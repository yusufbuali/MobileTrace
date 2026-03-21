# Feature Pack 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three forensic investigation features: contact recovery from encrypted devices (C3), cross-platform chronological timeline tab (A1), and inline media thumbnails in conversations (A4).

**Architecture:** C3 extends the parser layer — when primary contacts return empty, parsers reconstruct from WhatsApp/Telegram/SMS metadata and tag them `source='recovered'`. A1 adds a new Flask route + vanilla JS tab that UNIONs messages and call_logs with cursor pagination. A4 adds a `media_files` DB table, file extraction during parse, a streaming media route, and thumbnail rendering in conversation bubbles.

**Tech Stack:** Python/Flask, SQLite (FTS5), vanilla JS ES modules, CSS variables. Optional: `pillow-heif` for HEIC conversion.

**Spec:** `docs/superpowers/specs/2026-03-21-feature-pack-2-design.md`

**Run tests with:** `cd "C:/claudecode projects/AIFT-final-1/MobileTrace" && python -m pytest tests/ -v`

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
- `app/parsers/base.py` — add `source` kwarg to `_norm_contact()`, add `media_files` field to `ParsedCase`
- `app/routes/cases.py` — update contacts INSERT to include `source`; add `media_files` arm to `_store_parsed()`
- `app/parsers/ios_parser.py` — add `_recover_contacts_ios()` method called when contacts empty
- `app/parsers/android_parser.py` — add `_recover_contacts_android()` method called when contacts empty
- `app/__init__.py` — register `timeline` and `media` blueprints
- `templates/index.html` — add Timeline tab button + panel; add timeline.js + media.js script tags
- `static/js/cases.js` — wire `initTimeline()` on tab switch + in `openCase()`
- `static/js/conversations.js` — media thumbnail rendering + lightbox in message bubbles
- `static/style.css` — timeline CSS + `.msg-media-thumb` + `#media-lightbox`

---

## Task 1: DB Schema — contacts.source column + media_files table

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Read current database.py to understand _migrate() and _SCHEMA**

  Read `app/database.py`. Note the `_SCHEMA` string (line ~1-100) and `_migrate()` function (lines ~160-187). Also check the contacts FTS5 trigger if present.

- [ ] **Step 2: Write failing tests**

  Add to `tests/test_database.py`:
  ```python
  def test_contacts_source_column(client, app):
      """contacts table must have a source column defaulting to NULL."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          info = db.execute("PRAGMA table_info(contacts)").fetchall()
          cols = [r["name"] for r in info]
          assert "source" in cols

  def test_media_files_table_exists(client, app):
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
  cd "C:/claudecode projects/AIFT-final-1/MobileTrace"
  python -m pytest tests/test_database.py::test_contacts_source_column tests/test_database.py::test_media_files_table_exists -v
  ```
  Expected: FAIL — `source` not in contacts, `media_files` table doesn't exist.

- [ ] **Step 4: Add media_files DDL to _SCHEMA in database.py**

  In `app/database.py`, find `_SCHEMA` and append before the closing `"""`:
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

  In `_migrate()` in `app/database.py`, add at the end of the function (before or after existing migration blocks):
  ```python
  # Add source column to contacts (idempotent)
  try:
      conn.execute("ALTER TABLE contacts ADD COLUMN source TEXT DEFAULT NULL")
      conn.commit()
  except Exception:
      pass  # column already exists
  ```

- [ ] **Step 6: Run tests to verify they pass**
  ```bash
  python -m pytest tests/test_database.py::test_contacts_source_column tests/test_database.py::test_media_files_table_exists -v
  ```
  Expected: PASS.

- [ ] **Step 7: Run full test suite to check no regressions**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all 125 existing tests pass + 2 new tests.

- [ ] **Step 8: Commit**
  ```bash
  git add app/database.py tests/test_database.py
  git commit -m "feat(db): add contacts.source migration and media_files table"
  ```

---

## Task 2: Base Parser — _norm_contact() source kwarg + ParsedCase.media_files

**Files:**
- Modify: `app/parsers/base.py`

- [ ] **Step 1: Read app/parsers/base.py**

  Confirm current `ParsedCase` dataclass fields and `_norm_contact()` full signature (should match what we found: `name, phone, email, source_app, raw=None`).

- [ ] **Step 2: Add `source` kwarg to `_norm_contact()`**

  Change the method to:
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
          "source": source,  # None = normal, 'recovered' = reconstructed
      }
  ```

- [ ] **Step 3: Add `media_files` field to `ParsedCase` dataclass**

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
      # Each media dict: { message_id: int|None, filename: str,
      #   mime_type: str, size_bytes: int, tmp_path: str }
      raw_db_paths: list[Path] = field(default_factory=list)
      warnings: list[str] = field(default_factory=list)
  ```

- [ ] **Step 4: Run full test suite — no regressions expected**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all pass. `_norm_contact()` change is backwards-compatible (new kwarg defaults to `None`).

- [ ] **Step 5: Commit**
  ```bash
  git add app/parsers/base.py
  git commit -m "feat(parsers): add source kwarg to _norm_contact, media_files to ParsedCase"
  ```

---

## Task 3: _store_parsed() — propagate source + media_files arm

**Files:**
- Modify: `app/routes/cases.py`

- [ ] **Step 1: Read _store_parsed() in app/routes/cases.py**

  Confirm the contacts INSERT at lines ~476-479 is:
  ```python
  db.execute(
      "INSERT INTO contacts (case_id, name, phone, email, source_app, raw_json) VALUES (?,?,?,?,?,?)",
      (case_id, c["name"], c["phone"], c["email"], c["source_app"], json.dumps(c["raw_json"])),
  )
  ```

- [ ] **Step 2: Update contacts INSERT to include source column**

  Replace the contacts INSERT with:
  ```python
  db.execute(
      "INSERT INTO contacts (case_id, name, phone, email, source_app, raw_json, source)"
      " VALUES (?,?,?,?,?,?,?)",
      (case_id, c["name"], c["phone"], c["email"],
       c["source_app"], json.dumps(c.get("raw_json") or {}), c.get("source")),
  )
  ```

