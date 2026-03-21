# Feature Pack 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three forensic investigation features: contact recovery from encrypted devices (C3), cross-platform chronological timeline tab (A1), and inline media thumbnails in conversations (A4).

**Architecture:** C3 extends the parser layer — when primary contacts return empty, parsers reconstruct from WhatsApp/Telegram/SMS metadata and tag them `source='recovered'`. A1 adds a new Flask route + vanilla JS tab that UNIONs messages and call_logs with composite-key cursor pagination. A4 adds a `media_files` DB table, file extraction during parse, a streaming media route, and thumbnail rendering in conversation bubbles.

**Tech Stack:** Python/Flask 3.0, SQLite (FTS5), vanilla JS ES modules, CSS variables. Optional: `pillow-heif` for HEIC conversion.

**Spec:** `docs/superpowers/specs/2026-03-21-feature-pack-2-design.md`

**Run tests with:** `python -m pytest tests/ -v` (from project root)

**Test fixtures:** All new test files rely on `tests/conftest.py` for `app` and `client` fixtures — do NOT redefine them in new test files. The conftest fixture does `create_app(testing=True)` then sets `app.config["MT_CONFIG"]["server"]["database_path"]` and `app.config["MT_CONFIG"]["server"]["cases_dir"]`.

---

## File Map

**New files:**
- `app/routes/timeline.py` — GET /api/cases/<id>/timeline route
- `app/routes/media.py` — GET /api/cases/<id>/media/<media_id> route
- `static/js/timeline.js` — Timeline tab ES module
- `tests/test_timeline_routes.py`
- `tests/test_contact_recovery.py`
- `tests/test_media_extraction.py`

**Modified files:**
- `app/database.py` — add `contacts.source` migration + `media_files` table DDL
- `app/parsers/base.py` — add `_norm_phone()` static method, `source` kwarg to `_norm_contact()`, `media_files` field to `ParsedCase`
- `app/routes/cases.py` — update contacts INSERT to include `source`; add `media_files` arm to `_store_parsed()`; add contacts list endpoint; update messages query to include media join
- `app/parsers/ios_parser.py` — add `_recover_contacts_ios()` method; guard in `parse()`
- `app/parsers/android_parser.py` — add `_recover_contacts_android()` method; guard in `parse()`
- `app/__init__.py` — register `bp_timeline` and `bp_media` blueprints
- `templates/index.html` — add Timeline tab button + panel; lightbox dialog; script tags
- `static/js/cases.js` — wire `initTimeline()` on tab switch + in `openCase()`
- `static/js/conversations.js` — media thumbnail rendering + lightbox
- `static/style.css` — timeline CSS + `.msg-media-*` + `.media-lightbox`

---

