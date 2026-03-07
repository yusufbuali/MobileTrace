# Missing Parser Features Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add three missing artifact parsers: Signal Android (SQLCipher key-based decryption), iMessage iOS group chats and attachments, Telegram iOS.

**Architecture:** All three extend existing parser classes (`android_parser.py` and `ios_parser.py`). No new parser files needed, only test additions. Each follows the established `_read_X()` pattern: open DB, query, return `list[dict]` via `_norm_message()`. Signal requires `pysqlcipher3` added to `requirements.txt` and `Dockerfile`.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), pysqlcipher3 (Signal only), pytest

---

## Task 1 — Telegram on iOS

**Context:** On iOS, Telegram stores messages in `TelegramDatabase.sqlite` (plain SQLite, readable without any binary TLV parsing — unlike Android's `cache4.db`). The file lives inside the app container at a UUID path like:
`private/var/mobile/Containers/Data/Application/<UUID>/Documents/Telegram/postbox/db/db`
(no file extension — matched by path suffix, same mechanism already used for WhatsApp).

**Files:**
- Modify: `app/parsers/ios_parser.py`
- Modify: `tests/test_ios_parser.py`

### Step 1: Write the failing test

Add to `tests/test_ios_parser.py`:

```python
def test_read_telegram_ios(tmp_path):
    """iOSParser reads Telegram messages from TelegramDatabase.sqlite."""
    import sqlite3
    db = tmp_path / "ios_telegram.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE messages (
            mid INTEGER PRIMARY KEY, peer_id INTEGER,
            timestamp INTEGER, message TEXT, outgoing INTEGER
        );
        CREATE TABLE peers (
            id INTEGER PRIMARY KEY, phone TEXT,
            first_name TEXT, last_name TEXT
        );
        INSERT INTO peers VALUES (42, '+97312345678', 'Alice', 'Smith');
        INSERT INTO messages VALUES (1, 42, 1700000000, 'Hello Telegram iOS', 0);
    """)
    conn.commit()
    conn.close()

    from app.parsers.ios_parser import iOSParser
    msgs = iOSParser()._read_telegram_ios(db, [])
    assert len(msgs) == 1
    assert msgs[0]["platform"] == "telegram"
    assert msgs[0]["direction"] == "incoming"
    assert "Hello" in msgs[0]["body"]
```

Run: `python -m pytest tests/test_ios_parser.py::test_read_telegram_ios -v`
Expected: FAIL with `AttributeError: '_read_telegram_ios'`

### Step 2: Add Telegram to suffix targets in ios_parser.py

Replace the `_WHATSAPP_SUFFIX` constant with a dict that covers both suffixes:

```python
# OLD — remove this:
_WHATSAPP_SUFFIX = "Documents/ChatStorage.sqlite"

# NEW — replace with:
_SUFFIX_TARGETS: dict[str, str] = {
    "whatsapp": "Documents/ChatStorage.sqlite",
    "telegram": "Documents/Telegram/postbox/db/db",  # no file extension
}
```

Update `_build_wanted_map()` to loop over `_SUFFIX_TARGETS`:

```python
def _build_wanted_map(self, names: list[str]) -> dict[str, str]:
    norm = {n.lstrip("/"): n for n in names}
    wanted: dict[str, str] = {}
    for key, rel_path in _TARGET_DBS.items():
        if rel_path in norm:
            wanted[norm[rel_path]] = key
    for stripped, orig in norm.items():
        for key, suffix in _SUFFIX_TARGETS.items():
            if stripped.endswith(suffix) and key not in wanted:
                wanted[orig] = key
                break
    return wanted
```

### Step 3: Implement `_read_telegram_ios()`

Add to `iOSParser` class:

```python
def _read_telegram_ios(self, path: Path | None, warnings: list) -> list[dict]:
    conn = self._open_db(path)
    if not conn:
        return []  # optional — no warning if absent
    msgs = []
    try:
        peer_names: dict[int, str] = {}
        try:
            for r in conn.execute(
                "SELECT id, phone, first_name, last_name FROM peers"
            ).fetchall():
                name = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()
                peer_names[r["id"]] = name or r["phone"] or str(r["id"])
        except Exception:
            pass
        rows = conn.execute(
            "SELECT mid, peer_id, timestamp, message, outgoing"
            " FROM messages WHERE message IS NOT NULL AND message != ''"
            " ORDER BY timestamp ASC"
        ).fetchall()
        for r in rows:
            from_me = bool(r["outgoing"])
            peer = peer_names.get(r["peer_id"], str(r["peer_id"]))
            msgs.append(self._norm_message(
                platform="telegram",
                body=r["message"] or "",
                sender="device" if from_me else peer,
                recipient=peer if from_me else "device",
                direction="outgoing" if from_me else "incoming",
                timestamp=_apple_ts_to_iso(r["timestamp"]),
                thread_id=str(r["peer_id"]),
            ))
    except Exception as exc:
        warnings.append(f"Telegram iOS parse error: {exc}")
    finally:
        conn.close()
    return msgs
```

### Step 4: Wire into `parse()`

In `iOSParser.parse()`, after the `_read_whatsapp()` line add:

```python
result.messages += self._read_telegram_ios(db_paths.get("telegram"), warnings)
```

### Step 5: Run tests

```bash
python -m pytest tests/test_ios_parser.py -v
```
Expected: all pass including new test.

### Step 6: Commit

```bash
git add app/parsers/ios_parser.py tests/test_ios_parser.py
git commit -m "feat(parser): add Telegram iOS parser via TelegramDatabase.sqlite"
```

---

## Task 2 — iMessage Group Chats + Attachments

**Context:** `sms.db` has a `chat` table for group threads, a `chat_message_join` linking table, and an `attachment` + `message_attachment_join` table for media. Currently `_read_sms()` only reads `message.handle_id` (1-on-1 only, so all group messages share the same thread_id). This task adds:
1. Group thread identification via `chat_message_join → chat.chat_identifier`
2. Attachment metadata (mime_type, filename) stored in `raw_json.attachments`

**Files:**
- Modify: `app/parsers/ios_parser.py`
- Modify: `tests/test_ios_parser.py`

### Step 1: Write the failing test

```python
def test_read_sms_group_and_attachments(tmp_path):
    """_read_sms() uses group chat_identifier as thread_id and captures attachments."""
    import sqlite3
    db = tmp_path / "sms_group.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, handle_id INTEGER, date INTEGER,
            text TEXT, is_from_me INTEGER, cache_roomnames TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY, mime_type TEXT, transfer_name TEXT);
        CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
        INSERT INTO handle VALUES (1, 'Alice');
        INSERT INTO chat VALUES (10, 'chat123', 'Group Chat');
        INSERT INTO message VALUES (1, 1, 700000000, 'Hi group', 0, 'chat123');
        INSERT INTO chat_message_join VALUES (10, 1);
        INSERT INTO attachment VALUES (1, 'image/jpeg', 'photo.jpg');
        INSERT INTO message_attachment_join VALUES (1, 1);
    """)
    conn.commit()
    conn.close()

    from app.parsers.ios_parser import iOSParser
    msgs = iOSParser()._read_sms(db, [])
    assert len(msgs) == 1
    assert msgs[0]["thread_id"] == "chat123"
    assert msgs[0]["raw_json"].get("attachments") == [
        {"mime_type": "image/jpeg", "filename": "photo.jpg"}
    ]
```

Run: `python -m pytest tests/test_ios_parser.py::test_read_sms_group_and_attachments -v`
Expected: FAIL (thread_id will be handle id, no attachments key in raw_json)

### Step 2: Replace `_read_sms()` in ios_parser.py

```python
def _read_sms(self, path: Path | None, warnings: list) -> list[dict]:
    conn = self._open_db(path)
    if not conn:
        if path:
            warnings.append("SMS DB not found or unreadable")
        return []
    msgs = []
    try:
        # Build message_id -> chat_identifier (group thread ID)
        msg_chat: dict[int, str] = {}
        try:
            for r in conn.execute(
                "SELECT cmj.message_id, c.chat_identifier"
                " FROM chat_message_join cmj JOIN chat c ON cmj.chat_id = c.ROWID"
            ).fetchall():
                msg_chat[r["message_id"]] = r["chat_identifier"]
        except Exception:
            pass

        # Build message_id -> attachments list
        msg_att: dict[int, list] = {}
        try:
            for r in conn.execute(
                "SELECT maj.message_id, a.mime_type, a.transfer_name"
                " FROM message_attachment_join maj"
                " JOIN attachment a ON maj.attachment_id = a.ROWID"
            ).fetchall():
                msg_att.setdefault(r["message_id"], []).append({
                    "mime_type": r["mime_type"] or "",
                    "filename": r["transfer_name"] or "",
                })
        except Exception:
            pass

        rows = conn.execute("""
            SELECT m.ROWID, h.id AS address, m.date AS ts,
                   m.text AS body, m.is_from_me AS from_me,
                   m.cache_roomnames AS room
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            ORDER BY m.date ASC
        """).fetchall()
        for r in rows:
            from_me = bool(r["from_me"])
            addr = r["address"] or "unknown"
            mid = r["ROWID"]
            thread_id = msg_chat.get(mid) or r["room"] or addr
            attachments = msg_att.get(mid, [])
            raw = {"attachments": attachments} if attachments else {}
            body = r["body"] or (f"[{len(attachments)} attachment(s)]" if attachments else "")
            msgs.append(self._norm_message(
                platform="sms",
                body=body,
                sender="device" if from_me else addr,
                recipient=addr if from_me else "device",
                direction="outgoing" if from_me else "incoming",
                timestamp=_apple_ts_to_iso(r["ts"]),
                thread_id=thread_id,
                raw=raw,
            ))
    except Exception as exc:
        warnings.append(f"SMS parse error: {exc}")
    finally:
        conn.close()
    return msgs
```

### Step 3: Run tests

```bash
python -m pytest tests/test_ios_parser.py -v
```
Expected: all pass.

### Step 4: Commit

```bash
git add app/parsers/ios_parser.py tests/test_ios_parser.py
git commit -m "feat(parser): iMessage group chats and attachment metadata from sms.db"
```

---

## Task 3 — Signal Android (Key-Based SQLCipher Decryption)

**Context:** `signal.db` is SQLCipher-encrypted. Cellebrite and GrayKey sometimes export the raw 32-byte (64-char hex) SQLCipher key. We add an optional `signal_key` field to the Evidence tab. If provided, we open `signal.db` with `pysqlcipher3` using raw key mode (`PRAGMA key = "x'<hex>'"`) and parse the `sms` table. If no key is supplied, the existing warning stands.

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`
- Modify: `app/parsers/android_parser.py`
- Modify: `app/parsers/dispatcher.py`
- Modify: `app/routes/cases.py`
- Modify: `templates/index.html`
- Modify: `static/js/cases.js`
- Modify: `static/style.css`
- Modify: `tests/test_android_parser.py`

### Step 1: Write the failing test

Add to `tests/test_android_parser.py`:

```python
def test_signal_read_accepts_key_kwarg(tmp_path):
    """_read_signal() accepts signal_key kwarg. None path -> empty list, no crash."""
    from app.parsers.android_parser import AndroidParser
    result = AndroidParser()._read_signal(None, [], signal_key="aa" * 32)
    assert result == []
```

Run: `python -m pytest tests/test_android_parser.py::test_signal_read_accepts_key_kwarg -v`
Expected: FAIL with `AttributeError: '_read_signal'`

### Step 2: Add `_read_signal()` to AndroidParser

```python
def _read_signal(self, path: Path | None, warnings: list, signal_key: str = "") -> list[dict]:
    if not path or not path.exists():
        return []
    if not signal_key:
        warnings.append(
            "Signal database found but no decryption key provided. "
            "Supply the 64-char hex SQLCipher key via the Evidence upload form."
        )
        return []
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher
    except ImportError:
        warnings.append("pysqlcipher3 not installed — cannot decrypt Signal database.")
        return []
    msgs = []
    conn = None
    try:
        conn = sqlcipher.connect(str(path))
        conn.row_factory = sqlcipher.Row
        key_hex = signal_key.strip().lower()
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\";")
        conn.execute("PRAGMA cipher_page_size = 4096;")
        conn.execute("SELECT count(*) FROM sqlite_master;")  # validate key works
        rows = conn.execute(
            "SELECT body, date_sent, date_received, address, type"
            " FROM sms ORDER BY date_sent ASC"
        ).fetchall()
        for r in rows:
            direction = "outgoing" if r["type"] == 2 else "incoming"
            addr = r["address"] or "unknown"
            msgs.append(self._norm_message(
                platform="signal",
                body=r["body"] or "",
                sender="device" if direction == "outgoing" else addr,
                recipient=addr if direction == "outgoing" else "device",
                direction=direction,
                timestamp=_ms_to_iso(r["date_sent"] or r["date_received"]),
                thread_id=addr,
            ))
    except Exception as exc:
        warnings.append(f"Signal decrypt failed: {exc}")
    finally:
        if conn:
            conn.close()
    return msgs
