# MobileTrace Feature Pack 2 — Design Spec

**Date:** 2026-03-21
**Status:** Approved

---

## Overview

Three primary features added to MobileTrace, a Flask/SQLite forensic intelligence SPA for mobile evidence analysis. All features extend existing architecture without breaking current functionality.

---

## Feature A1: Global Timeline Tab

### Goal
Give investigators a chronological cross-platform view of all messages and calls within a case, replacing the need to manually correlate timestamps across the Conversations tab's per-thread view.

### Backend

**New route:** `GET /api/cases/<id>/timeline`

- Query parameters: `cursor` (ISO timestamp, for pagination), `limit` (default 100), `platforms` (comma-separated: `sms,whatsapp,telegram,signal,calls`)
- Merges `messages` and `call_logs` tables, sorted by `timestamp ASC`
- Returns: `{ items: [...], next_cursor: "..." | null }`
- Each item: `{ id, type: "message"|"call", platform, timestamp, direction, sender, recipient, body, thread_id, risk_level | null, duration_seconds | null }`
- Risk level populated by joining `analysis_results` where the message's thread is flagged HIGH or CRITICAL

**No new DB table required** — query combines existing `messages` + `call_logs` with optional join to `analysis_results`.

### Frontend

- New `Timeline` tab added to case tab bar, between Conversations and Analysis
- New file: `static/js/timeline.js`
- Tab registered in `templates/index.html` and activated in `static/js/cases.js`

**UI components:**
- Platform filter pills: All / SMS / WhatsApp / Telegram / Signal / Calls (multi-select, default All)
- Jump-to-date: HTML5 `<input type="date">` — on change, fetches timeline with `cursor` set to midnight of selected date
- Compact feed: date-separator divs (sticky, e.g. "2021-03-14 — Monday"), then per-message rows:
  - Platform badge (colored: SMS=blue, WhatsApp=green, Telegram=teal, Signal=purple, Calls=grey)
  - Timestamp (HH:MM)
  - Direction indicator (→ sent / ← received)
  - Sender name or number
  - Message body (truncated to 120 chars, expandable on click)
  - Risk badge (HIGH/CRITICAL) when present
- Pagination: "Load more" button at bottom (loads next 100 rows)
- Clicking a message row navigates to that thread in the Conversations tab (reuses `selectThread()`)