## Task 1: DB Schema — contacts.source column + media_files table

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_database.py` (extend existing file)

- [ ] **Step 1: Read app/database.py**

  Read `app/database.py` in full. Note: `_SCHEMA` string contains all `CREATE TABLE IF NOT EXISTS` statements. `_migrate()` handles idempotent schema changes. Find the exact end of `_SCHEMA` (closing `"""`) and the end of `_migrate()`.

- [ ] **Step 2: Write failing tests — append to tests/test_database.py**

  ```python
  def test_contacts_source_column(app):
      """contacts table must have a source column defaulting to NULL."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          info = db.execute("PRAGMA table_info(contacts)").fetchall()
          cols = [r["name"] for r in info]
          assert "source" in cols

  def test_media_files_table_exists(app):
      """media_files table must exist with required columns."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          info = db.execute("PRAGMA table_info(media_files)").fetchall()
          cols = [r["name"] for r in info]
          for col in ["id", "case_id", "message_id", "filename", "mime_type", "size_bytes", "filepath"]:
              assert col in cols, f"Missing column: {col}"
  ```

- [ ] **Step 3: Run tests to verify they fail**
  ```bash
  python -m pytest tests/test_database.py::test_contacts_source_column tests/test_database.py::test_media_files_table_exists -v
  ```
  Expected: FAIL.

- [ ] **Step 4: Add media_files DDL to _SCHEMA**

  In `_SCHEMA` string, append before the closing `"""`:
  ```sql
  CREATE TABLE IF NOT EXISTS media_files (
      id           TEXT PRIMARY KEY,
      case_id      TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
      message_id   INTEGER,
      filename     TEXT NOT NULL,
      mime_type    TEXT NOT NULL,
      size_bytes   INTEGER,
      filepath     TEXT NOT NULL,
      extracted_at TEXT DEFAULT (datetime('now')),
      FOREIGN KEY (message_id) REFERENCES messages(id)
  );
  CREATE INDEX IF NOT EXISTS idx_media_files_case    ON media_files(case_id);
  CREATE INDEX IF NOT EXISTS idx_media_files_message ON media_files(message_id);
  ```

- [ ] **Step 5: Add contacts.source migration to _migrate()**

  At the end of `_migrate()`, add:
  ```python
  # Add source column to contacts (idempotent)
  try:
      conn.execute("ALTER TABLE contacts ADD COLUMN source TEXT DEFAULT NULL")
      conn.commit()
  except sqlite3.OperationalError:
      pass  # column already exists
  ```
  Ensure `import sqlite3` is at the top of `database.py` (it should already be).

- [ ] **Step 6: Run and verify**
  ```bash
  python -m pytest tests/test_database.py -v
  ```
  Expected: all pass including 2 new tests.

- [ ] **Step 7: Commit**
  ```bash
  git add app/database.py tests/test_database.py
  git commit -m "feat(db): add contacts.source migration and media_files table"
  ```

---

## Task 2: Base Parser — _norm_phone(), _norm_contact() source kwarg, ParsedCase.media_files

**Files:**
- Modify: `app/parsers/base.py`

- [ ] **Step 1: Read app/parsers/base.py in full**

  Confirm the current `ParsedCase` dataclass fields and the full `_norm_contact()` signature. Confirm `_norm_phone` does NOT already exist here.

- [ ] **Step 2: Add _norm_phone() static method to BaseParser**

  After the existing `_norm_contact()` method, add:
  ```python
  @staticmethod
  def _norm_phone(phone: str) -> str:
      """Normalize a phone number to a stable dedup key (digits + leading +)."""
      if not phone:
          return ""
      phone = str(phone).strip()
      # Keep leading + for international numbers
      prefix = "+" if phone.startswith("+") else ""
      digits = "".join(c for c in phone if c.isdigit())
      return prefix + digits
  ```

- [ ] **Step 3: Add `source` kwarg to _norm_contact()**

  Change the method signature and return value:
  ```python
  @staticmethod
  def _norm_contact(
      name: str = "",
      phone: str = "",
      email: str = "",
      source_app: str = "device_contacts",
      raw: dict | None = None,
      source: str | None = None,
  ) -> dict[str, Any]:
      return {
          "name": name or "",
          "phone": phone or "",
          "email": email or "",
          "source_app": source_app,
          "raw_json": raw or {},
          "source": source,   # None = normal, 'recovered' = reconstructed
      }
  ```

- [ ] **Step 4: Add media_files field to ParsedCase**

  ```python
  @dataclass
  class ParsedCase:
      """Normalized output from any mobile forensic format."""
      format: str
      device_info: dict[str, Any] = field(default_factory=dict)
      contacts: list[dict[str, Any]] = field(default_factory=list)
      messages: list[dict[str, Any]] = field(default_factory=list)
      call_logs: list[dict[str, Any]] = field(default_factory=list)
      media_files: list[dict[str, Any]] = field(default_factory=list)
      # Each dict: { message_id: int|None, filename: str, mime_type: str,
      #              size_bytes: int, tmp_path: str }
      raw_db_paths: list[Path] = field(default_factory=list)
      warnings: list[str] = field(default_factory=list)
  ```

- [ ] **Step 5: Run full suite — no regressions**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all existing tests pass (`source=None` default is backwards-compatible).

- [ ] **Step 6: Commit**
  ```bash
  git add app/parsers/base.py
  git commit -m "feat(parsers): _norm_phone(), source kwarg on _norm_contact, media_files in ParsedCase"
  ```

---

## Task 3: _store_parsed() — propagate source + media_files arm

**Files:**
- Modify: `app/routes/cases.py`

- [ ] **Step 1: Read app/routes/cases.py**

  Read the full `_store_parsed()` function (lines ~473-491). Note the contacts INSERT and how `cfg = current_app.config["MT_CONFIG"]` is used elsewhere (e.g. lines 177, 194, 299) to get `cases_dir`.

- [ ] **Step 2: Update contacts INSERT to include source column**

  Replace the existing contacts INSERT:
  ```python
  db.execute(
      "INSERT INTO contacts"
      " (case_id, name, phone, email, source_app, raw_json, source)"
      " VALUES (?,?,?,?,?,?,?)",
      (case_id, c["name"], c["phone"], c["email"],
       c["source_app"], json.dumps(c.get("raw_json") or {}), c.get("source")),
  )
  ```

- [ ] **Step 3: Add media_files arm to _store_parsed()**

  Add these imports at the TOP of `cases.py` (not inline in the function):
  ```python
  import uuid
  import shutil
  ```

  After the `for cl in parsed.call_logs:` loop and before `db.commit()`, add:
  ```python
  # Media files (A4) — copy extracted media to cases dir and record in DB
  cfg = current_app.config["MT_CONFIG"]
  cases_dir = Path(cfg["server"]["cases_dir"])
  media_dir = cases_dir / case_id / "media"
  media_dir.mkdir(parents=True, exist_ok=True)

  for mf in getattr(parsed, "media_files", []):
      if mf.get("size_bytes", 0) > 50 * 1024 * 1024:
          continue  # skip files > 50 MB
      tmp = Path(mf["tmp_path"])
      if not tmp.exists():
          continue
      ext = tmp.suffix.lower()
      media_id = str(uuid.uuid4())
      dest = media_dir / f"{media_id}{ext}"
      shutil.copy2(tmp, dest)
      rel_path = f"{case_id}/media/{media_id}{ext}"
      db.execute(
          "INSERT INTO media_files"
          " (id, case_id, message_id, filename, mime_type, size_bytes, filepath)"
          " VALUES (?,?,?,?,?,?,?)",
          (media_id, case_id, mf.get("message_id"),
           mf["filename"], mf["mime_type"], mf.get("size_bytes"), rel_path),
      )
  ```

- [ ] **Step 4: Add GET /api/cases/<id>/contacts endpoint**

  The recovery test needs a contacts list API endpoint. Read `cases.py` to find where case routes are defined. Add this route in `cases.py` (or wherever the case blueprint routes live):
  ```python
  @bp_cases.get("/cases/<case_id>/contacts")
  def get_contacts(case_id):
      db = get_db()
      if not db.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone():
          abort(404)
      rows = db.execute(
          "SELECT id, name, phone, email, source_app, source FROM contacts WHERE case_id=?",
          (case_id,),
      ).fetchall()
      return jsonify([dict(r) for r in rows])
  ```

- [ ] **Step 5: Update messages query to include media**

  Find the route that returns messages for a case (used by conversations.js). It likely queries `messages` table directly. Update to LEFT JOIN media_files — use a correlated subquery to avoid duplicate rows when a message has multiple media files:
  ```python
  rows = db.execute("""
      SELECT m.*,
             mf.id         AS media_id,
             mf.mime_type  AS mime_type,
             mf.filename   AS media_filename,
             mf.size_bytes AS media_size
      FROM messages m
      LEFT JOIN (
          SELECT * FROM media_files mf2
          WHERE mf2.id = (
              SELECT id FROM media_files
              WHERE message_id = mf2.message_id
              ORDER BY extracted_at ASC LIMIT 1
          )
      ) mf ON mf.message_id = m.id
      WHERE m.case_id = ?
      ORDER BY m.timestamp ASC
  """, (case_id,)).fetchall()
  ```

- [ ] **Step 6: Run full suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all pass.

- [ ] **Step 7: Commit**
  ```bash
  git add app/routes/cases.py
  git commit -m "feat(cases): contacts.source in INSERT, media_files arm in _store_parsed, contacts endpoint"
  ```

---

## Task 4: C3 — Contact Recovery Logic

**Files:**
- Modify: `app/parsers/ios_parser.py`
- Modify: `app/parsers/android_parser.py`
- Create: `tests/test_contact_recovery.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/test_contact_recovery.py`. Note: `app` and `client` fixtures come automatically from `tests/conftest.py` — do NOT redefine them.

  ```python
  """Tests for encrypted-device contact recovery (C3)."""
  import sqlite3
  import uuid
  from pathlib import Path
  import pytest

  def _make_wa_db(path: Path):
      """Create a minimal wa.db with two WhatsApp contacts."""
      path.parent.mkdir(parents=True, exist_ok=True)
      conn = sqlite3.connect(str(path))
      conn.execute("CREATE TABLE wa_contacts (jid TEXT, display_name TEXT, number TEXT)")
      conn.execute("INSERT INTO wa_contacts VALUES ('1@s.whatsapp.net', 'Alice', '+15550101')")
      conn.execute("INSERT INTO wa_contacts VALUES ('2@s.whatsapp.net', 'Bob', '+15550202')")
      conn.commit()
      conn.close()

  def test_ios_recovery_from_whatsapp(tmp_path):
      """_recover_contacts_ios returns contacts from wa.db when called."""
      from app.parsers.ios_parser import iOSParser
      wa_db = tmp_path / "wa.db"
      _make_wa_db(wa_db)
      parser = iOSParser.__new__(iOSParser)
      warnings = []
      recovered = parser._recover_contacts_ios(
          wa_db_path=wa_db, tg_db_path=None, parsed_messages=[], warnings=warnings
      )
      assert len(recovered) == 2
      assert all(c["source"] == "recovered" for c in recovered)
      names = {c["name"] for c in recovered}
      assert "Alice" in names and "Bob" in names

  def test_recovery_deduplication(tmp_path):
      """Same normalized phone in WhatsApp + SMS yields one contact."""
      from app.parsers.ios_parser import iOSParser
      wa_db = tmp_path / "wa.db"
      _make_wa_db(wa_db)
      # SMS message from Alice with same number as WhatsApp (different formatting)
      sms_messages = [{
          "platform": "sms", "direction": "incoming", "sender": "Alice",
          "body": "hi", "timestamp": "2021-01-01T10:00:00",
          "thread_id": "+15550101", "recipient": None,
          "raw_json": {"address": "+1-555-0101", "contact_name": "Alice"},
      }]
      parser = iOSParser.__new__(iOSParser)
      recovered = parser._recover_contacts_ios(
          wa_db_path=wa_db, tg_db_path=None,
          parsed_messages=sms_messages, warnings=[]
      )
      alice_contacts = [c for c in recovered if c["name"] == "Alice"]
      assert len(alice_contacts) == 1, "Dedup failed: Alice appears more than once"

  def test_android_recovery_from_whatsapp(tmp_path):
      """_recover_contacts_android returns contacts from wa.db."""
      from app.parsers.android_parser import AndroidParser
      wa_db = tmp_path / "wa.db"
      _make_wa_db(wa_db)
      parser = AndroidParser.__new__(AndroidParser)
      warnings = []
      recovered = parser._recover_contacts_android(
          wa_db_path=wa_db, tg_db_path=None, parsed_messages=[], warnings=warnings
      )
      assert len(recovered) == 2
      assert all(c["source"] == "recovered" for c in recovered)

  def test_recovered_contacts_api(client, app, tmp_path):
      """GET /api/cases/<id>/contacts returns source field for recovered contacts."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "RecovTest"))
          db.execute(
              "INSERT INTO contacts"
              " (case_id, name, phone, email, source_app, raw_json, source)"
              " VALUES (?,?,?,?,?,?,?)",
              (cid, "Alice", "+15550101", "", "whatsapp_contacts", "{}", "recovered"),
          )
          db.commit()
      resp = client.get(f"/api/cases/{cid}/contacts")
      assert resp.status_code == 200
      contacts = resp.get_json()
      alice = next((c for c in contacts if c["name"] == "Alice"), None)
      assert alice is not None
      assert alice.get("source") == "recovered"

  def test_parse_recovery_skipped_when_contacts_present(tmp_path):
      """When AddressBook has contacts, recovery list must be empty (not called)."""
      from app.parsers.ios_parser import iOSParser
      # When primary contacts exist, caller guards _recover_contacts_ios — test
      # the guard by confirming calling with empty WA db returns empty list
      parser = iOSParser.__new__(iOSParser)
      # No wa.db, no tg.db, no messages → nothing to recover
      recovered = parser._recover_contacts_ios(
          wa_db_path=tmp_path / "nonexistent.db",
          tg_db_path=None, parsed_messages=[], warnings=[]
      )
      assert recovered == []
  ```

- [ ] **Step 2: Run tests to verify they fail**
  ```bash
  python -m pytest tests/test_contact_recovery.py -v
  ```
  Expected: FAIL with `ImportError` or `AttributeError` — methods don't exist yet.

- [ ] **Step 3: Implement _recover_contacts_ios() in ios_parser.py**

  Read `app/parsers/ios_parser.py`. Note the class is named `iOSParser`. Add this method to the class (after `_read_calls`):

  ```python
  def _recover_contacts_ios(
      self,
      wa_db_path,
      tg_db_path,
      parsed_messages: list,
      warnings: list,
  ) -> list:
      """Reconstruct contacts from messaging metadata when AddressBook is empty."""
      import sqlite3 as _sq3
      recovered: dict[str, dict] = {}  # normalized_phone → contact dict

      def _add(name, phone, source_app):
          norm = self._norm_phone(phone)
          key = norm or name  # fall back to name if phone is empty
          if key and key not in recovered:
              recovered[key] = self._norm_contact(
                  name=name, phone=norm, email="",
                  source_app=source_app, source="recovered"
              )

      # 1. WhatsApp wa_contacts
      if wa_db_path and Path(wa_db_path).exists():
          try:
              conn = _sq3.connect(str(wa_db_path))
              conn.row_factory = _sq3.Row
              for row in conn.execute(
                  "SELECT display_name, number FROM wa_contacts"
                  " WHERE display_name IS NOT NULL AND display_name != ''"
              ).fetchall():
                  _add(row["display_name"], row["number"] or "", "whatsapp_contacts")
              conn.close()
          except Exception as e:
              warnings.append(f"Contact recovery (WhatsApp iOS): {e}")

      # 2. Telegram peers table
      if tg_db_path and Path(tg_db_path).exists():
          try:
              conn = _sq3.connect(str(tg_db_path))
              conn.row_factory = _sq3.Row
              for row in conn.execute(
                  "SELECT phone, first_name, last_name FROM peers"
                  " WHERE phone IS NOT NULL AND phone != ''"
              ).fetchall():
                  name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
                  _add(name or row["phone"], row["phone"], "telegram_peers")
              conn.close()
          except Exception as e:
              warnings.append(f"Contact recovery (Telegram iOS): {e}")

      # 3. SMS sender names from already-parsed messages
      for msg in parsed_messages:
          if msg.get("platform") != "sms":
              continue
          raw = msg.get("raw_json") or {}
          name = raw.get("contact_name") or ""
          phone = raw.get("address") or msg.get("sender") or ""
          if name and phone:
              _add(name, phone, "sms_metadata")

      return list(recovered.values())
  ```

  Then in `parse()`, after `result.contacts = self._read_contacts(...)`, add the guard:
  ```python
  # C3: recover contacts from messaging metadata if AddressBook is empty
  if not result.contacts:
      wa_path = db_paths.get("whatsapp")  # path to wa.db already found by parser
      tg_path = db_paths.get("telegram")  # path to cache4.db already found
      recovered = self._recover_contacts_ios(
          wa_db_path=wa_path, tg_db_path=tg_path,
          parsed_messages=result.messages, warnings=warnings
      )
      result.contacts.extend(recovered)
      if recovered:
          warnings.append(
              f"AddressBook empty — recovered {len(recovered)} contacts from messaging data"
          )
  ```

  Note: `db_paths` is a dict already built in `parse()` containing resolved paths to each DB. Check the exact key names used (e.g. `"whatsapp"` for `wa.db`, `"telegram"` for `cache4.db`) by reading the `_build_wanted_map()` or equivalent method.

- [ ] **Step 4: Implement _recover_contacts_android() in android_parser.py**

  Read `app/parsers/android_parser.py`. Add to `AndroidParser` class:

  ```python
  def _recover_contacts_android(
      self,
      wa_db_path,
      tg_db_path,
      parsed_messages: list,
      warnings: list,
  ) -> list:
      """Reconstruct contacts from messaging metadata when contacts2.db is empty."""
      import sqlite3 as _sq3
      recovered: dict[str, dict] = {}

      def _add(name, phone, source_app):
          norm = self._norm_phone(phone)
          key = norm or name
          if key and key not in recovered:
              recovered[key] = self._norm_contact(
                  name=name, phone=norm, email="",
                  source_app=source_app, source="recovered"
              )

      # 1. WhatsApp wa_contacts
      if wa_db_path and Path(wa_db_path).exists():
          try:
              conn = _sq3.connect(str(wa_db_path))
              conn.row_factory = _sq3.Row
              for row in conn.execute(
                  "SELECT display_name, number FROM wa_contacts"
                  " WHERE display_name IS NOT NULL AND display_name != ''"
              ).fetchall():
                  _add(row["display_name"], row["number"] or "", "whatsapp_contacts")
              conn.close()
          except Exception as e:
              warnings.append(f"Contact recovery (WhatsApp Android): {e}")

      # 2. Telegram user_contacts_v7
      if tg_db_path and Path(tg_db_path).exists():
          try:
              conn = _sq3.connect(str(tg_db_path))
              conn.row_factory = _sq3.Row
              for row in conn.execute(
                  "SELECT uid, fname, sname FROM user_contacts_v7"
              ).fetchall():
                  name = f"{row['fname'] or ''} {row['sname'] or ''}".strip()
                  _add(name or str(row["uid"]), "", "telegram_contacts")
              conn.close()
          except Exception as e:
              warnings.append(f"Contact recovery (Telegram Android): {e}")

      # 3. SMS metadata
      for msg in parsed_messages:
          if msg.get("platform") != "sms":
              continue
          raw = msg.get("raw_json") or {}
          name = raw.get("contact_name") or ""
          phone = raw.get("address") or msg.get("sender") or ""
          if name and phone:
              _add(name, phone, "sms_metadata")

      return list(recovered.values())
  ```

  In `parse()`, after contacts are populated, add guard:
  ```python
  if not result.contacts:
      wa_path = db_paths.get("whatsapp")
      tg_path = db_paths.get("telegram")
      recovered = self._recover_contacts_android(
          wa_db_path=wa_path, tg_db_path=tg_path,
          parsed_messages=result.messages, warnings=warnings
      )
      result.contacts.extend(recovered)
      if recovered:
          warnings.append(
              f"contacts2.db empty — recovered {len(recovered)} contacts from messaging data"
          )
  ```

- [ ] **Step 5: Run contact recovery tests**
  ```bash
  python -m pytest tests/test_contact_recovery.py -v
  ```
  Expected: all 5 tests pass.

- [ ] **Step 6: Run full suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all pass.

- [ ] **Step 7: Commit**
  ```bash
  git add app/parsers/ios_parser.py app/parsers/android_parser.py tests/test_contact_recovery.py
  git commit -m "feat(C3): contact recovery from WhatsApp/Telegram/SMS when AddressBook empty"
  ```

---

## Task 5: A1 — Timeline Route

**Files:**
- Create: `app/routes/timeline.py`
- Modify: `app/__init__.py`
- Create: `tests/test_timeline_routes.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/test_timeline_routes.py` (uses `app`/`client` from conftest.py):

  ```python
  """Tests for GET /api/cases/<id>/timeline (A1)."""
  import uuid

  def _insert_case(db, title="TL Test"):
      cid = str(uuid.uuid4())
      db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, title))
      db.commit()
      return cid

  def _insert_msg(db, cid, platform, ts, body="hi", direction="incoming"):
      db.execute(
          "INSERT INTO messages (case_id, platform, direction, sender, recipient,"
          " body, timestamp, thread_id, raw_json) VALUES (?,?,?,?,?,?,?,?,?)",
          (cid, platform, direction, "Alice", None, body, ts, "t1", "{}"),
      )
      db.commit()

  def _insert_call(db, cid, ts, platform="sms", direction="incoming"):
      db.execute(
          "INSERT INTO call_logs (case_id, number, direction, duration_s, timestamp, platform)"
          " VALUES (?,?,?,?,?,?)",
          (cid, "+15559999", direction, 120, ts, platform),
      )
      db.commit()

  def test_timeline_empty_case(client, app):
      with app.app_context():
          from app.database import get_db
          cid = _insert_case(get_db())
      resp = client.get(f"/api/cases/{cid}/timeline")
      assert resp.status_code == 200
      data = resp.get_json()
      assert data["items"] == []
      assert data["next_cursor"] is None

  def test_timeline_merges_and_sorts(client, app):
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = _insert_case(db)
          _insert_msg(db, cid, "sms",      "2021-03-14T09:00:00")
          _insert_msg(db, cid, "whatsapp", "2021-03-14T10:00:00")
          _insert_call(db, cid,             "2021-03-14T11:00:00", platform="phone")
      resp = client.get(f"/api/cases/{cid}/timeline")
      items = resp.get_json()["items"]
      assert len(items) == 3
      timestamps = [i["timestamp"] for i in items]
      assert timestamps == sorted(timestamps)
      assert any(i["type"] == "message" for i in items)
      assert any(i["type"] == "call" for i in items)

  def test_timeline_platform_filter_excludes(client, app):
      """platform=sms filter must exclude whatsapp messages."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = _insert_case(db)
          _insert_msg(db, cid, "sms",      "2021-01-01T09:00:00")
          _insert_msg(db, cid, "whatsapp", "2021-01-01T10:00:00")
      resp = client.get(f"/api/cases/{cid}/timeline?platforms=sms")
      items = resp.get_json()["items"]
      assert all(i["platform"] == "sms" for i in items)
      assert len(items) == 1

  def test_timeline_limit_capped_at_500(client, app):
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = _insert_case(db)
          _insert_msg(db, cid, "sms", "2021-01-01T09:00:00")
      resp = client.get(f"/api/cases/{cid}/timeline?limit=9999")
      assert resp.status_code == 200  # no crash
      assert len(resp.get_json()["items"]) <= 500

  def test_timeline_pagination_no_duplicates(client, app):
      """Two pages must together equal all items with no duplicates, even with tie timestamps."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = _insert_case(db)
          # 5 messages at identical timestamp — stresses tie-breaking
          for i in range(5):
              _insert_msg(db, cid, "sms", "2021-01-01T12:00:00", body=f"msg{i}")
      resp1 = client.get(f"/api/cases/{cid}/timeline?limit=3")
      data1 = resp1.get_json()
      assert len(data1["items"]) == 3
      assert data1["next_cursor"] is not None

      nc = data1["next_cursor"]
      resp2 = client.get(
          f"/api/cases/{cid}/timeline?limit=3"
          f"&cursor_ts={nc['ts']}&cursor_key={nc['key']}"
      )
      data2 = resp2.get_json()
      assert len(data2["items"]) == 2

      # Use row_key (namespaced) for dedup — numeric id can overlap across tables
      all_keys = [i["row_key"] for i in data1["items"]] + [i["row_key"] for i in data2["items"]]
      assert len(all_keys) == len(set(all_keys)), "Duplicate items across pages"
  ```

- [ ] **Step 2: Run tests to verify they fail**
  ```bash
  python -m pytest tests/test_timeline_routes.py -v
  ```
  Expected: FAIL with 404.

- [ ] **Step 3: Create app/routes/timeline.py**

  ```python
  """GET /api/cases/<id>/timeline — chronological cross-platform event feed."""
  import json
  from flask import Blueprint, jsonify, request, abort
  from app.database import get_db

  bp_timeline = Blueprint("timeline", __name__, url_prefix="/api")


  def _platform_risk_map(db, case_id: str) -> dict[str, str]:
      """Return {platform: 'HIGH'|'CRITICAL'} from the most recent analysis per artifact."""
      risk_map: dict[str, str] = {}
      seen: set[str] = set()
      for row in db.execute(
          "SELECT artifact_key, result_parsed FROM analysis_results"
          " WHERE case_id=? ORDER BY created_at DESC",
          (case_id,),
      ).fetchall():
          ak = row["artifact_key"] or ""
          if ak in seen:
              continue
          seen.add(ak)
          try:
              parsed = json.loads(row["result_parsed"] or "null") or {}
              rl = (parsed.get("risk_level") or "").upper()
              if rl in ("HIGH", "CRITICAL"):
                  platform = ak.split("_")[0]
                  risk_map.setdefault(platform, rl)
          except Exception:
              pass
      return risk_map


  @bp_timeline.get("/cases/<case_id>/timeline")
  def get_timeline(case_id):
      db = get_db()
      if not db.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone():
          abort(404)

      limit = min(int(request.args.get("limit", 100)), 500)
      cursor_ts  = request.args.get("cursor_ts", "")
      cursor_key = request.args.get("cursor_key", "")
      platforms_raw = request.args.get("platforms", "")
      platform_filter = [p.strip() for p in platforms_raw.split(",") if p.strip()]

      # row_key is namespaced to prevent id collision between messages and call_logs
      # (both tables use INTEGER PRIMARY KEY AUTOINCREMENT starting from 1)
      msg_sql = (
          "SELECT id, 'message' AS type, platform, timestamp, direction,"
          "       sender, recipient, body, thread_id,"
          "       'msg-' || id AS row_key"
          " FROM messages WHERE case_id=:cid"
      )
      call_sql = (
          "SELECT id, 'call' AS type, platform, timestamp, direction,"
          "       CASE WHEN direction='incoming' THEN number ELSE NULL END AS sender,"
          "       CASE WHEN direction='outgoing' THEN number ELSE NULL END AS recipient,"
          "       NULL AS body, NULL AS thread_id,"
          "       'call-' || id AS row_key"
          " FROM call_logs WHERE case_id=:cid"
      )

      params: dict = {"cid": case_id}

      if platform_filter:
          ph = ",".join(f":pf{i}" for i in range(len(platform_filter)))
          msg_sql  += f" AND platform IN ({ph})"
          call_sql += f" AND platform IN ({ph})"
          for i, pf in enumerate(platform_filter):
              params[f"pf{i}"] = pf

      sql = f"SELECT * FROM ({msg_sql} UNION ALL {call_sql})"

      if cursor_ts and cursor_key:
          sql += (
              " WHERE (timestamp > :cur_ts)"
              " OR (timestamp = :cur_ts AND row_key > :cur_key)"
          )
          params["cur_ts"]  = cursor_ts
          params["cur_key"] = cursor_key

      sql += " ORDER BY timestamp ASC, row_key ASC LIMIT :lim"
      params["lim"] = limit + 1  # fetch one extra to detect next page

      rows = db.execute(sql, params).fetchall()
      has_more = len(rows) > limit
      rows = rows[:limit]

      risk_map = _platform_risk_map(db, case_id)

      items = []
      for r in rows:
          item = {
              "id":       r["id"],
              "type":     r["type"],
              "platform": r["platform"],
              "timestamp": r["timestamp"],
              "direction": r["direction"],
              "sender":   r["sender"],
              "recipient": r["recipient"],
              "body":     r["body"],
              "thread_id": r["thread_id"],
              "row_key":  r["row_key"],
              "risk_level": risk_map.get(r["platform"]),
          }
          if r["type"] == "call":
              cl = db.execute(
                  "SELECT duration_s FROM call_logs WHERE id=?", (r["id"],)
              ).fetchone()
              item["duration_seconds"] = cl["duration_s"] if cl else None
          items.append(item)

      next_cursor = None
      if has_more and rows:
          last = rows[-1]
          next_cursor = {"ts": last["timestamp"], "key": last["row_key"]}

      return jsonify({"items": items, "next_cursor": next_cursor})
  ```

- [ ] **Step 4: Register blueprint in app/__init__.py**

  Read `app/__init__.py`. Find where other blueprints are registered (e.g. `from app.routes.cases import bp_cases; app.register_blueprint(bp_cases)`). Add:
  ```python
  from app.routes.timeline import bp_timeline
  app.register_blueprint(bp_timeline)
  ```

- [ ] **Step 5: Run tests**
  ```bash
  python -m pytest tests/test_timeline_routes.py -v
  ```
  Expected: all 5 pass.

- [ ] **Step 6: Run full suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all pass.

- [ ] **Step 7: Commit**
  ```bash
  git add app/routes/timeline.py app/__init__.py tests/test_timeline_routes.py
  git commit -m "feat(A1): GET /api/cases/<id>/timeline with namespaced cursor pagination"
  ```

---

## Task 6: A1 — Timeline Frontend

**Files:**
- Modify: `templates/index.html`
- Create: `static/js/timeline.js`
- Modify: `static/js/cases.js`
- Modify: `static/style.css`

- [ ] **Step 1: Add Timeline tab to index.html**

  In the tab bar (around line 182), insert after the Conversations button and before Analysis:
  ```html
  <button class="tab-btn" data-tab="tab-timeline" role="tab" aria-selected="false" aria-controls="tab-timeline">Timeline</button>
  ```

- [ ] **Step 2: Add Timeline tab panel to index.html**

  After the closing `</div>` of the conversations panel and before the analysis panel:
  ```html
  <!-- Timeline tab (A1) -->
  <div id="tab-timeline" class="tab-panel" role="tabpanel">
    <div class="tl-header">
      <div class="tl-filter-pills" id="tl-platform-pills">
        <button class="tl-pill active" data-platform="">All</button>
        <button class="tl-pill" data-platform="sms">SMS</button>
        <button class="tl-pill" data-platform="whatsapp">WhatsApp</button>
        <button class="tl-pill" data-platform="telegram">Telegram</button>
        <button class="tl-pill" data-platform="signal">Signal</button>
        <button class="tl-pill" data-platform="calls">Calls</button>
      </div>
      <input type="date" id="tl-date-jump" class="tl-date-input" aria-label="Jump to date" />
    </div>
    <div id="tl-feed" class="tl-feed"></div>
    <div id="tl-load-more-wrap" style="text-align:center;padding:16px;display:none">
      <button id="tl-load-more" class="btn-secondary">Load more</button>
    </div>
  </div>
  ```

- [ ] **Step 3: Create static/js/timeline.js**

  ```javascript
  /**
   * timeline.js — Cross-platform chronological timeline tab (A1).
   */
  import { apiFetch } from "./api.js";

  let _caseId = null;
  let _nextCursor = null;
  let _activePlatforms = new Set(); // empty = All

  const _PLATFORM_COLORS = {
    sms:      "var(--info)",
    whatsapp: "#25d366",
    telegram: "#0088cc",
    signal:   "#3a76f0",
    calls:    "var(--text-muted)",
    phone:    "var(--text-muted)",
  };

  export async function initTimeline(caseId) {
    _caseId = caseId;
    _nextCursor = null;
    _activePlatforms = new Set();
    document.getElementById("tl-feed").innerHTML = "";
    _wirePills();
    _wireDateJump();
    _wireLoadMore();
    _fetchAndRender(true).catch(console.error);
  }

  function _wirePills() {
    document.querySelectorAll("#tl-platform-pills .tl-pill").forEach(btn => {
      btn.addEventListener("click", () => {
        const plat = btn.dataset.platform;
        if (!plat) {
          _activePlatforms.clear();
          document.querySelectorAll("#tl-platform-pills .tl-pill")
            .forEach(b => b.classList.toggle("active", !b.dataset.platform));
        } else {
          document.querySelector("#tl-platform-pills .tl-pill[data-platform='']")
            .classList.remove("active");
          btn.classList.toggle("active");
          if (btn.classList.contains("active")) {
            _activePlatforms.add(plat);
          } else {
            _activePlatforms.delete(plat);
            if (!_activePlatforms.size) {
              document.querySelector("#tl-platform-pills .tl-pill[data-platform='']")
                .classList.add("active");
            }
          }
        }
        _nextCursor = null;
        document.getElementById("tl-feed").innerHTML = "";
        _fetchAndRender(true).catch(console.error);
      });
    });
  }

  function _wireDateJump() {
    document.getElementById("tl-date-jump").addEventListener("change", e => {
      const date = e.target.value;
      if (!date) return;
      _nextCursor = { ts: `${date}T00:00:00`, key: "" };
      document.getElementById("tl-feed").innerHTML = "";
      _fetchAndRender(false).catch(console.error);
    });
  }

  function _wireLoadMore() {
    document.getElementById("tl-load-more").addEventListener("click", () => {
      _fetchAndRender(false).catch(console.error);
    });
  }

  async function _fetchAndRender(reset) {
    if (!_caseId) return;
    const params = new URLSearchParams({ limit: 100 });
    if (_activePlatforms.size) params.set("platforms", [..._activePlatforms].join(","));
    if (_nextCursor) {
      params.set("cursor_ts",  _nextCursor.ts);
      params.set("cursor_key", _nextCursor.key || "");
    }
    try {
      const data = await apiFetch(`/api/cases/${_caseId}/timeline?${params}`);
      _nextCursor = data.next_cursor || null;
      _renderItems(data.items, reset);
      document.getElementById("tl-load-more-wrap").style.display = _nextCursor ? "" : "none";
    } catch (err) {
      document.getElementById("tl-feed").innerHTML =
        `<div class="tl-empty">Failed to load timeline: ${_esc(err.message)}</div>`;
    }
  }

  function _renderItems(items, reset) {
    const feed = document.getElementById("tl-feed");
    if (reset) {
      feed.innerHTML = "";
      delete feed.dataset.lastDate;
    }

    if (!items.length && reset) {
      feed.innerHTML = `<div class="tl-empty">No messages in this case yet</div>`;
      return;
    }

    let lastDate = feed.dataset.lastDate || null;

    items.forEach(item => {
      const dateStr = (item.timestamp || "").slice(0, 10);
      if (dateStr !== lastDate) {
        lastDate = dateStr;
        const sep = document.createElement("div");
        sep.className = "tl-date-sep";
        sep.textContent = _formatDateSep(dateStr);
        feed.appendChild(sep);
      }

      const row = document.createElement("div");
      row.className = "tl-row";
      if (item.risk_level) row.classList.add(`tl-risk-${item.risk_level.toLowerCase()}`);

      const color = _PLATFORM_COLORS[item.platform] || "var(--accent)";
      const time  = (item.timestamp || "").slice(11, 16);
      const dir   = item.direction === "incoming" ? "←" : "→";
      const sender = _esc(item.sender || item.recipient || "—");
      const isTruncated = item.type !== "call" && (item.body || "").length > 120;
      const bodyText = item.type === "call"
        ? `📞 Call · ${_fmtDuration(item.duration_seconds)}`
        : _esc((item.body || "").slice(0, 120));

      const badge    = document.createElement("span");
      badge.className = "tl-badge";
      badge.style.cssText = `background:${color}22;color:${color};border-color:${color}44`;
      badge.textContent = item.platform;

      const timeEl  = document.createElement("span");
      timeEl.className = "tl-time";
      timeEl.textContent = time;

      const dirEl   = document.createElement("span");
      dirEl.className = "tl-dir";
      dirEl.textContent = dir;

      const senderEl = document.createElement("span");
      senderEl.className = "tl-sender";
      senderEl.textContent = sender;

      const bodyEl  = document.createElement("span");
      bodyEl.className = "tl-body" + (isTruncated ? " tl-body--truncated" : "");
      bodyEl.textContent = bodyText + (isTruncated ? "…" : "");

      row.append(badge, timeEl, dirEl, senderEl, bodyEl);

      if (item.risk_level) {
        const rb = document.createElement("span");
        rb.className = `tl-risk-badge risk-${item.risk_level.toLowerCase()}`;
        rb.textContent = item.risk_level;
        row.appendChild(rb);
      }

      if (isTruncated) {
        bodyEl.addEventListener("click", e => {
          e.stopPropagation();
          bodyEl.textContent = item.body;
          bodyEl.classList.remove("tl-body--truncated");
        });
      }

      if (item.thread_id && item.type === "message") {
        row.style.cursor = "pointer";
        row.addEventListener("click", () => {
          // Dispatch with bubbles:true so window listener in conversations.js fires
          window.dispatchEvent(new CustomEvent("mt:open-thread", {
            detail: { platform: item.platform, thread: item.thread_id },
            bubbles: true,
          }));
          const convBtn = document.querySelector('.tab-btn[data-tab="tab-conversations"]');
          if (convBtn) convBtn.click();
        });
      }

      feed.appendChild(row);
    });

    feed.dataset.lastDate = lastDate || "";
  }

  function _formatDateSep(dateStr) {
    try {
      const d = new Date(dateStr + "T12:00:00");
      return d.toLocaleDateString("en-GB", {
        weekday: "long", year: "numeric", month: "long", day: "numeric"
      });
    } catch { return dateStr; }
  }

  function _fmtDuration(secs) {
    if (!secs) return "—";
    const m = Math.floor(secs / 60), s = secs % 60;
    return m ? `${m}m ${s}s` : `${s}s`;
  }

  function _esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  ```

- [ ] **Step 4: Wire initTimeline in cases.js**

  Read `static/js/cases.js`. At the top, add import:
  ```javascript
  import { initTimeline } from "./timeline.js";
  ```

  In the tab click handler block (where `initConversations`, `initCorrelation` etc. are), add:
  ```javascript
  if (btn.dataset.tab === "tab-timeline" && activeCaseId) {
    initTimeline(activeCaseId);
  }
  ```

  In `openCase()`, in the block that checks already-active tabs (look for existing `if (tab-conversations is active)` pattern), add:
  ```javascript
  if (document.querySelector('.tab-btn[data-tab="tab-timeline"]')?.classList.contains("active")) {
    initTimeline(id);
  }
  ```

- [ ] **Step 5: Add script tag to index.html**

  After `ioc.js` script tag:
  ```html
  <script type="module" src="/static/js/timeline.js?v=20260321e"></script>
  ```

  Change `cases.js?v=20260308` → `cases.js?v=20260321e`.

- [ ] **Step 6: Add Timeline CSS to style.css**

  Append to `static/style.css`:
  ```css
  /* ── Timeline Tab (A1) ─────────────────────────────────────────────────── */
  .tl-header { display:flex; align-items:center; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
  .tl-filter-pills { display:flex; gap:6px; flex-wrap:wrap; }
  .tl-pill { background:var(--surface2); border:1px solid var(--border); color:var(--text-muted);
    padding:4px 12px; border-radius:16px; font-size:0.8rem; cursor:pointer; }
  .tl-pill.active { background:var(--accent); border-color:var(--accent); color:#fff; }
  .tl-date-input { background:var(--surface2); border:1px solid var(--border); color:var(--text);
    padding:4px 10px; border-radius:6px; font-size:0.85rem; }
  .tl-feed { display:flex; flex-direction:column; gap:2px; }
  .tl-date-sep { font-size:0.75rem; color:var(--text-muted); font-weight:600;
    text-transform:uppercase; letter-spacing:0.05em; padding:12px 0 4px;
    border-bottom:1px solid var(--border); margin-bottom:4px; }
  .tl-row { display:flex; align-items:baseline; gap:8px; padding:5px 8px; border-radius:6px;
    font-size:0.85rem; }
  .tl-row:hover { background:var(--surface2); }
  .tl-row.tl-risk-high     { border-left:2px solid var(--danger,#f85149); padding-left:6px; }
  .tl-row.tl-risk-critical { border-left:2px solid #f85149; padding-left:6px; }
  .tl-badge { font-size:0.7rem; padding:1px 6px; border-radius:10px; border:1px solid;
    text-transform:uppercase; letter-spacing:0.04em; flex-shrink:0; }
  .tl-time   { color:var(--text-muted); font-size:0.8rem; min-width:36px; flex-shrink:0; }
  .tl-dir    { color:var(--text-muted); font-size:0.8rem; flex-shrink:0; }
  .tl-sender { color:var(--accent); font-weight:500; min-width:80px; flex-shrink:0;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:160px; }
  .tl-body   { color:var(--text); flex:1; overflow:hidden; }
  .tl-body--truncated { cursor:pointer; color:var(--text-muted); }
  .tl-body--truncated:hover { color:var(--text); }
  .tl-risk-badge { font-size:0.7rem; padding:1px 5px; border-radius:3px; flex-shrink:0;
    background:rgba(248,81,73,0.1); color:#f85149; }
  .tl-empty  { color:var(--text-muted); text-align:center; padding:40px 0; font-size:0.9rem; }
  ```

- [ ] **Step 7: Manual smoke test**
  1. Restart server: `python wsgi.py`
  2. Open case with messages → click "Timeline" tab
  3. Verify chronological feed with date separators and platform badges
  4. Click a platform pill → non-matching rows disappear
  5. Click a message row → Conversations tab opens at the correct thread

- [ ] **Step 8: Commit**
  ```bash
  git add static/js/timeline.js static/js/cases.js static/style.css templates/index.html
  git commit -m "feat(A1): Timeline tab — compact feed, platform filter, date jump, cross-tab nav"
  ```

---

## Task 7: A4 — Media Route

**Files:**
- Create: `app/routes/media.py`
- Modify: `app/__init__.py`
- Create: `tests/test_media_extraction.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/test_media_extraction.py` (uses conftest.py fixtures):

  ```python
  """Tests for media file serving and _store_parsed media arm (A4)."""
  import uuid
  from pathlib import Path

  def test_media_route_streams_file(client, app, tmp_path):
      with app.app_context():
          from app.database import get_db
          from flask import current_app
          db = get_db()
          cid = str(uuid.uuid4())
          mid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "MediaTest"))

          cfg = current_app.config["MT_CONFIG"]
          cases_dir = Path(cfg["server"]["cases_dir"])
          media_path = cases_dir / cid / "media"
          media_path.mkdir(parents=True, exist_ok=True)
          fake_file = media_path / f"{mid}.jpg"
          fake_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

          db.execute(
              "INSERT INTO media_files (id, case_id, message_id, filename,"
              " mime_type, size_bytes, filepath) VALUES (?,?,?,?,?,?,?)",
              (mid, cid, None, "photo.jpg", "image/jpeg", 24,
               f"{cid}/media/{mid}.jpg"),
          )
          db.commit()

      resp = client.get(f"/api/cases/{cid}/media/{mid}")
      assert resp.status_code == 200
      assert "image/jpeg" in resp.content_type

  def test_media_route_404_wrong_case(client, app):
      """media_id belonging to case A must 404 when requested under case B."""
      with app.app_context():
          from app.database import get_db
          from flask import current_app
          db = get_db()
          cid_a = str(uuid.uuid4())
          cid_b = str(uuid.uuid4())
          mid   = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid_a, "A"))
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid_b, "B"))

          cfg = current_app.config["MT_CONFIG"]
          cases_dir = Path(cfg["server"]["cases_dir"])
          media_path = cases_dir / cid_a / "media"
          media_path.mkdir(parents=True, exist_ok=True)
          fake = media_path / f"{mid}.jpg"
          fake.write_bytes(b"\xff\xd8\xff")

          db.execute(
              "INSERT INTO media_files (id, case_id, message_id, filename,"
              " mime_type, size_bytes, filepath) VALUES (?,?,?,?,?,?,?)",
              (mid, cid_a, None, "photo.jpg", "image/jpeg", 3,
               f"{cid_a}/media/{mid}.jpg"),
          )
          db.commit()

      # Request mid under cid_b — must 404
      resp = client.get(f"/api/cases/{cid_b}/media/{mid}")
      assert resp.status_code == 404

  def test_media_route_404_missing_file(client, app):
      """Return 404 if DB row exists but file is missing from disk."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = str(uuid.uuid4())
          mid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "Ghost"))
          db.execute(
              "INSERT INTO media_files (id, case_id, message_id, filename,"
              " mime_type, size_bytes, filepath) VALUES (?,?,?,?,?,?,?)",
              (mid, cid, None, "ghost.jpg", "image/jpeg", 100,
               f"{cid}/media/{mid}.jpg"),  # file not on disk
          )
          db.commit()
      resp = client.get(f"/api/cases/{cid}/media/{mid}")
      assert resp.status_code == 404

  def test_store_parsed_skips_large_media(app, tmp_path):
      """_store_parsed() must not insert media_files rows > 50 MB."""
      with app.app_context():
          from app.database import get_db
          from app.routes.cases import _store_parsed
          from app.parsers.base import ParsedCase
          db = get_db()
          cid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "BigMedia"))
          db.commit()

          fake = tmp_path / "big.mp4"
          fake.write_bytes(b"x" * 100)
          parsed = ParsedCase(format="test")
          parsed.media_files = [{
              "message_id": None, "filename": "big.mp4",
              "mime_type": "video/mp4",
              "size_bytes": 60 * 1024 * 1024,  # > 50 MB limit
              "tmp_path": str(fake),
          }]
          _store_parsed(db, cid, parsed)
          rows = db.execute("SELECT * FROM media_files WHERE case_id=?", (cid,)).fetchall()
          assert len(rows) == 0, "Large file should have been skipped"
  ```

- [ ] **Step 2: Run tests to verify they fail**
  ```bash
  python -m pytest tests/test_media_extraction.py -v
  ```
  Expected: FAIL — route not registered.

- [ ] **Step 3: Create app/routes/media.py**

  ```python
  """GET /api/cases/<id>/media/<media_id> — stream extracted media files (A4)."""
  from pathlib import Path
  from flask import Blueprint, abort, current_app, send_file
  from app.database import get_db

  bp_media = Blueprint("media", __name__, url_prefix="/api")

  @bp_media.get("/cases/<case_id>/media/<media_id>")
  def get_media(case_id, media_id):
      db = get_db()
      # UUID lookup — no path traversal possible
      row = db.execute(
          "SELECT filepath, mime_type FROM media_files WHERE id=? AND case_id=?",
          (media_id, case_id),
      ).fetchone()
      if not row:
          abort(404)

      cfg = current_app.config["MT_CONFIG"]
      cases_dir = Path(cfg["server"]["cases_dir"])
      full_path = cases_dir / row["filepath"]
      if not full_path.exists():
          abort(404)

      resp = send_file(full_path, mimetype=row["mime_type"])
      resp.headers["Cache-Control"] = "max-age=86400, immutable"
      return resp
  ```

- [ ] **Step 4: Register bp_media in app/__init__.py**

  ```python
  from app.routes.media import bp_media
  app.register_blueprint(bp_media)
  ```

- [ ] **Step 5: Run tests**
  ```bash
  python -m pytest tests/test_media_extraction.py -v
  ```
  Expected: all 4 pass.

- [ ] **Step 6: Run full suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all pass.

- [ ] **Step 7: Commit**
  ```bash
  git add app/routes/media.py app/__init__.py tests/test_media_extraction.py
  git commit -m "feat(A4): GET /api/cases/<id>/media/<media_id> streaming route"
  ```

---

## Task 8: A4 — Media Thumbnails UI

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/conversations.js`
- Modify: `static/style.css`