```

### Step 3: Update `parse()` to call `_read_signal`

Change signature to accept `signal_key`:

```python
def parse(self, source_path: Path, dest_dir: Path, signal_key: str = "") -> ParsedCase:
```

Replace the old `if "signal" in db_paths` warning block with:

```python
# Remove old block:
# if "signal" in db_paths:
#     warnings.append("Signal database (signal.db) is SQLCipher-encrypted...")

# Add after _read_telegram():
result.messages += self._read_signal(db_paths.get("signal"), warnings, signal_key=signal_key)
```

### Step 4: Pass `**kwargs` through dispatcher

In `app/parsers/dispatcher.py`:

```python
def dispatch(source_path: Path, dest_dir: Path, **kwargs) -> ParsedCase:
    for parser in _PARSERS:
        if parser.can_handle(source_path):
            return parser.parse(source_path, dest_dir, **kwargs)
    raise ValueError(f"No parser found for: {source_path}")
```

### Step 5: Extract `signal_key` in the upload route

In `app/routes/cases.py`, `upload_evidence()`:

```python
# File upload mode — add after saving file:
signal_key = request.form.get("signal_key", "").strip()
return _ingest_path(db, case_id, case_dir, dest_path, signal_key=signal_key)

# Local path (JSON) mode — add after source_path validation:
signal_key = body.get("signal_key", "").strip()
return _ingest_path(db, case_id, case_dir, source_path, signal_key=signal_key)
```

Update `_ingest_path()` signature:

```python
def _ingest_path(db, case_id: str, case_dir: Path, source_path: Path, signal_key: str = ""):
    ...
    parsed = dispatch(source_path, extract_dir, signal_key=signal_key)
