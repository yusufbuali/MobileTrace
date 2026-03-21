# MobileTrace Feature Pack 2 — Design Spec

**Date:** 2026-03-21
**Status:** Implemented ✓

---

## Overview

Three primary features added to MobileTrace, a Flask/SQLite forensic intelligence SPA for mobile evidence analysis. All features extend existing architecture without breaking current functionality.

---

## Feature A1: Global Timeline Tab

### Goal
Give investigators a chronological cross-platform view of all messages and calls within a case, replacing the need to manually correlate timestamps across the Conversations tab's per-thread view.

### Backend

**New route:** `GET /api/cases/<id>/timeline`

- Query parameters:
  - `cursor_ts` (ISO timestamp string) + `cursor_id` (integer) — composite cursor for tie-safe pagination
  - `limit` (integer, default 100, max 500) — matches existing `GET /api/cases/<id>/messages` cap pattern
  - `platforms` (comma-separated: `sms,whatsapp,telegram,signal,calls`)
- Merges `messages` and `call_logs` tables via UNION, sorted by `(timestamp ASC, row_key ASC)` where `row_key` is a namespaced string: `'msg-' || id` for messages, `'call-' || id` for calls. This prevents id collision between the two tables (both have `INTEGER PRIMARY KEY AUTOINCREMENT` — ids can overlap).
- Pagination WHERE clause: `WHERE (timestamp > cursor_ts) OR (timestamp = cursor_ts AND row_key > cursor_key)` — composite cursor with namespaced key prevents duplicate rows on timestamp ties
- Returns: `{ items: [...], next_cursor: { ts: "...", key: "msg-123" } | null }`
- Each item shape:
  ```json
  {
    "id": 123,
    "type": "message",
    "platform": "whatsapp",
    "timestamp": "2021-03-14T09:14:00",
    "direction": "incoming",
    "sender": "Ahmed",
    "recipient": null,
    "body": "package is ready",
    "thread_id": "group-logistics",
    "risk_level": "HIGH"
  }
  ```
- For `call_logs` rows: `type = "call"`, `sender = number WHERE direction = 'incoming' ELSE NULL`, `recipient = number WHERE direction = 'outgoing' ELSE NULL`, `body = null`, `duration_seconds` added as extra field
- **Risk level:** Application-level lookup, not a SQL JOIN. After fetching timeline items, group by platform. For each platform present, check `analysis_results` for the case's most recent analysis — if `result_parsed.risk_level` is HIGH or CRITICAL for that platform's artifact, tag all messages of that platform as that risk level. This is a coarse platform-level signal, not per-message. Per-message risk is out of scope for this feature.

### Frontend

- New `Timeline` tab added to case tab bar, between Conversations and Analysis
- New file: `static/js/timeline.js` (ES module, exported `initTimeline(caseId)`)
- Tab registered in `templates/index.html`, activated in `static/js/cases.js` (same pattern as other tabs)

**UI components:**
- Platform filter pills: All / SMS / WhatsApp / Telegram / Signal / Calls (multi-select, default All)
- Jump-to-date: HTML5 `<input type="date">` — on change, fetches with `cursor_ts` set to midnight of selected date, `cursor_id = 0`
- Compact feed with date-separator `<div>`s (e.g. "2021-03-14 — Monday"), then per-row:
  - Coloured platform badge (SMS=blue, WhatsApp=green, Telegram=teal, Signal=purple, Calls=grey)
  - Timestamp (HH:MM)
  - Direction arrow (→ sent / ← received)
  - Sender name or number
  - Message body truncated to 120 chars; click expands to full
  - Risk badge (HIGH / CRITICAL) when platform analysis flagged that level
- "Load more" button at bottom appends next 100 rows
- Clicking a message row: dispatch `new CustomEvent('mt:open-thread', { detail: { platform, thread: threadId } })` on `document` — `thread` matches the key destructured by the live listener in `conversations.js` line 34 (`const { platform, thread } = e.detail`). This avoids a direct import cycle between `timeline.js` and `conversations.js`.

### Edge Cases
- No messages: empty state "No messages in this case yet"
- Calls rows: body rendered as `📞 Call · {duration}` (e.g. "📞 Call · 4m 12s")
- Date jump to date with no messages: load the closest page after that date (cursor returns next available rows)