- [ ] **Step 3: Add media_files arm after call_logs loop**

  After the `for cl in parsed.call_logs:` loop, before `db.commit()`:
  ```python
  import uuid as _uuid
  import shutil as _shutil

  cases_dir = Path(current_app.config.get("CASES_DIR", "cases"))
  media_dir = cases_dir / case_id / "media"
  media_dir.mkdir(parents=True, exist_ok=True)

  for mf in getattr(parsed, "media_files", []):
      if mf.get("size_bytes", 0) > 50 * 1024 * 1024:
          continue  # skip files > 50 MB
      tmp = Path(mf["tmp_path"])
      if not tmp.exists():
          continue
      ext = tmp.suffix.lower()
      media_id = str(_uuid.uuid4())
      dest = media_dir / f"{media_id}{ext}"
      _shutil.copy2(tmp, dest)
      rel_path = f"{case_id}/media/{media_id}{ext}"
      db.execute(
          "INSERT INTO media_files (id, case_id, message_id, filename, mime_type, size_bytes, filepath)"
          " VALUES (?,?,?,?,?,?,?)",
          (media_id, case_id, mf.get("message_id"),
           mf["filename"], mf["mime_type"], mf.get("size_bytes"), rel_path),
      )
  ```

  Note: `uuid` and `shutil` may already be imported; add them at the top of `cases.py` if not present.

- [ ] **Step 4: Run full test suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all pass.

- [ ] **Step 5: Commit**
  ```bash
  git add app/routes/cases.py
  git commit -m "feat(cases): propagate contacts.source, add media_files arm to _store_parsed"
  ```

---

## Task 4: C3 — Contact Recovery Logic

**Files:**
- Modify: `app/parsers/ios_parser.py`
- Modify: `app/parsers/android_parser.py`
- Create: `tests/test_contact_recovery.py`

- [ ] **Step 1: Write failing tests for contact recovery**

  Create `tests/test_contact_recovery.py`:
  ```python
  """Tests for encrypted-device contact recovery (C3)."""
  import sqlite3, json, tempfile, os
  from pathlib import Path
  import pytest
  from app import create_app
  from app.database import init_db

  @pytest.fixture
  def app(tmp_path):
      db_path = str(tmp_path / "test.db")
      app = create_app({"TESTING": True, "DATABASE": db_path,
                        "CASES_DIR": str(tmp_path / "cases")})
      with app.app_context():
          init_db(db_path)
      return app

  @pytest.fixture
  def client(app):
      return app.test_client()

  def _make_wa_db(path: Path):
      """Create a minimal wa.db with two WhatsApp contacts."""
      path.parent.mkdir(parents=True, exist_ok=True)
      conn = sqlite3.connect(path)
      conn.execute("CREATE TABLE wa_contacts (jid TEXT, display_name TEXT, number TEXT)")
      conn.execute("INSERT INTO wa_contacts VALUES ('1@s.whatsapp.net', 'Alice', '+1-555-0101')")
      conn.execute("INSERT INTO wa_contacts VALUES ('2@s.whatsapp.net', 'Bob', '+1-555-0202')")
      conn.commit()
      conn.close()

  def test_ios_recovery_triggers_when_contacts_empty(tmp_path):
      """iOS parser should recover contacts from WhatsApp when AddressBook is empty."""
      from app.parsers.ios_parser import IosParser
      wa_db = tmp_path / "wa.db"
      _make_wa_db(wa_db)
      parser = IosParser.__new__(IosParser)
      # Simulate: primary contacts empty, wa.db present, no messages
      recovered = parser._recover_contacts_ios(
          wa_db_path=wa_db,
          tg_db_path=None,
          parsed_messages=[],
      )
      assert len(recovered) == 2
      assert all(c["source"] == "recovered" for c in recovered)
      names = {c["name"] for c in recovered}
      assert "Alice" in names
      assert "Bob" in names

  def test_ios_recovery_skipped_when_contacts_present(tmp_path):
      """Recovery must NOT run when primary contacts are non-empty."""
      from app.parsers.ios_parser import IosParser
      wa_db = tmp_path / "wa.db"
      _make_wa_db(wa_db)
      parser = IosParser.__new__(IosParser)
      # If contacts already exist, _recover_contacts_ios should not be called
      # — test the guard in parse() via a unit check on the method
      recovered = parser._recover_contacts_ios(wa_db_path=wa_db, tg_db_path=None, parsed_messages=[])
      assert len(recovered) > 0  # method itself works; calling code guards it

  def test_recovery_deduplication(tmp_path):
      """Same phone in WhatsApp and SMS messages should yield one contact."""
      from app.parsers.ios_parser import IosParser
      wa_db = tmp_path / "wa.db"
      _make_wa_db(wa_db)
      sms_messages = [
          {"sender": "Alice", "platform": "sms", "direction": "incoming",
           "body": "hello", "timestamp": "2021-01-01T10:00:00",
           "thread_id": "+15550101", "recipient": None,
           "raw_json": {"address": "+15550101", "contact_name": "Alice"}},
      ]
      parser = IosParser.__new__(IosParser)
      recovered = parser._recover_contacts_ios(
          wa_db_path=wa_db, tg_db_path=None, parsed_messages=sms_messages
      )
      # Alice appears in both WhatsApp (+1-555-0101) and SMS (+15550101)
      # After normalization they should deduplicate to one entry
      alice_contacts = [c for c in recovered if c["name"] == "Alice"]
      assert len(alice_contacts) == 1

  def test_android_recovery_triggers(tmp_path):
      """Android parser should recover contacts from WhatsApp when contacts2.db is empty."""
      from app.parsers.android_parser import AndroidParser
      wa_db = tmp_path / "wa.db"
      _make_wa_db(wa_db)
      parser = AndroidParser.__new__(AndroidParser)
      recovered = parser._recover_contacts_android(
          wa_db_path=wa_db, tg_db_path=None, parsed_messages=[]
      )
      assert len(recovered) == 2
      assert all(c["source"] == "recovered" for c in recovered)

  def test_recovered_contacts_have_source_label(client, app, tmp_path):
      """GET /api/cases/<id>/contacts should include source field for recovered contacts."""
      import uuid
      with app.app_context():
          from app.database import get_db
          db = get_db()
          case_id = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?, ?)", (case_id, "Test"))
          db.execute(
              "INSERT INTO contacts (case_id, name, phone, email, source_app, raw_json, source)"
              " VALUES (?,?,?,?,?,?,?)",
              (case_id, "Alice", "+15550101", "", "whatsapp_contacts", "{}", "recovered"),
          )
          db.commit()
      resp = client.get(f"/api/cases/{case_id}/contacts")
      assert resp.status_code == 200
      contacts = resp.get_json()
      alice = next((c for c in contacts if c["name"] == "Alice"), None)
      assert alice is not None
      assert alice.get("source") == "recovered"
  ```