- [ ] **Step 1: Add lightbox dialog to index.html**

  Before `</body>`:
  ```html
  <!-- Media lightbox (A4) -->
  <dialog id="media-lightbox" class="media-lightbox">
    <div class="media-lightbox-inner">
      <button class="media-lightbox-close" aria-label="Close">&times;</button>
      <div id="media-lightbox-content"></div>
      <div id="media-lightbox-meta" class="media-lightbox-meta"></div>
    </div>
  </dialog>
  ```

- [ ] **Step 2: Add Media CSS to style.css**

  ```css
  /* ── Media Thumbnails (A4) ─────────────────────────────────────────────── */
  .msg-media-wrap { margin-top:6px; }
  .msg-media-thumb { display:block; width:140px; height:90px; object-fit:cover;
    border-radius:4px; cursor:pointer; background:var(--surface2);
    border:1px solid var(--border); }
  .msg-media-video { width:140px; height:90px; background:var(--surface2);
    border:1px solid var(--border); border-radius:4px; display:flex;
    align-items:center; justify-content:center; font-size:1.4rem; cursor:pointer; }
  .msg-media-meta { font-size:0.75rem; color:var(--text-muted); margin-top:3px; }

  /* Lightbox */
  .media-lightbox { border:none; border-radius:8px; background:var(--surface);
    max-width:90vw; max-height:90vh; padding:0;
    box-shadow:0 8px 40px rgba(0,0,0,.5); }
  .media-lightbox::backdrop { background:rgba(0,0,0,.75); }
  .media-lightbox-inner { position:relative; padding:16px; }
  .media-lightbox-close { position:absolute; top:8px; right:12px; background:none;
    border:none; font-size:1.4rem; cursor:pointer; color:var(--text-muted); }
  .media-lightbox-close:hover { color:var(--text); }
  #media-lightbox-content img,
  #media-lightbox-content video { max-width:80vw; max-height:75vh; display:block;
    border-radius:4px; }
  .media-lightbox-meta { font-size:0.8rem; color:var(--text-muted); margin-top:8px; }
  ```