---

## Feature A4: Media Thumbnails in Conversations

### Goal
Show image and video attachments inline in conversation bubbles rather than as missing/empty body text, enabling investigators to see visual evidence without leaving the app.

### Backend

**New DB table: `media_files`**
```sql
CREATE TABLE IF NOT EXISTS media_files (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    message_id  INTEGER,
    filename    TEXT NOT NULL,
    mime_type   TEXT NOT NULL,
    size_bytes  INTEGER,
    filepath    TEXT NOT NULL,
    extracted_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (message_id) REFERENCES messages(id)
);
CREATE INDEX IF NOT EXISTS idx_media_files_case    ON media_files(case_id);
CREATE INDEX IF NOT EXISTS idx_media_files_message ON media_files(message_id);
```

Note: `message_id INTEGER` matches `messages.id INTEGER PRIMARY KEY AUTOINCREMENT`. `id` is stored as a lowercase hyphenated UUID string via `str(uuid.uuid4())` — consistent with `evidence_files.id` in `database.py`. `filepath` stores path **relative to `cases_dir`** (e.g. `"<case_id>/media/<uuid>.jpg"`), resolved at serve time using `app.config['CASES_DIR']`. This avoids stale absolute paths if the volume is remounted.

**`ParsedCase` dataclass extension** (`app/parsers/base.py`):
```python
@dataclass
class ParsedCase:
    # existing fields ...
    media_files: list[dict] = field(default_factory=list)
    # Each dict: { message_id: int|None, filename: str, mime_type: str,
    #              size_bytes: int, tmp_path: str }
    # tmp_path: absolute path to extracted file in a temp location;
    # _store_parsed() copies it to cases_dir and inserts the DB row.
```

**`_store_parsed()` extension** (`app/routes/cases.py`):
- After existing contacts/messages/call_logs inserts, add a `media_files` arm:
  - For each `media_files` entry: generate UUID, copy from `tmp_path` to `{cases_dir}/{case_id}/media/{uuid}{ext}`, insert row with `filepath = f"{case_id}/media/{uuid}{ext}"`
  - Skip files where `size_bytes > 50 * 1024 * 1024` (50 MB cap)

**Media extraction during parse** (per-parser responsibility):
- **Android** (`android_parser.py`): detect WhatsApp `ZWAMEDIAITEM` or equivalent attachment records; for each, copy the referenced file from the dump into `ParsedCase.media_files`
- **iOS** (`ios_parser.py`): detect `MediaPath` fields in Telegram and WhatsApp message records
- HEIC → JPEG conversion: wrap `import pillow_heif` in try/except at module top (same pattern as `from weasyprint import HTML` in `reports.py` lines 234-236). If unavailable, store HEIC as-is and set `mime_type = "image/heic"` — browser will show broken image, which is acceptable fallback.
- System dependency note: `pillow-heif` requires `libheif` (`libheif-dev` on Debian/Ubuntu, `libheif` on Alpine). Add to Dockerfile alongside existing WeasyPrint deps.

**New route:** `GET /api/cases/<id>/media/<media_id>`
- Look up `media_files` row by `id` where `case_id = <id>` — UUID lookup, no path traversal possible
- Resolve absolute path: `cases_dir / row['filepath']`
- Validate file exists on disk; 404 if missing
- Stream with `send_file(path, mimetype=row['mime_type'])`, `Cache-Control: max-age=86400`

### Frontend

In `static/js/conversations.js`, message bubble rendering — if `message.media_id` is set:
- **Images** (`image/*`): `<img class="msg-media-thumb" loading="lazy" alt="{filename}">` — `src` set by `IntersectionObserver` when bubble enters viewport (lazy load)
- **Videos** (`video/*`): `<div class="msg-media-thumb msg-media-video">▶ {duration}</div>` placeholder; click fetches and opens `<video>` in lightbox
- **Below thumbnail:** `<div class="msg-media-meta">{icon} {filename} · {size}</div>`
- **Lightbox:** `<dialog id="media-lightbox">` opened via `dialog.showModal()` (not CSS visibility — `<dialog>` requires programmatic opening). Contains `<img>` or `<video controls autoplay>`. Closed by clicking backdrop or pressing Escape.