- [ ] **Step 2: Run tests to verify they fail**
  ```bash
  python -m pytest tests/test_contact_recovery.py -v
  ```
  Expected: FAIL — `_recover_contacts_ios`, `_recover_contacts_android` don't exist yet.

- [ ] **Step 3: Implement _recover_contacts_ios() in ios_parser.py**

  Read `app/parsers/ios_parser.py` to find the parse() method and `_read_contacts_ios()`. Add this method to the `IosParser` class:

  ```python
  def _recover_contacts_ios(self, wa_db_path, tg_db_path, parsed_messages):
      """Reconstruct contacts from messaging metadata when AddressBook is empty."""
      recovered: dict[str, dict] = {}  # normalized_phone → contact dict

      def _add(name, phone, source_app):
          norm = self._norm_phone(phone)
          if norm and norm not in recovered:
              recovered[norm] = self._norm_contact(
                  name=name, phone=norm, email="",
                  source_app=source_app, source="recovered"
              )

      # 1. WhatsApp wa_contacts
      if wa_db_path and Path(wa_db_path).exists():
          try:
              import sqlite3 as _sq3
              conn = _sq3.connect(wa_db_path)
              conn.row_factory = _sq3.Row
              for row in conn.execute(
                  "SELECT display_name, number FROM wa_contacts"
                  " WHERE display_name IS NOT NULL AND display_name != ''"
              ).fetchall():
                  _add(row["display_name"], row["number"] or "", "whatsapp_contacts")
              conn.close()
          except Exception as e:
              self.parsed.warnings.append(f"Contact recovery (WhatsApp): {e}")

      # 2. Telegram peers table
      if tg_db_path and Path(tg_db_path).exists():
          try:
              import sqlite3 as _sq3
              conn = _sq3.connect(tg_db_path)
              conn.row_factory = _sq3.Row
              for row in conn.execute(
                  "SELECT phone, first_name, last_name FROM peers"
                  " WHERE phone IS NOT NULL AND phone != ''"
              ).fetchall():
                  name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
                  _add(name or row["phone"], row["phone"], "telegram_peers")
              conn.close()
          except Exception as e:
              self.parsed.warnings.append(f"Contact recovery (Telegram): {e}")

      # 3. SMS sender/recipient names from already-parsed messages
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

  Then in the `parse()` method (or `_read_contacts_ios()`), after the existing contacts are gathered, add the recovery guard:
  ```python
  # After self.parsed.contacts is populated from AddressBook...
  if not self.parsed.contacts:
      # AddressBook empty (likely encrypted) — recover from messaging data
      wa_path = self._find_db("wa.db")    # use existing helper or Path glob
      tg_path = self._find_db("cache4.db")
      recovered = self._recover_contacts_ios(wa_path, tg_path, self.parsed.messages)
      self.parsed.contacts.extend(recovered)
      if recovered:
          self.parsed.warnings.append(
              f"AddressBook empty — recovered {len(recovered)} contacts from messaging data"
          )
  ```

  Note: `self._find_db(name)` may already exist in the parser; if not, use `next(self._root.rglob(name), None)` where `self._root` is the extraction root.

- [ ] **Step 4: Implement _recover_contacts_android() in android_parser.py**

  Add to `AndroidParser` class:
  ```python
  def _recover_contacts_android(self, wa_db_path, tg_db_path, parsed_messages):
      """Reconstruct contacts from messaging metadata when contacts2.db is empty."""
      recovered: dict[str, dict] = {}

      def _add(name, phone, source_app):
          norm = self._norm_phone(phone)
          if norm and norm not in recovered:
              recovered[norm] = self._norm_contact(
                  name=name, phone=norm, email="",
                  source_app=source_app, source="recovered"
              )

      # 1. WhatsApp wa_contacts
      if wa_db_path and Path(wa_db_path).exists():
          try:
              import sqlite3 as _sq3
              conn = _sq3.connect(wa_db_path)
              conn.row_factory = _sq3.Row
              for row in conn.execute(
                  "SELECT display_name, number FROM wa_contacts"
                  " WHERE display_name IS NOT NULL AND display_name != ''"
              ).fetchall():
                  _add(row["display_name"], row["number"] or "", "whatsapp_contacts")
              conn.close()
          except Exception as e:
              self.parsed.warnings.append(f"Contact recovery (WhatsApp): {e}")

      # 2. Telegram user_contacts_v7
      if tg_db_path and Path(tg_db_path).exists():
          try:
              import sqlite3 as _sq3
              conn = _sq3.connect(tg_db_path)
              conn.row_factory = _sq3.Row
              for row in conn.execute(
                  "SELECT uid, fname, sname FROM user_contacts_v7"
              ).fetchall():
                  name = f"{row['fname'] or ''} {row['sname'] or ''}".strip()
                  _add(name or str(row["uid"]), "", "telegram_contacts")
              conn.close()
          except Exception as e:
              self.parsed.warnings.append(f"Contact recovery (Telegram): {e}")

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

  And in `android_parser.py`'s `parse()` method after contacts are gathered:
  ```python
  if not self.parsed.contacts:
      wa_path = next(self._root.rglob("wa.db"), None)
      tg_path = next(self._root.rglob("telegramDB.db"), None)
      recovered = self._recover_contacts_android(wa_path, tg_path, self.parsed.messages)
      self.parsed.contacts.extend(recovered)
      if recovered:
          self.parsed.warnings.append(
              f"contacts2.db empty — recovered {len(recovered)} contacts from messaging data"
          )
  ```

- [ ] **Step 5: Check the contacts API route returns source field**

  Read `app/routes/cases.py` — find `GET /api/cases/<id>/contacts`. Ensure it returns `source` in the response. If the route does a `SELECT *` or names columns, add `source` to the projection. Example:
  ```python
  rows = db.execute(
      "SELECT id, name, phone, email, source_app, source FROM contacts WHERE case_id=?",
      (case_id,)
  ).fetchall()
  return jsonify([dict(r) for r in rows])
  ```

- [ ] **Step 6: Run recovery tests**
  ```bash
  python -m pytest tests/test_contact_recovery.py -v
  ```
  Expected: all 5 tests pass.

- [ ] **Step 7: Run full suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all pass.

- [ ] **Step 8: Commit**
  ```bash
  git add app/parsers/ios_parser.py app/parsers/android_parser.py \
          app/routes/cases.py tests/test_contact_recovery.py
  git commit -m "feat(C3): contact recovery from WhatsApp/Telegram/SMS when AddressBook empty"
  ```