```

### Step 6: Add `signal_key` input to Evidence tab

In `templates/index.html`, inside `form#form-upload-evidence` after the file input,
and inside `form#form-path-evidence` after the path input:

```html
<details class="ev-advanced">
  <summary>Advanced options</summary>
  <label>Signal decryption key (optional)
    <input name="signal_key" type="password"
           placeholder="64-char hex key from Cellebrite / GrayKey"
           autocomplete="off" />
    <p class="muted" style="font-size:0.75rem;margin-top:2px">
      Only required if this device has Signal installed. Leave blank to skip.
    </p>
  </label>
</details>
```

In `static/js/cases.js`, the browser-upload FormData already picks up named inputs
automatically. For the local-path form, include `signal_key` in the JSON body:

```javascript
// In the formPath submit handler, update body builder:
const signal_key = new FormData(formPath).get("signal_key")?.trim() || "";
body: JSON.stringify({ source_path: path, signal_key }),
```

### Step 7: Add CSS for advanced toggle

In `static/style.css`:

```css
.ev-advanced { margin-top: 10px; }
.ev-advanced summary {
  font-size: 0.8rem; color: var(--text-muted);
  cursor: pointer; user-select: none;
}
```

### Step 8: Add pysqlcipher3 dependency

`requirements.txt` — add:
```
pysqlcipher3==1.2.0
```

