# Evidence Annotations — Design

**Date:** 2026-03-21
**Status:** Approved

---

## Overview

Allow investigators to tag individual messages as key evidence, add free-text notes, and have those annotations appear in the HTML and PDF reports. Annotations are stored server-side in SQLite so they persist across sessions and are visible to all users of the case.

---

## Architecture

### Database

**New table in `app/database.py`:**

```sql
CREATE TABLE IF NOT EXISTS annotations (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    message_id  TEXT NOT NULL,
    tag         TEXT NOT NULL DEFAULT 'KEY_EVIDENCE',
    note        TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_annotations_case    ON annotations(case_id);
CREATE INDEX IF NOT EXISTS idx_annotations_message ON annotations(message_id);
```

Tags enum: `KEY_EVIDENCE`, `SUSPICIOUS`, `ALIBI`, `EXCULPATORY`, `NOTE`

---

### Backend

**New route file:** `app/routes/annotations.py`
**Blueprint:** `bp_annotations`, registered in `app/__init__.py`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/cases/<id>/annotations` | List all annotations for a case |
| `POST` | `/api/cases/<id>/annotations` | Create annotation `{ message_id, tag, note }` |
| `PATCH` | `/api/cases/<id>/annotations/<ann_id>` | Update `{ tag?, note? }` |
| `DELETE` | `/api/cases/<id>/annotations/<ann_id>` | Delete annotation |

`GET /annotations` response includes joined message fields (platform, thread_id, body snippet, timestamp, direction) for rendering without a second API call.

---

### Frontend — Conversations Tab

**Annotation button on each bubble:**
Every `.msg-bubble` gets a small `☆` flag button (`.ann-btn`) shown on hover. Clicking opens an inline annotation panel below the bubble:

```
[ Tag dropdown: KEY_EVIDENCE ▾ ]  [ Note input _________________ ]  [ Save ] [ Cancel ]
```

If an annotation exists, the button becomes `★` (filled), tag badge shown on the bubble, and clicking re-opens the panel with existing data for editing.

**Annotated bubble indicator:**
A colored left-border + small tag badge (`KEY_EVIDENCE` in amber, `SUSPICIOUS` in red, `ALIBI` in blue, `EXCULPATORY` in green, `NOTE` in grey) on the message bubble.

**Annotations sidebar filter:**
A toggle pill "Annotated only" in the conversation thread sidebar — when active, the thread list shows only threads containing at least one annotation (computed client-side from the loaded annotation set).

---

### Frontend — Load Strategy

On `initConversations(caseId)`:
1. Fetch `GET /api/cases/<caseId>/annotations` once — store in `_annotations: Map<message_id, annotation>`
2. When rendering bubbles: check map, apply badge + button state
3. On save/delete: update map and re-render affected bubble only (no full reload)

---

### Report Integration

**HTML report (`templates/report.html`):**
Add "Annotated Evidence" section (after Conversation Excerpts, before AI Analysis):
- Table: Tag badge | Platform | Thread | Timestamp | Direction | Message Body | Note
- Sorted by: tag severity (KEY_EVIDENCE first), then timestamp

**`app/routes/reports.py`:**
Add query:
```python
annotations = db.execute(
    "SELECT a.*, m.platform, m.thread_id, m.body, m.timestamp, m.direction "
    "FROM annotations a JOIN messages m ON a.message_id = m.id "
    "WHERE a.case_id=? ORDER BY a.created_at ASC",
    (case_id,)
).fetchall()
```

---

## Error Handling

- Duplicate annotation on same message → `UPSERT` (replace), not error
- message_id not in messages table → 400 validation error
- Note > 1000 chars → 400

---

## Testing

- `tests/test_annotations_routes.py`: CRUD — create, list, patch, delete; 404 on wrong case; duplicate upsert behaviour
- Conversations tab: annotated messages get `★` button (visual, no automated test)

---

## Files Changed

| File | Type |
|---|---|
| `app/database.py` | Modified — new annotations table + indexes |
| `app/routes/annotations.py` | New — CRUD blueprint |
| `app/__init__.py` | Modified — register bp_annotations |
| `app/routes/reports.py` | Modified — include annotations in report context |
| `static/js/conversations.js` | Modified — annotation buttons, panel, map load |
| `templates/index.html` | Modified — annotation panel HTML |
| `templates/report.html` | Modified — annotated evidence section |
| `static/style.css` | Modified — annotation badges, button, panel styles |
| `tests/test_annotations_routes.py` | New |