**New CSS classes:** `.msg-media-thumb`, `.msg-media-meta`, `#media-lightbox`

### Edge Cases
- File not on disk: broken image icon + "Media unavailable" below
- HEIC without `pillow-heif`: browser shows broken image (acceptable)
- Files >50 MB: skip extraction, show `📎 Large file — {filename} ({size})` in bubble instead
- No `message_id` (orphaned media): insert with `message_id = NULL`; not shown in conversations but available via future gallery

---

## Feature C3: Encrypted iOS/Android Contacts Recovery

### Goal
When a device uses full-disk encryption, `AddressBook.sqlitedb` (iOS) or `contacts2.db` (Android) returns 0 contacts. Automatically reconstruct a contacts list from messaging metadata.

### Applies to
Both `ios_parser.py` and `android_parser.py` — not iOS-only.

### DB Schema Change
```sql
ALTER TABLE contacts ADD COLUMN source TEXT DEFAULT NULL;
-- NULL = from AddressBook/contacts2.db (normal)
-- 'recovered' = reconstructed from messaging metadata
```
Wrapped in try/except in `init_db()` for idempotency (column already exists → ignore `OperationalError`).

### `_norm_contact()` Extension (`app/parsers/base.py`)
The existing signature is `_norm_contact(name, phone, email, source_app, raw=None)` where `source_app` tracks which parser produced the contact (e.g. `"ios_addressbook"`, `"whatsapp_contacts"`). Add a new **separate** `source` kwarg (default `None`) that tracks whether the contact was recovered vs. directly parsed:
```python
def _norm_contact(name, phone, email, source_app, raw=None, source=None):
    return { "name": name, "phone": _norm_phone(phone), "email": email,
             "source_app": source_app, "raw_json": raw, "source": source }
```
`source` is distinct from `source_app` — `source_app` = which parser/table, `source` = `None` (normal) or `'recovered'`.

### `_store_parsed()` Extension (`app/routes/cases.py`)
The **existing** contacts INSERT must be updated to include the new `source` column alongside existing columns:
```sql
INSERT OR IGNORE INTO contacts (case_id, name, phone, email, source_app, raw_json, source)
VALUES (?, ?, ?, ?, ?, ?, ?)
```
Pass `c.get('source')` as the seventh value (defaults to `None` for all normal contacts — no behaviour change for existing code paths). The C3 recovery logic calls `_norm_contact(..., source='recovered')` and goes through this same INSERT.

### Recovery Logic (runs when `len(parsed.contacts) == 0` after primary parse)

**iOS recovery sources** (correct table names from `ios_parser.py`):
1. **WhatsApp** — `wa.db` → `wa_contacts` table: `WHERE display_name IS NOT NULL` (no `is_whatsapp_contact` filter — column absent in newer multi-device schema)
2. **Telegram** — `cache4.db` → `peers` table: columns `phone, first_name, last_name` (matches existing `_read_telegram_ios()` at line 351-358 of `ios_parser.py`)
3. **SMS** — from already-parsed `messages` list: collect unique `(address, contact_name)` pairs where `contact_name` is non-null

**Android recovery sources** (correct table names from `android_parser.py`):
1. **WhatsApp** — `wa.db` → `wa_contacts`: `WHERE display_name IS NOT NULL` (same as iOS — no `is_whatsapp_contact` filter)
2. **Telegram** — `telegramDB.db` → `user_contacts_v7`: columns `uid, fname, sname` (matches existing `_read_telegram()` at lines 388-395 of `android_parser.py`)
3. **SMS** — from already-parsed `messages` list: unique `(address, contact_name)` pairs

**Deduplication:** normalize phone numbers via existing `_norm_phone()`. For conflicts, AddressBook/contacts2.db rows take priority over recovered rows (recovered runs only when primary returns 0, so no conflict in normal case; partial encryption edge case: re-run with merge if primary returns >0).

**Insert:** each recovered contact passed through `_norm_contact(name, number, source='recovered')`.

### UI Display
- Evidence tab Contacts section: recovered contacts show `(recovered)` in `var(--text-muted)` after the name
- Overview tab contact count badge: tooltip "X contacts (Y recovered from messaging data)" when `Y > 0`
- All other behaviour identical (search, IOC extraction, correlation graph)