`Dockerfile` — after existing pip install line, add:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends libsqlcipher-dev \
    && pip install pysqlcipher3==1.2.0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
```

### Step 9: Run all tests

```bash
python -m pytest tests/test_android_parser.py tests/test_ios_parser.py -v
```
Expected: all pass.

### Step 10: Docker smoke test

```bash
docker compose up -d --build
# Upload an Android evidence file without a Signal key
# Evidence tab should show warning: "Signal database found but no decryption key provided"
# Uploading with a valid 64-char hex key should produce Signal messages in Conversations tab
```

### Step 11: Commit

```bash
git add app/parsers/android_parser.py app/parsers/dispatcher.py app/routes/cases.py \
        templates/index.html static/js/cases.js static/style.css \
        requirements.txt Dockerfile tests/test_android_parser.py
git commit -m "feat(parser): Signal Android key-based decryption via pysqlcipher3"
```

---

## Files Changed Summary

| File | Task |
|---|---|
| `app/parsers/ios_parser.py` | Task 1 (Telegram iOS), Task 2 (iMessage groups + attachments) |
| `app/parsers/android_parser.py` | Task 3 (Signal `_read_signal`, `parse()` kwarg) |
| `app/parsers/dispatcher.py` | Task 3 (`dispatch()` passes `**kwargs`) |
| `app/routes/cases.py` | Task 3 (`signal_key` from request, `_ingest_path` kwarg) |
| `templates/index.html` | Task 3 (`signal_key` input in Evidence tab) |
| `static/js/cases.js` | Task 3 (`signal_key` in local-path JSON body) |
| `static/style.css` | Task 3 (`.ev-advanced` toggle styles) |
| `requirements.txt` | Task 3 |
| `Dockerfile` | Task 3 |
| `tests/test_ios_parser.py` | Task 1 + 2 |
| `tests/test_android_parser.py` | Task 3 |