### Edge Cases
- Cases with no messages: show empty state "No messages in this case yet"
- Cases with >10,000 messages: pagination handles this; no virtual scroll required
- Calls with no body: show "📞 Call · {duration}" as body

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
    message_id  TEXT,
    filename    TEXT NOT NULL,
    mime_type   TEXT NOT NULL,
    size_bytes  INTEGER,
    filepath    TEXT NOT NULL,
    extracted_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (case_id) REFERENCES cases(id)
);
CREATE INDEX idx_media_files_case ON media_files(case_id);
CREATE INDEX idx_media_files_message ON media_files(message_id);
```

**Media extraction during parse** (in `app/parsers/base.py` or per-parser):
- When parsing iOS/Android dumps, detect media attachments in message records (WhatsApp `ZWAMEDIAITEM`, Telegram `MediaPath`, SMS MMS parts)
- Extract files matching `*.jpg`, `*.jpeg`, `*.png`, `*.heic`, `*.mp4`, `*.mov` (max 50 MB per file to avoid disk exhaustion)
- Copy to `cases/<case_id>/media/<uuid>.<ext>`
- Insert row into `media_files`, set `message_id` to parent message's ID

**New route:** `GET /api/cases/<id>/media/<media_id>`
- Validates `media_id` belongs to `case_id` (security: no path traversal)
- Streams file with correct `Content-Type` header
- `Cache-Control: max-age=86400` (media files are immutable once extracted)

**New route:** `GET /api/cases/<id>/media` (optional, for future gallery view)
- Returns list of all media for a case

### Frontend

In `static/js/conversations.js`, message bubble rendering:
- If `message.media_id` is present, render below the body text:
  - **Images** (`image/*`): `<img class="msg-media-thumb" src="/api/cases/{caseId}/media/{mediaId}" loading="lazy" alt="{filename}">` with `width:140px; height:90px; object-fit:cover; border-radius:4px; cursor:pointer`
  - **Videos** (`video/*`): placeholder div with play button icon + duration, click opens video in lightbox
  - **Below thumbnail:** `<div class="msg-media-meta">{icon} {filename} · {sizeFormatted}</div>`
- Clicking any thumbnail opens a **lightbox overlay** (`<dialog>` element):
  - Images: full-size `<img>` with pan/zoom on click
  - Videos: `<video controls autoplay>` element
  - Click backdrop or press Escape to close
- Lazy loading: use `IntersectionObserver` — set `src` only when bubble enters viewport

**New CSS classes:** `.msg-media-thumb`, `.msg-media-meta`, `.msg-lightbox`

### Edge Cases
- File not found on disk (deleted/moved): show broken image icon with "Media unavailable"
- HEIC format: convert to JPEG during extraction using `pillow` with `pillow-heif` plugin; fallback to placeholder if unavailable
- Large files (>50 MB): skip extraction, show `📎 Large file — {filename} ({size})` placeholder
- Media with no `message_id` (orphaned): still extractable, shown in future gallery view

---

## Feature C3: Encrypted iOS Contacts Recovery

### Goal
When an iOS device uses full-disk encryption, `AddressBook.sqlitedb` returns 0 contacts. Automatically reconstruct a contacts list from messaging metadata so investigators can identify people of interest even without the AddressBook.

### Implementation

**Location:** `app/parsers/ios_parser.py` — after existing contacts extraction

**Recovery logic (runs only when `len(contacts) == 0` after AddressBook parse):**

1. **WhatsApp contacts** — query `wa.db` → `wa_contacts` table: `SELECT jid, display_name, number FROM wa_contacts WHERE is_whatsapp_contact = 1`
2. **Telegram contacts** — query `cache4.db` → `TGUser` or equivalent: extract `name`, `phone`
3. **SMS senders** — from already-parsed `messages` list: collect unique `(address, contact_name)` pairs where `contact_name` is non-null
4. **Deduplication** — normalize phone numbers (strip spaces, dashes, leading zeros; E.164 format where possible), merge by normalized number
5. **Insert** — each recovered contact inserted into `contacts` table with `source = 'recovered'` (new nullable column, default `NULL` for normal contacts)

**DB schema change:**
```sql
ALTER TABLE contacts ADD COLUMN source TEXT DEFAULT NULL;
-- NULL = from AddressBook (normal), 'recovered' = reconstructed from messaging metadata
```

**UI display:**
- In the Contacts section of the Evidence tab: recovered contacts show a `(recovered)` label in muted text next to the name
- In the Overview tab contact count: tooltip "X contacts (Y recovered from messaging data)" when recovered contacts exist
- No behavioural difference — recovered contacts work identically for search, IOC extraction, correlation graph

### Edge Cases
- Partial encryption: some AddressBook rows readable — merge with recovered; deduplicate by normalized number; AddressBook rows take priority
- No messaging data either: show "No contacts found — device may be fully encrypted" in Evidence tab
- Phone number normalization failures (international formats): store as-is, log warning

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
- **A4 dependencies:** `pillow` (already likely present), `pillow-heif` (optional, for HEIC → JPEG conversion)
- **No breaking API changes** — all new routes are additive
- **SQLite migration:** `media_files` table creation and `contacts.source` column addition handled in `app/database.py` `init_db()` using `IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN` with try/except for idempotency
- **Security:** media route validates `case_id` ownership before streaming; no directory traversal possible via `media_id` (UUID lookup, not path)
- **Test coverage:** new pytest fixtures for each feature; media extraction tested with small synthetic fixture files

---

## Implementation Order

1. **C3** (Encrypted iOS Contacts Recovery) — pure backend, no new UI, lowest risk
2. **A1** (Global Timeline Tab) — new route + new JS file, no parser changes
3. **A4** (Media Thumbnails) — most complex: parser changes + new DB table + new route + JS + CSS

---

## Success Criteria

- [ ] Timeline tab shows all messages + calls sorted chronologically, platform filter works, date jump works
- [ ] Media thumbnails render inline for WhatsApp image messages in Android Pixel 3 test case
- [ ] iOS case with 0 AddressBook contacts auto-recovers contacts from WhatsApp/SMS metadata
- [ ] All existing 125 tests continue to pass
- [ ] 3 new test files covering timeline API, media extraction, and contact recovery