- [ ] **Step 3: Add media thumbnail helpers to conversations.js**

  Read `static/js/conversations.js` to find:
  - The message bubble rendering function (search for `class="msg-bubble"` or similar)
  - Where `_caseId` is stored (module-level variable)

  Add these functions at module level (outside any other function):

  ```javascript
  // ── Media thumbnail helpers (A4) ──────────────────────────────────────────

  function _fmtBytes(b) {
    if (b > 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
    if (b > 1024) return `${(b / 1024).toFixed(0)} KB`;
    return `${b} B`;
  }

  function _renderMediaThumb(msg, caseId, container) {
    if (!msg.media_id) return;
    const url    = `/api/cases/${caseId}/media/${msg.media_id}`;
    const mime   = msg.mime_type || "";
    const fname  = msg.media_filename || "attachment";
    const size   = msg.media_size ? ` · ${_fmtBytes(msg.media_size)}` : "";

    const wrap = document.createElement("div");
    wrap.className = "msg-media-wrap";

    if (mime.startsWith("image/")) {
      const img = document.createElement("img");
      img.className = "msg-media-thumb";
      img.alt = fname;
      img.dataset.src = url;        // lazy — set by IntersectionObserver
      img.dataset.mediaName = fname;
      img.dataset.mediaType = "image";
      wrap.appendChild(img);
    } else if (mime.startsWith("video/")) {
      const vid = document.createElement("div");
      vid.className = "msg-media-video";
      vid.textContent = "▶";
      vid.dataset.src = url;
      vid.dataset.mediaName = fname;
      vid.dataset.mediaType = "video";
      wrap.appendChild(vid);
    }

    const meta = document.createElement("div");
    meta.className = "msg-media-meta";
    meta.textContent = `${mime.startsWith("image/") ? "🖼" : "📹"} ${fname}${size}`;
    wrap.appendChild(meta);

    container.appendChild(wrap);
  }

  function _openLightbox(url, name, type) {
    const dlg     = document.getElementById("media-lightbox");
    const content = document.getElementById("media-lightbox-content");
    const metaEl  = document.getElementById("media-lightbox-meta");
    content.innerHTML = type === "video"
      ? `<video src="${url}" controls autoplay></video>`
      : `<img src="${url}" alt="" />`;
    metaEl.textContent = name;
    dlg.showModal();
  }

  function _initLightbox() {
    const dlg = document.getElementById("media-lightbox");
    if (!dlg) return;
    dlg.querySelector(".media-lightbox-close").addEventListener("click", () => dlg.close());
    dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
  }

  function _lazyLoadImages(container) {
    const els = container.querySelectorAll("[data-src]");
    if (!els.length) return;
    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (!e.isIntersecting) return;
        const el = e.target;
        const url  = el.dataset.src;
        const name = el.dataset.mediaName || "";
        const type = el.dataset.mediaType || "image";
        if (el.tagName === "IMG") {
          el.src = url;
          el.addEventListener("click", () => _openLightbox(url, name, "image"));
        } else {
          // video placeholder div
          el.addEventListener("click", () => _openLightbox(url, name, "video"));
        }
        el.removeAttribute("data-src");
        obs.unobserve(el);
      });
    }, { rootMargin: "200px" });
    els.forEach(el => obs.observe(el));
  }
  ```

  Call `_initLightbox()` inside `initConversations()` (once, on first call — guard with a flag):
  ```javascript
  let _lightboxInited = false;
  export async function initConversations(caseId) {
    if (!_lightboxInited) { _initLightbox(); _lightboxInited = true; }
    // ... rest of existing init ...
  }
  ```