### Edge Cases
- Partial encryption (some AddressBook rows present): primary parse returns >0 → recovery skipped entirely. The "some recovered from messaging" case is deferred to a future deduplication pass.
- No messaging data either: "No contacts found — device may be fully encrypted" shown in Evidence tab
- Phone normalization failure (unrecognised format): store as-is, log a warning

---

## Backlog Features (Next Spec)

Approved for planning but out of scope for this implementation cycle:

| ID | Feature | Description | Complexity |
|----|---------|-------------|------------|
| A2 | Cross-case crime patterns | Dashboard panel: crime categories ranked across all cases, co-occurrence matrix, trend over time | Medium |
| A3 | Global full-text search | Search bar queries all cases at once, results grouped by case, filtered by platform/date | Medium |
| C1 | Signal decryption | Accept user-supplied SQLCipher key in Settings → open `signal.db` | High |
| C2 | Additional parsers | TikTok `db/db.sqlite`, Viber `viber_data`, Threema `ThreemaData.db` | High |

---

## Architecture Constraints

- **No new dependencies** for A1 and C3 (pure SQL + JS)
- **A4 dependencies:** `pillow` (already present), `pillow-heif` (optional, requires `libheif` system lib — add to Dockerfile)
- **No breaking API changes** — all new routes are additive
- **SQLite migrations:** `media_files` table via `CREATE TABLE IF NOT EXISTS`; `contacts.source` column via `ALTER TABLE ... ADD COLUMN` with try/except `OperationalError` — both in `app/database.py` `init_db()`
- **Security:** media route uses UUID lookup (not path construction) — no directory traversal possible; `filepath` is relative and resolved server-side
- **Test coverage:** 3 new test files (see below)

---

## Implementation Order

1. **C3** (Encrypted Contacts Recovery) — pure backend, no new UI, lowest risk
2. **A1** (Global Timeline Tab) — new route + new JS file, no parser changes
3. **A4** (Media Thumbnails) — most complex: parser changes + new DB table + new route + JS + CSS

---

## Test Plan

**`tests/test_timeline_routes.py`**
- Timeline returns empty list for case with no messages
- Timeline merges SMS + WhatsApp rows sorted by timestamp
- Timeline pagination: page 1 + cursor (`ts`, `key`) returns page 2 without duplicates even when messages and calls share the same timestamp (tests tie-breaking via namespaced `row_key`)
- Timeline platform filter: `platforms=sms` excludes WhatsApp rows
- Timeline limit cap: `limit=9999` clamped to 500

**`tests/test_media_extraction.py`**
- `_store_parsed()` copies media file to `cases/<id>/media/` and inserts DB row
- `GET /api/cases/<id>/media/<media_id>` streams correct file with correct MIME type
- `GET /api/cases/<id>/media/<media_id>` returns 404 if `media_id` belongs to different case
- File >50 MB is skipped (no DB row inserted)

**`tests/test_contact_recovery.py`**
- iOS parse with empty AddressBook triggers recovery; WhatsApp contacts appear with `source='recovered'`
- iOS parse with non-empty AddressBook skips recovery; all contacts have `source=NULL`
- Deduplication: same phone in WhatsApp + SMS recovered as single contact
- Recovered contacts show `(recovered)` label in Contacts API response
- Android parse with empty contacts2.db triggers same recovery path

---

## Success Criteria

- [ ] Timeline tab shows all messages + calls sorted chronologically for Android Pixel 3 test case (86 SMS + 24 WhatsApp + 30 Telegram + 30 calls)
- [ ] Platform filter pills correctly include/exclude platform rows
- [ ] Date jump scrolls to correct date
- [ ] Clicking a timeline row opens the correct thread in Conversations tab
- [ ] Media thumbnails render inline for WhatsApp image messages in Android Pixel 3 test case
- [ ] Lightbox opens on thumbnail click; closes on backdrop click and Escape key
- [ ] iOS case with 0 AddressBook contacts auto-recovers contacts from WhatsApp/SMS metadata with `(recovered)` label
- [ ] iOS case with non-zero AddressBook contacts does NOT trigger recovery
- [ ] Recovered contacts appear in correlation graph and IOC extraction identically to normal contacts
- [ ] All existing 125 tests continue to pass
- [ ] All 3 new test files pass