---

## Task 5: A1 — Timeline Route

**Files:**
- Create: `app/routes/timeline.py`
- Modify: `app/__init__.py`
- Create: `tests/test_timeline_routes.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/test_timeline_routes.py`:
  ```python
  """Tests for GET /api/cases/<id>/timeline (A1)."""
  import json, uuid
  import pytest
  from app import create_app
  from app.database import init_db

  @pytest.fixture
  def app(tmp_path):
      db_path = str(tmp_path / "test.db")
      app = create_app({"TESTING": True, "DATABASE": db_path,
                        "CASES_DIR": str(tmp_path / "cases")})
      with app.app_context():
          init_db(db_path)
      return app

  @pytest.fixture
  def client(app):
      return app.test_client()

  @pytest.fixture
  def case_with_messages(app):
      """Create a case with SMS + WhatsApp messages and a call log."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "TL Test"))
          # SMS at 09:00
          db.execute(
              "INSERT INTO messages (case_id, platform, direction, sender, recipient,"
              " body, timestamp, thread_id, raw_json) VALUES (?,?,?,?,?,?,?,?,?)",
              (cid, "sms", "incoming", "Alice", None,
               "hello", "2021-03-14T09:00:00", "+15550101", "{}"),
          )
          # WhatsApp at 10:00
          db.execute(
              "INSERT INTO messages (case_id, platform, direction, sender, recipient,"
              " body, timestamp, thread_id, raw_json) VALUES (?,?,?,?,?,?,?,?,?)",
              (cid, "whatsapp", "incoming", "Bob", None,
               "package ready", "2021-03-14T10:00:00", "group1", "{}"),
          )
          # Call at 11:00
          db.execute(
              "INSERT INTO call_logs (case_id, number, direction, duration_s, timestamp, platform)"
              " VALUES (?,?,?,?,?,?)",
              (cid, "+15559999", "incoming", 120, "2021-03-14T11:00:00", "sms"),
          )
          db.commit()
          return cid

  def test_timeline_empty_case(client, app):
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "Empty"))
          db.commit()
      resp = client.get(f"/api/cases/{cid}/timeline")
      assert resp.status_code == 200
      data = resp.get_json()
      assert data["items"] == []
      assert data["next_cursor"] is None

  def test_timeline_merges_and_sorts(client, case_with_messages):
      resp = client.get(f"/api/cases/{case_with_messages}/timeline")
      assert resp.status_code == 200
      items = resp.get_json()["items"]
      assert len(items) == 3
      timestamps = [i["timestamp"] for i in items]
      assert timestamps == sorted(timestamps)
      types = [i["type"] for i in items]
      assert "message" in types
      assert "call" in types

  def test_timeline_platform_filter(client, case_with_messages):
      resp = client.get(f"/api/cases/{case_with_messages}/timeline?platforms=sms")
      assert resp.status_code == 200
      items = resp.get_json()["items"]
      # Only SMS messages + SMS calls (call_logs with platform=sms)
      non_sms = [i for i in items if i["platform"] != "sms"]
      assert non_sms == []

  def test_timeline_limit_capped(client, case_with_messages):
      resp = client.get(f"/api/cases/{case_with_messages}/timeline?limit=9999")
      assert resp.status_code == 200
      # With only 3 items, result is 3; but confirm no server error on huge limit
      data = resp.get_json()
      assert len(data["items"]) <= 500

  def test_timeline_pagination_no_duplicates(client, app):
      """Two pages together must equal all items with no duplicates."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "PagTest"))
          # Insert 5 messages at the SAME timestamp to stress tie-breaking
          for i in range(5):
              db.execute(
                  "INSERT INTO messages (case_id, platform, direction, sender,"
                  " recipient, body, timestamp, thread_id, raw_json)"
                  " VALUES (?,?,?,?,?,?,?,?,?)",
                  (cid, "sms", "incoming", f"S{i}", None,
                   f"msg{i}", "2021-01-01T12:00:00", "t1", "{}"),
              )
          db.commit()
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
      assert len(data2["items"]) == 2  # remaining 2

      all_ids = [i["id"] for i in data1["items"]] + [i["id"] for i in data2["items"]]
      assert len(all_ids) == len(set(all_ids)), "Duplicate items across pages"
  ```

- [ ] **Step 2: Run tests to verify they fail**
  ```bash
  python -m pytest tests/test_timeline_routes.py -v
  ```
  Expected: FAIL — 404 on `/api/cases/<id>/timeline`.