- [ ] **Step 4: Call _renderMediaThumb in message bubble rendering**

  Find where message bubbles are built (search for `msg-bubble` or `innerHTML` inside a messages rendering function). After the body text is added to the bubble element, call:
  ```javascript
  _renderMediaThumb(msg, _caseId, bubbleElement);
  ```
  Where `bubbleElement` is the DOM node for the bubble (the one that gets appended).

  After all bubbles are appended to the messages container, call:
  ```javascript
  _lazyLoadImages(messagesContainer);
  ```

- [ ] **Step 5: Bump conversations.js version in index.html**

  Change `conversations.js?v=20260308` → `conversations.js?v=20260321e`.

- [ ] **Step 6: Manual smoke test**
  1. Use the Android Pixel 3 case (or import a dump with images)
  2. Navigate to Conversations → WhatsApp thread
  3. Verify thumbnail renders (140×90px) below message body
  4. Click thumbnail → lightbox opens with full image
  5. Click backdrop → lightbox closes
  6. Press Escape → lightbox closes

- [ ] **Step 7: Run full suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all 138 tests pass (125 original + 13 new).

- [ ] **Step 8: Commit**
  ```bash
  git add static/js/conversations.js static/style.css templates/index.html
  git commit -m "feat(A4): media thumbnails with lazy load and lightbox in conversation bubbles"
  ```