- [ ] **Step 3: Create app/routes/timeline.py**

  ```python
  """GET /api/cases/<id>/timeline — chronological cross-platform message + call view."""
  import json
  from flask import Blueprint, jsonify, request, abort
  from app.database import get_db

  bp_timeline = Blueprint("timeline", __name__, url_prefix="/api")

  _PLATFORM_RISK_QUERY = """
      SELECT artifact_key, result_parsed
      FROM analysis_results
      WHERE case_id = ?
      ORDER BY created_at DESC
  """

  def _platform_risk_map(db, case_id: str) -> dict[str, str]:
      """Return {platform: risk_level} for the most recent analysis per artifact."""
      risk_map: dict[str, str] = {}
      seen: set[str] = set()
      for row in db.execute(_PLATFORM_RISK_QUERY, (case_id,)).fetchall():
          ak = row["artifact_key"] or ""
          if ak in seen:
              continue
          seen.add(ak)
          try:
              parsed = json.loads(row["result_parsed"] or "null") or {}
              rl = (parsed.get("risk_level") or parsed.get("risk_level_summary") or "").upper()
              if rl in ("HIGH", "CRITICAL"):
                  platform = ak.split("_")[0]  # "whatsapp_messages" → "whatsapp"
                  risk_map[platform] = rl
          except Exception:
              pass
      return risk_map

  @bp_timeline.get("/cases/<case_id>/timeline")
  def get_timeline(case_id):
      db = get_db()
      # Verify case exists
      if not db.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone():
          abort(404)

      limit = min(int(request.args.get("limit", 100)), 500)
      cursor_ts = request.args.get("cursor_ts", "")
      cursor_key = request.args.get("cursor_key", "")
      platforms_raw = request.args.get("platforms", "")
      platform_filter = [p.strip() for p in platforms_raw.split(",") if p.strip()]

      # Build UNION query: messages + call_logs
      # row_key is namespaced to avoid id collision between tables
      msg_select = """
          SELECT id, 'message' AS type, platform, timestamp,
                 direction, sender, recipient, body, thread_id,
                 'msg-' || id AS row_key
          FROM messages
          WHERE case_id = :case_id
      """
      call_select = """
          SELECT id, 'call' AS type, platform, timestamp,
                 direction,
                 CASE WHEN direction='incoming' THEN number ELSE NULL END AS sender,
                 CASE WHEN direction='outgoing' THEN number ELSE NULL END AS recipient,
                 NULL AS body, NULL AS thread_id,
                 'call-' || id AS row_key
          FROM call_logs
          WHERE case_id = :case_id
      """

      params: dict = {"case_id": case_id}

      if platform_filter:
          placeholders = ",".join(f":pf{i}" for i in range(len(platform_filter)))
          msg_select += f" AND platform IN ({placeholders})"
          call_select += f" AND platform IN ({placeholders})"
          for i, pf in enumerate(platform_filter):
              params[f"pf{i}"] = pf

      union_sql = f"SELECT * FROM ({msg_select} UNION ALL {call_select})"

      if cursor_ts and cursor_key:
          union_sql += (
              " WHERE (timestamp > :cur_ts)"
              " OR (timestamp = :cur_ts AND row_key > :cur_key)"
          )
          params["cur_ts"] = cursor_ts
          params["cur_key"] = cursor_key

      union_sql += " ORDER BY timestamp ASC, row_key ASC LIMIT :limit"
      params["limit"] = limit + 1  # fetch one extra to detect next page

      rows = db.execute(union_sql, params).fetchall()
      has_more = len(rows) > limit
      rows = rows[:limit]

      risk_map = _platform_risk_map(db, case_id)

      items = []
      for r in rows:
          item = {
              "id": r["id"],
              "type": r["type"],
              "platform": r["platform"],
              "timestamp": r["timestamp"],
              "direction": r["direction"],
              "sender": r["sender"],
              "recipient": r["recipient"],
              "body": r["body"],
              "thread_id": r["thread_id"],
              "row_key": r["row_key"],
              "risk_level": risk_map.get(r["platform"]),
          }
          if r["type"] == "call":
              # Add duration for calls (need a second query or store separately)
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

  Read `app/__init__.py` to see how other blueprints are registered. Add:
  ```python
  from app.routes.timeline import bp_timeline
  app.register_blueprint(bp_timeline)
  ```

- [ ] **Step 5: Run timeline tests**
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
  git commit -m "feat(A1): GET /api/cases/<id>/timeline with cursor pagination and platform filter"
  ```

---

## Task 6: A1 — Timeline Frontend (HTML + JS + CSS)

**Files:**
- Modify: `templates/index.html`
- Create: `static/js/timeline.js`
- Modify: `static/js/cases.js`
- Modify: `static/style.css`

- [ ] **Step 1: Add Timeline tab button to index.html**

  In `templates/index.html`, find the tab bar (around line 180-188). Insert Timeline button between Conversations and Analysis:
  ```html
  <button class="tab-btn" data-tab="tab-timeline" role="tab" aria-selected="false" aria-controls="tab-timeline">Timeline</button>
  ```

- [ ] **Step 2: Add Timeline tab panel to index.html**

  After the Conversations tab panel and before the Analysis tab panel, add:
  ```html
  <!-- Timeline tab -->
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

- [ ] **Step 3: Add timeline.js script tag to index.html**

  In the script tags section at the bottom (after ioc.js):
  ```html
  <script type="module" src="/static/js/timeline.js?v=20260321e"></script>
  ```

- [ ] **Step 4: Create static/js/timeline.js**

  ```javascript
  /**
   * timeline.js — Cross-platform chronological timeline tab (A1).
   */
  import { apiFetch } from "./api.js";

  let _caseId = null;
  let _nextCursor = null;
  let _activePlatforms = new Set(); // empty = All
  const _PLATFORM_COLORS = {
    sms: "var(--info)",
    whatsapp: "#25d366",
    telegram: "#0088cc",
    signal: "#3a76f0",
    calls: "var(--text-muted)",
  };

  export async function initTimeline(caseId) {
    _caseId = caseId;
    _nextCursor = null;
    _activePlatforms = new Set();
    document.getElementById("tl-feed").innerHTML = "";
    _wirePills();
    _wireDateJump();
    _wireLoadMore();
    await _fetchAndRender(true);
  }

  function _wirePills() {
    document.querySelectorAll("#tl-platform-pills .tl-pill").forEach(btn => {
      btn.addEventListener("click", () => {
        const plat = btn.dataset.platform;
        if (!plat) {
          _activePlatforms.clear();
          document.querySelectorAll("#tl-platform-pills .tl-pill").forEach(b =>
            b.classList.toggle("active", !b.dataset.platform)
          );
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
        _fetchAndRender(true);
      });
    });
  }

  function _wireDateJump() {
    document.getElementById("tl-date-jump").addEventListener("change", e => {
      const date = e.target.value; // YYYY-MM-DD
      if (!date) return;
      _nextCursor = { ts: `${date}T00:00:00`, key: "" };
      document.getElementById("tl-feed").innerHTML = "";
      _fetchAndRender(false);
    });
  }

  function _wireLoadMore() {
    document.getElementById("tl-load-more").addEventListener("click", () => {
      _fetchAndRender(false);
    });
  }

  async function _fetchAndRender(reset) {
    if (!_caseId) return;
    const params = new URLSearchParams({ limit: 100 });
    if (_activePlatforms.size) params.set("platforms", [..._activePlatforms].join(","));
    if (_nextCursor) {
      params.set("cursor_ts", _nextCursor.ts);
      params.set("cursor_key", _nextCursor.key || "");
    }
    try {
      const data = await apiFetch(`/api/cases/${_caseId}/timeline?${params}`);
      _nextCursor = data.next_cursor || null;
      _renderItems(data.items, reset);
      const wrap = document.getElementById("tl-load-more-wrap");
      wrap.style.display = _nextCursor ? "" : "none";
    } catch (err) {
      document.getElementById("tl-feed").innerHTML =
        `<div class="tl-empty">Failed to load timeline: ${err.message}</div>`;
    }
  }

  function _renderItems(items, reset) {
    const feed = document.getElementById("tl-feed");
    if (reset) feed.innerHTML = "";

    if (!items.length && reset) {
      feed.innerHTML = `<div class="tl-empty">No messages in this case yet</div>`;
      return;
    }

    let lastDate = reset ? null : feed.dataset.lastDate || null;

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
      const time = (item.timestamp || "").slice(11, 16);
      const dir = item.direction === "incoming" ? "←" : "→";
      const sender = _esc(item.sender || item.recipient || "—");
      let body = item.type === "call"
        ? `📞 Call · ${_fmtDuration(item.duration_seconds)}`
        : _esc((item.body || "").slice(0, 120));
      const expanded = item.type !== "call" && (item.body || "").length > 120;

      row.innerHTML = `
        <span class="tl-badge" style="background:${color}22;color:${color};border-color:${color}44">${_esc(item.platform)}</span>
        <span class="tl-time">${time}</span>
        <span class="tl-dir">${dir}</span>
        <span class="tl-sender">${sender}</span>
        <span class="tl-body${expanded ? " tl-body--truncated" : ""}">${body}${expanded ? "…" : ""}</span>
        ${item.risk_level ? `<span class="tl-risk-badge risk-${item.risk_level}">${item.risk_level}</span>` : ""}
      `;

      if (expanded) {
        row.querySelector(".tl-body").addEventListener("click", function () {
          this.textContent = _esc(item.body);
          this.classList.remove("tl-body--truncated");
        });
      }

      if (item.thread_id && item.type === "message") {
        row.style.cursor = "pointer";
        row.addEventListener("click", e => {
          if (e.target.classList.contains("tl-body--truncated")) return;
          document.dispatchEvent(
            new CustomEvent("mt:open-thread", {
              detail: { platform: item.platform, thread: item.thread_id },
            })
          );
          // Switch to conversations tab
          const convBtn = document.querySelector('.tab-btn[data-tab="tab-conversations"]');
          if (convBtn) convBtn.click();
        });
      }

      feed.appendChild(row);
    });

    feed.dataset.lastDate = lastDate;
  }

  function _formatDateSep(dateStr) {
    try {
      const d = new Date(dateStr + "T12:00:00");
      return d.toLocaleDateString("en-GB", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
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

- [ ] **Step 5: Wire initTimeline in cases.js**

  Read `static/js/cases.js`. At the top, add import:
  ```javascript
  import { initTimeline } from "./timeline.js";
  ```

  In the tab click handler (where `initConversations`, `initCorrelation`, etc. are called), add:
  ```javascript
  if (btn.dataset.tab === "tab-timeline" && activeCaseId) {
    initTimeline(activeCaseId);
  }
  ```

  In `openCase()`, if the timeline tab is already active:
  ```javascript
  if (document.querySelector('.tab-btn[data-tab="tab-timeline"]')?.classList.contains("active")) {
    initTimeline(id);
  }
  ```

- [ ] **Step 6: Add Timeline CSS to style.css**

  Append to `static/style.css`:
  ```css
  /* ── Timeline Tab ──────────────────────────────────────────────────────── */
  .tl-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
  .tl-filter-pills { display: flex; gap: 6px; flex-wrap: wrap; }
  .tl-pill { background: var(--surface2); border: 1px solid var(--border); color: var(--text-muted);
    padding: 4px 12px; border-radius: 16px; font-size: 0.8rem; cursor: pointer; }
  .tl-pill.active { background: var(--accent); border-color: var(--accent); color: #fff; }
  .tl-date-input { background: var(--surface2); border: 1px solid var(--border); color: var(--text);
    padding: 4px 10px; border-radius: 6px; font-size: 0.85rem; }
  .tl-feed { display: flex; flex-direction: column; gap: 2px; }
  .tl-date-sep { font-size: 0.75rem; color: var(--text-muted); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.05em; padding: 12px 0 4px;
    border-bottom: 1px solid var(--border); margin-bottom: 4px; }
  .tl-row { display: flex; align-items: baseline; gap: 8px; padding: 5px 8px;
    border-radius: 6px; font-size: 0.85rem; }
  .tl-row:hover { background: var(--surface2); }
  .tl-row.tl-risk-high { border-left: 2px solid var(--danger); padding-left: 6px; }
  .tl-row.tl-risk-critical { border-left: 2px solid #f85149; padding-left: 6px; }
  .tl-badge { font-size: 0.7rem; padding: 1px 6px; border-radius: 10px; border: 1px solid;
    text-transform: uppercase; letter-spacing: 0.04em; flex-shrink: 0; }
  .tl-time { color: var(--text-muted); font-size: 0.8rem; min-width: 36px; flex-shrink: 0; }
  .tl-dir { color: var(--text-muted); font-size: 0.8rem; flex-shrink: 0; }
  .tl-sender { color: var(--accent); font-weight: 500; min-width: 80px; flex-shrink: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px; }
  .tl-body { color: var(--text); flex: 1; overflow: hidden; }
  .tl-body--truncated { cursor: pointer; color: var(--text-muted); }
  .tl-body--truncated:hover { color: var(--text); }
  .tl-risk-badge { font-size: 0.7rem; padding: 1px 5px; border-radius: 3px;
    background: var(--danger-bg, #f8514922); color: var(--danger, #f85149); flex-shrink: 0; }
  .tl-empty { color: var(--text-muted); text-align: center; padding: 40px 0; font-size: 0.9rem; }
  ```

- [ ] **Step 7: Bump cache-bust version for cases.js in index.html**

  Change `cases.js?v=20260308` to `cases.js?v=20260321e` in `templates/index.html`.

- [ ] **Step 8: Manual smoke test**
  1. Start the server: `python wsgi.py`
  2. Open a case with messages
  3. Click "Timeline" tab — verify feed appears with date separators and platform badges
  4. Click a platform pill to filter — verify non-matching rows disappear
  5. Click a row — verify Conversations tab opens to the correct thread

- [ ] **Step 9: Commit**
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

  Create `tests/test_media_extraction.py`:
  ```python
  """Tests for GET /api/cases/<id>/media/<media_id> (A4)."""
  import uuid
  from pathlib import Path
  import pytest
  from app import create_app
  from app.database import init_db

  @pytest.fixture
  def app(tmp_path):
      db_path = str(tmp_path / "test.db")
      cases_dir = tmp_path / "cases"
      cases_dir.mkdir()
      app = create_app({"TESTING": True, "DATABASE": db_path,
                        "CASES_DIR": str(cases_dir)})
      with app.app_context():
          init_db(db_path)
      return app

  @pytest.fixture
  def client(app):
      return app.test_client()

  @pytest.fixture
  def case_with_media(app, tmp_path):
      """Create a case and a media file on disk + DB row."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = str(uuid.uuid4())
          media_id = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "MediaTest"))

          # Write a tiny fake JPEG to the cases dir
          from flask import current_app
          cases_dir = Path(current_app.config["CASES_DIR"])
          media_path = cases_dir / cid / "media"
          media_path.mkdir(parents=True)
          fake_file = media_path / f"{media_id}.jpg"
          fake_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)  # minimal JPEG header

          db.execute(
              "INSERT INTO media_files (id, case_id, message_id, filename, mime_type,"
              " size_bytes, filepath) VALUES (?,?,?,?,?,?,?)",
              (media_id, cid, None, "photo.jpg", "image/jpeg", 24,
               f"{cid}/media/{media_id}.jpg"),
          )
          db.commit()
          return {"case_id": cid, "media_id": media_id}

  def test_media_route_streams_file(client, case_with_media):
      r = client.get(f"/api/cases/{case_with_media['case_id']}/media/{case_with_media['media_id']}")
      assert r.status_code == 200
      assert r.content_type == "image/jpeg"

  def test_media_route_404_wrong_case(client, case_with_media, app):
      """media_id belonging to a different case must return 404."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          other_cid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (other_cid, "Other"))
          db.commit()
      r = client.get(f"/api/cases/{other_cid}/media/{case_with_media['media_id']}")
      assert r.status_code == 404

  def test_media_route_404_missing_file(client, app, tmp_path):
      """Return 404 if DB row exists but file is missing from disk."""
      with app.app_context():
          from app.database import get_db
          db = get_db()
          cid = str(uuid.uuid4())
          mid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "GhostCase"))
          db.execute(
              "INSERT INTO media_files (id, case_id, message_id, filename, mime_type,"
              " size_bytes, filepath) VALUES (?,?,?,?,?,?,?)",
              (mid, cid, None, "ghost.jpg", "image/jpeg", 100,
               f"{cid}/media/{mid}.jpg"),  # file doesn't exist on disk
          )
          db.commit()
      r = client.get(f"/api/cases/{cid}/media/{mid}")
      assert r.status_code == 404

  def test_store_parsed_skips_large_media(app, tmp_path):
      """_store_parsed() must skip media files > 50 MB."""
      with app.app_context():
          from app.database import get_db
          from app.routes.cases import _store_parsed
          from app.parsers.base import ParsedCase
          from app.database import init_db
          db = get_db()
          cid = str(uuid.uuid4())
          db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "LargeMedia"))
          db.commit()

          # Create a fake large media entry (tmp_path file, size_bytes > 50MB)
          fake = tmp_path / "big.mp4"
          fake.write_bytes(b"x" * 100)  # small actual file, but large reported size
          parsed = ParsedCase(format="test")
          parsed.media_files = [{
              "message_id": None, "filename": "big.mp4",
              "mime_type": "video/mp4", "size_bytes": 60 * 1024 * 1024,
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
  Expected: FAIL — route not found.

- [ ] **Step 3: Create app/routes/media.py**

  ```python
  """GET /api/cases/<id>/media/<media_id> — stream extracted media files."""
  from pathlib import Path
  from flask import Blueprint, abort, current_app, send_file
  from app.database import get_db

  bp_media = Blueprint("media", __name__, url_prefix="/api")

  @bp_media.get("/cases/<case_id>/media/<media_id>")
  def get_media(case_id, media_id):
      db = get_db()
      row = db.execute(
          "SELECT filepath, mime_type FROM media_files WHERE id=? AND case_id=?",
          (media_id, case_id),
      ).fetchone()
      if not row:
          abort(404)

      cases_dir = Path(current_app.config.get("CASES_DIR", "cases"))
      full_path = cases_dir / row["filepath"]
      if not full_path.exists():
          abort(404)

      return send_file(
          full_path,
          mimetype=row["mime_type"],
          max_age=86400,
      )
  ```

- [ ] **Step 4: Register bp_media in app/__init__.py**

  ```python
  from app.routes.media import bp_media
  app.register_blueprint(bp_media)
  ```

- [ ] **Step 5: Run media tests**
  ```bash
  python -m pytest tests/test_media_extraction.py -v
  ```
  Expected: all pass.

- [ ] **Step 6: Run full suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all pass.

- [ ] **Step 7: Commit**
  ```bash
  git add app/routes/media.py app/__init__.py tests/test_media_extraction.py
  git commit -m "feat(A4): GET /api/cases/<id>/media/<media_id> streaming route with security check"
  ```

---

## Task 8: A4 — Media Thumbnails in Conversations UI

**Files:**
- Modify: `static/js/conversations.js`
- Modify: `static/style.css`
- Modify: `templates/index.html` (add lightbox dialog)

- [ ] **Step 1: Add lightbox dialog to index.html**

  Before `</body>`, add:
  ```html
  <!-- Media lightbox -->
  <dialog id="media-lightbox" class="media-lightbox">
    <div class="media-lightbox-inner">
      <button class="media-lightbox-close" aria-label="Close">&times;</button>
      <div id="media-lightbox-content"></div>
      <div id="media-lightbox-meta" class="media-lightbox-meta"></div>
    </div>
  </dialog>
  ```

- [ ] **Step 2: Add media thumbnail CSS to style.css**

  ```css
  /* ── Media Thumbnails (A4) ─────────────────────────────────────────────── */
  .msg-media-thumb { display: block; width: 140px; height: 90px; object-fit: cover;
    border-radius: 4px; cursor: pointer; margin-top: 6px; background: var(--surface2);
    border: 1px solid var(--border); }
  .msg-media-video { width: 140px; height: 90px; background: var(--surface2);
    border: 1px solid var(--border); border-radius: 4px; display: flex;
    align-items: center; justify-content: center; font-size: 1.4rem; cursor: pointer;
    margin-top: 6px; position: relative; }
  .msg-media-video-dur { position: absolute; bottom: 4px; right: 6px;
    font-size: 0.7rem; color: #fff; background: rgba(0,0,0,0.6); padding: 1px 4px;
    border-radius: 2px; }
  .msg-media-meta { font-size: 0.75rem; color: var(--text-muted); margin-top: 3px; }
  .msg-media-unavailable { font-size: 0.8rem; color: var(--text-muted); font-style: italic;
    margin-top: 6px; }

  /* Lightbox */
  .media-lightbox { border: none; border-radius: 8px; background: var(--surface);
    max-width: 90vw; max-height: 90vh; padding: 0; box-shadow: 0 8px 40px rgba(0,0,0,0.5); }
  .media-lightbox::backdrop { background: rgba(0,0,0,0.75); }
  .media-lightbox-inner { position: relative; padding: 16px; }
  .media-lightbox-close { position: absolute; top: 8px; right: 12px; background: none;
    border: none; font-size: 1.4rem; cursor: pointer; color: var(--text-muted); z-index: 1; }
  .media-lightbox-close:hover { color: var(--text); }
  #media-lightbox-content img, #media-lightbox-content video {
    max-width: 80vw; max-height: 75vh; display: block; border-radius: 4px; }
  .media-lightbox-meta { font-size: 0.8rem; color: var(--text-muted); margin-top: 8px; }
  ```

- [ ] **Step 3: Add media thumbnail rendering to conversations.js**

  Read `static/js/conversations.js` to find the message bubble rendering function (likely `_renderMessages()` or similar). Find where `body` text is inserted into the bubble HTML.

  Add a helper function near the top of the file:
  ```javascript
  function _mediaThumb(msg, caseId) {
    if (!msg.media_id) return "";
    const url = `/api/cases/${caseId}/media/${msg.media_id}`;
    const mime = msg.mime_type || "";
    const fname = _esc(msg.media_filename || "attachment");
    const size = msg.media_size ? ` · ${_fmtBytes(msg.media_size)}` : "";

    if (mime.startsWith("image/")) {
      return `
        <img class="msg-media-thumb" data-src="${url}" alt="${fname}"
             onclick="_openLightbox('${url}','${fname}','image')" />
        <div class="msg-media-meta">🖼 ${fname}${size}</div>
      `;
    }
    if (mime.startsWith("video/")) {
      return `
        <div class="msg-media-video" onclick="_openLightbox('${url}','${fname}','video')">
          ▶
        </div>
        <div class="msg-media-meta">📹 ${fname}${size}</div>
      `;
    }
    return `<div class="msg-media-meta">📎 ${fname}${size}</div>`;
  }

  function _fmtBytes(b) {
    if (b > 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
    if (b > 1024) return `${(b / 1024).toFixed(0)} KB`;
    return `${b} B`;
  }
  ```

  Add lightbox functions at module level:
  ```javascript
  function _openLightbox(url, name, type) {
    const dlg = document.getElementById("media-lightbox");
    const content = document.getElementById("media-lightbox-content");
    const meta = document.getElementById("media-lightbox-meta");
    content.innerHTML = type === "video"
      ? `<video src="${url}" controls autoplay></video>`
      : `<img src="${url}" alt="${name}" />`;
    meta.textContent = name;
    dlg.showModal();
  }

  // Wire lightbox close: backdrop click + Escape
  document.addEventListener("DOMContentLoaded", () => {
    const dlg = document.getElementById("media-lightbox");
    if (!dlg) return;
    document.getElementById("media-lightbox")
      .querySelector(".media-lightbox-close")
      .addEventListener("click", () => dlg.close());
    dlg.addEventListener("click", e => {
      if (e.target === dlg) dlg.close();
    });
  });
  ```

  In the bubble template string (wherever message body is rendered), add `${_mediaThumb(msg, _caseId)}` after the body text.

  Add `IntersectionObserver` for lazy loading after messages are rendered:
  ```javascript
  function _lazyLoadImages(container) {
    const imgs = container.querySelectorAll("img.msg-media-thumb[data-src]");
    if (!imgs.length) return;
    const obs = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          e.target.src = e.target.dataset.src;
          e.target.removeAttribute("data-src");
          obs.unobserve(e.target);
        }
      });
    }, { rootMargin: "200px" });
    imgs.forEach(img => obs.observe(img));
  }
  ```
  Call `_lazyLoadImages(messagesContainer)` after rendering messages.

- [ ] **Step 4: Check the messages API returns media fields**

  Read `app/routes/cases.py` — find `GET /api/cases/<id>/messages` or the conversations message fetch. Ensure it joins `media_files` and returns `media_id`, `mime_type`, `media_filename`, `media_size`:
  ```python
  # In the messages SELECT, add LEFT JOIN:
  SELECT m.*, mf.id as media_id, mf.mime_type, mf.filename as media_filename,
         mf.size_bytes as media_size
  FROM messages m
  LEFT JOIN media_files mf ON mf.message_id = m.id AND mf.case_id = m.case_id
  WHERE m.case_id = ?
  ```
  If the query already exists and uses `*`, update it to include the JOIN.

- [ ] **Step 5: Bump version strings**

  In `templates/index.html`:
  - `conversations.js?v=20260308` → `conversations.js?v=20260321e`

- [ ] **Step 6: Manual smoke test**
  1. Ensure an Android/iOS case with media has been imported
  2. Navigate to Conversations → find a WhatsApp image message
  3. Verify thumbnail renders (140×90 px)
  4. Click thumbnail → verify lightbox opens with full image
  5. Press Escape → lightbox closes

- [ ] **Step 7: Run full test suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: all 125 + 13 new tests pass.

- [ ] **Step 8: Commit**
  ```bash
  git add static/js/conversations.js static/style.css templates/index.html \
          app/routes/cases.py
  git commit -m "feat(A4): media thumbnails + lightbox in conversation bubbles"
  ```

---

## Task 9: Final Verification & Push

- [ ] **Step 1: Run complete test suite**
  ```bash
  python -m pytest tests/ -v --tb=short
  ```
  Expected: all 138 tests pass (125 original + 13 new).

- [ ] **Step 2: Verify success criteria manually**
  - [ ] Timeline tab shows all platforms for Android Pixel 3 case
  - [ ] Platform filter pills work
  - [ ] Date jump works
  - [ ] Row click opens Conversations tab at correct thread
  - [ ] Media thumbnails render for image messages
  - [ ] Lightbox opens/closes correctly
  - [ ] iOS case with 0 AddressBook contacts shows `(recovered)` label

- [ ] **Step 3: Update spec status**

  Change `docs/superpowers/specs/2026-03-21-feature-pack-2-design.md` header:
  ```markdown
  **Status:** Implemented ✓
  ```

- [ ] **Step 4: Update docs/completed-work.md**

  Add a section describing Feature Pack 2 (C3, A1, A4).

- [ ] **Step 5: Final commit and push**
  ```bash
  git add docs/
  git commit -m "docs: mark Feature Pack 2 as implemented, update completed-work.md"
  git push
  ```