---

## Task 9: Final Verification & Push

- [ ] **Step 1: Full test run**
  ```bash
  python -m pytest tests/ -v --tb=short 2>&1 | tail -20
  ```
  Expected: all tests pass.

- [ ] **Step 2: Manual success criteria checklist**
  - [ ] Timeline tab shows 86 SMS + 24 WhatsApp + 30 Telegram + 30 calls for Pixel 3 case
  - [ ] Platform filter pills work (WhatsApp pill → only green rows)
  - [ ] Date jump input scrolls timeline to selected date
  - [ ] Clicking a timeline row opens Conversations tab at the correct thread
  - [ ] Media thumbnails visible for image messages (if dump contains images)
  - [ ] Lightbox opens on click, closes on Escape and backdrop click
  - [ ] iOS case with 0 contacts shows `(recovered)` label in contacts section
  - [ ] iOS case with >0 contacts shows no `(recovered)` labels

- [ ] **Step 3: Update spec status**

  Edit `docs/superpowers/specs/2026-03-21-feature-pack-2-design.md`:
  Change `**Status:** Draft — Pending Review` → `**Status:** Implemented ✓`

- [ ] **Step 4: Update docs/completed-work.md**

  Append a section:
  ```markdown
  ## Feature Pack 2 (completed 2026-03-21)
  - **C3** Encrypted contact recovery — iOS/Android parsers recover contacts from WhatsApp/Telegram/SMS metadata when AddressBook is empty; tagged `source='recovered'`
  - **A1** Timeline tab — chronological cross-platform feed with platform filter pills, date jump, cursor pagination, cross-tab navigation
  - **A4** Media thumbnails — image/video thumbnails inline in conversation bubbles with lazy loading, lightbox, and streaming media route
  ```

- [ ] **Step 5: Commit and push**
  ```bash
  git add docs/
  git commit -m "docs: mark Feature Pack 2 implemented, update completed-work.md"
  git push
  ```
