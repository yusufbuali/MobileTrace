# Evidence Annotations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let investigators tag individual messages with a category (KEY_EVIDENCE, SUSPICIOUS, ALIBI, EXCULPATORY, NOTE) and optional free-text note; persist annotations in SQLite; surface them in the Conversations tab UI and in the HTML report.

**Architecture:** New `annotations` table in `database.py`; new `app/routes/annotations.py` Flask blueprint with full CRUD; `conversations.js` loads annotations on tab init and attaches flag buttons to every bubble; `reports.py` queries annotations to add an "Annotated Evidence" section to the report.

**Tech Stack:** Python 3.12, Flask, SQLite, vanilla JS ES modules, existing conftest.py pattern

---

## Task 1 — Database table

**Context:** The `annotations` table links to `messages` by integer `message_id` and to `cases` by `case_id`. The `tag` column is one of five fixed strings. We use `INSERT OR REPLACE` so re-annotating a message updates rather than errors.

**Files:**
- Modify: `app/database.py`
- Modify: `tests/test_database.py` (add one new test)

---

### Step 1: Write the failing test

Open `tests/test_database.py` and add at the bottom:

```python
def test_annotations_table_exists(app):
    from app.database import get_db
    with app.app_context():
        db = get_db()
        # Should not raise — table must exist
        db.execute("SELECT id, case_id, message_id, tag, note, created_at FROM annotations LIMIT 1")
```

Run: `python -m pytest tests/test_database.py::test_annotations_table_exists -v`
Expected: **FAIL** — `OperationalError: no such table: annotations`

---

### Step 2: Add the table to `app/database.py`

In `_SCHEMA`, add after the `chat_history` block (before the FTS5 section):

```sql
CREATE TABLE IF NOT EXISTS annotations (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    message_id  INTEGER NOT NULL,
    tag         TEXT NOT NULL DEFAULT 'KEY_EVIDENCE',
    note        TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_annotations_case    ON annotations(case_id);
CREATE INDEX IF NOT EXISTS idx_annotations_message ON annotations(message_id);
```

---

### Step 3: Run test

```bash
python -m pytest tests/test_database.py::test_annotations_table_exists -v
```

Expected: **PASS**

---

### Step 4: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass.

---

### Step 5: Commit

```bash
git add app/database.py tests/test_database.py
git commit -m "feat(annotations): add annotations table to schema"
```

---

## Task 2 — Annotations CRUD API (`app/routes/annotations.py`)

**Context:** Four endpoints: GET list, POST create (upsert), PATCH update, DELETE. GET list joins with messages so the caller gets platform/thread/body/timestamp for each annotation without a second request. Upsert semantics: if an annotation for that message already exists it is replaced (tag or note changed).

**Files:**
- Create: `app/routes/annotations.py`
- Modify: `app/__init__.py`
- Create: `tests/test_annotations_routes.py`

---

### Step 1: Write the failing tests

Create `tests/test_annotations_routes.py`:

```python
"""CRUD tests for /api/cases/<id>/annotations."""
import json
import pytest
from app import create_app
from app.database import init_db, close_db, get_db


@pytest.fixture
def client(tmp_path):
    app = create_app(testing=True)
    db_path = str(tmp_path / "test.db")
    app.config["MT_CONFIG"]["server"]["database_path"] = db_path
    app.config["MT_CONFIG"]["server"]["cases_dir"] = str(tmp_path / "cases")
    init_db(db_path)
    with app.test_client() as c:
        yield c
    close_db()


def _make_case(client):
    r = client.post("/api/cases", json={"title": "Ann Test", "officer": "Det"})
    assert r.status_code == 201
    return r.get_json()["id"]


def _seed_message(case_id) -> int:
    """Insert a message directly and return its integer id."""
    db = get_db()
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp) "
        "VALUES (?,?,?,?,?,?,?)",
        (case_id, "whatsapp", "incoming", "Alice", "device", "Suspicious text", "2024-01-01T10:00:00"),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_annotation(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    r = client.post(
        f"/api/cases/{case_id}/annotations",
        json={"message_id": msg_id, "tag": "KEY_EVIDENCE", "note": "Important message"},
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["tag"] == "KEY_EVIDENCE"
    assert data["note"] == "Important message"
    assert "id" in data


def test_create_annotation_missing_message_id(client):
    case_id = _make_case(client)
    r = client.post(f"/api/cases/{case_id}/annotations", json={"tag": "NOTE"})
    assert r.status_code == 400


def test_create_annotation_invalid_tag(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    r = client.post(
        f"/api/cases/{case_id}/annotations",
        json={"message_id": msg_id, "tag": "INVALID_TAG"},
    )
    assert r.status_code == 400


def test_create_annotation_404_case(client):
    r = client.post("/api/cases/nope/annotations", json={"message_id": 1, "tag": "NOTE"})
    assert r.status_code == 404


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_annotations_empty(client):
    case_id = _make_case(client)
    r = client.get(f"/api/cases/{case_id}/annotations")
    assert r.status_code == 200
    assert r.get_json() == []


def test_list_annotations_returns_message_fields(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    client.post(f"/api/cases/{case_id}/annotations",
                json={"message_id": msg_id, "tag": "SUSPICIOUS", "note": "x"})
    r = client.get(f"/api/cases/{case_id}/annotations")
    data = r.get_json()
    assert len(data) == 1
    ann = data[0]
    for field in ("id", "message_id", "tag", "note", "created_at",
                  "platform", "thread_id", "body", "timestamp", "direction"):
        assert field in ann, f"missing field: {field}"


# ── Upsert (duplicate) ────────────────────────────────────────────────────────

def test_upsert_annotation_replaces(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    client.post(f"/api/cases/{case_id}/annotations",
                json={"message_id": msg_id, "tag": "NOTE", "note": "first"})
    client.post(f"/api/cases/{case_id}/annotations",
                json={"message_id": msg_id, "tag": "KEY_EVIDENCE", "note": "updated"})
    r = client.get(f"/api/cases/{case_id}/annotations")
    data = r.get_json()
    assert len(data) == 1   # not duplicated
    assert data[0]["tag"] == "KEY_EVIDENCE"
    assert data[0]["note"] == "updated"


# ── Patch ─────────────────────────────────────────────────────────────────────

def test_patch_annotation(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    r = client.post(f"/api/cases/{case_id}/annotations",
                    json={"message_id": msg_id, "tag": "NOTE", "note": "old"})
    ann_id = r.get_json()["id"]
    r2 = client.patch(f"/api/cases/{case_id}/annotations/{ann_id}",
                      json={"note": "updated note"})
    assert r2.status_code == 200
    assert r2.get_json()["note"] == "updated note"


def test_patch_annotation_404(client):
    case_id = _make_case(client)
    r = client.patch(f"/api/cases/{case_id}/annotations/nonexistent", json={"note": "x"})
    assert r.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_annotation(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    r = client.post(f"/api/cases/{case_id}/annotations",
                    json={"message_id": msg_id, "tag": "NOTE"})
    ann_id = r.get_json()["id"]
    r2 = client.delete(f"/api/cases/{case_id}/annotations/{ann_id}")
    assert r2.status_code == 200
    # Verify gone
    r3 = client.get(f"/api/cases/{case_id}/annotations")
    assert r3.get_json() == []


def test_delete_annotation_404(client):
    case_id = _make_case(client)
    r = client.delete(f"/api/cases/{case_id}/annotations/nonexistent")
    assert r.status_code == 404
```

Run: `python -m pytest tests/test_annotations_routes.py -v`
Expected: **FAIL** — 404 on all annotation endpoints

---

### Step 2: Create `app/routes/annotations.py`

```python
"""Evidence annotations CRUD routes."""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from app.database import get_db

bp_annotations = Blueprint("annotations", __name__, url_prefix="/api")

_VALID_TAGS = {"KEY_EVIDENCE", "SUSPICIOUS", "ALIBI", "EXCULPATORY", "NOTE"}


@bp_annotations.get("/cases/<case_id>/annotations")
def list_annotations(case_id: str):
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
        return jsonify({"error": "case not found"}), 404
    rows = db.execute(
        """
        SELECT a.id, a.message_id, a.tag, a.note, a.created_at,
               m.platform, m.thread_id, m.body, m.timestamp, m.direction, m.sender
        FROM annotations a
        JOIN messages m ON a.message_id = m.id
        WHERE a.case_id = ?
        ORDER BY m.timestamp ASC
        """,
        (case_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp_annotations.post("/cases/<case_id>/annotations")
def create_annotation(case_id: str):
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
        return jsonify({"error": "case not found"}), 404

    body = request.get_json(force=True) or {}
    message_id = body.get("message_id")
    tag = (body.get("tag") or "KEY_EVIDENCE").upper()
    note = (body.get("note") or "")[:1000]

    if not message_id:
        return jsonify({"error": "message_id required"}), 400
    if tag not in _VALID_TAGS:
        return jsonify({"error": f"tag must be one of {sorted(_VALID_TAGS)}"}), 400

    # Upsert: delete existing annotation for this message in this case, then insert
    db.execute(
        "DELETE FROM annotations WHERE case_id=? AND message_id=?",
        (case_id, message_id),
    )
    ann_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO annotations (id, case_id, message_id, tag, note) VALUES (?,?,?,?,?)",
        (ann_id, case_id, message_id, tag, note),
    )
    db.commit()
    row = db.execute("SELECT * FROM annotations WHERE id=?", (ann_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp_annotations.patch("/cases/<case_id>/annotations/<ann_id>")
def update_annotation(case_id: str, ann_id: str):
    db = get_db()
    row = db.execute(
        "SELECT * FROM annotations WHERE id=? AND case_id=?", (ann_id, case_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(force=True) or {}
    tag = body.get("tag")
    note = body.get("note")

    if tag is not None:
        tag = tag.upper()
        if tag not in _VALID_TAGS:
            return jsonify({"error": f"tag must be one of {sorted(_VALID_TAGS)}"}), 400
        db.execute("UPDATE annotations SET tag=? WHERE id=?", (tag, ann_id))
    if note is not None:
        db.execute("UPDATE annotations SET note=? WHERE id=?", (note[:1000], ann_id))
    db.commit()
    updated = db.execute("SELECT * FROM annotations WHERE id=?", (ann_id,)).fetchone()
    return jsonify(dict(updated))


@bp_annotations.delete("/cases/<case_id>/annotations/<ann_id>")
def delete_annotation(case_id: str, ann_id: str):
    db = get_db()
    row = db.execute(
        "SELECT id FROM annotations WHERE id=? AND case_id=?", (ann_id, case_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM annotations WHERE id=?", (ann_id,))
    db.commit()
    return jsonify({"deleted": ann_id})
```

---

### Step 3: Register blueprint in `app/__init__.py`

Add after the IOC blueprint lines:

```python
from .routes.annotations import bp_annotations
app.register_blueprint(bp_annotations)
```

---

### Step 4: Run tests

```bash
python -m pytest tests/test_annotations_routes.py -v
```

Expected: **all pass**

---

### Step 5: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass.

---

### Step 6: Commit

```bash
git add app/routes/annotations.py app/__init__.py tests/test_annotations_routes.py
git commit -m "feat(annotations): CRUD API for per-message evidence annotations"
```

---

## Task 3 — Conversations tab: annotation buttons and panel

**Context:** When `initConversations(caseId)` is called, it fetches `GET /api/cases/<id>/annotations` once and stores a `Map<message_id, annotation>`. Each rendered bubble gets a `☆`/`★` flag button. Clicking opens an inline panel (tag dropdown + note input + Save/Delete). On save, the map is updated and the bubble badge re-rendered without a full reload.

**Files:**
- Modify: `static/js/conversations.js`
- Modify: `templates/index.html`
- Modify: `static/style.css`

---

### Step 1: Add annotation panel HTML to `templates/index.html`

Inside the Conversations tab panel (`#tab-conversations`), add a hidden annotation panel template that JavaScript will clone per bubble. Place it just before the closing `</div>` of `#tab-conversations`:

```html
<!-- Annotation panel template (hidden, cloned by JS) -->
<template id="tpl-annotation-panel">
  <div class="ann-panel">
    <select class="ann-tag-select">
      <option value="KEY_EVIDENCE">KEY EVIDENCE</option>
      <option value="SUSPICIOUS">SUSPICIOUS</option>
      <option value="ALIBI">ALIBI</option>
      <option value="EXCULPATORY">EXCULPATORY</option>
      <option value="NOTE">NOTE</option>
    </select>
    <input class="ann-note-input" type="text" maxlength="1000" placeholder="Add a note (optional)…" />
    <div class="ann-panel-actions">
      <button class="ann-save-btn btn-primary">Save</button>
      <button class="ann-delete-btn btn-secondary" style="display:none">Remove</button>
      <button class="ann-cancel-btn btn-secondary">Cancel</button>
    </div>
  </div>
</template>
```

---

### Step 2: Update `static/js/conversations.js`

Add the following changes to `conversations.js`:

**A. Load annotations map on init** — at the top of `initConversations(caseId)`, after the null guard, add:

```javascript
// Load all annotations for this case into a map keyed by message_id
let _annotations = new Map(); // message_id (number) → annotation object

async function _loadAnnotations(caseId) {
  try {
    const res = await fetch(`/api/cases/${caseId}/annotations`);
    if (!res.ok) return;
    const list = await res.json();
    _annotations = new Map(list.map(a => [a.message_id, a]));
  } catch (_) { /* non-critical */ }
}
```

Call `await _loadAnnotations(caseId)` inside `initConversations()` before `_loadThreads()`.

**B. Add flag button to each bubble** — in `_renderBubble(msg)`, after constructing the bubble element, append:

```javascript
const ann = _annotations.get(msg.id);
const flagBtn = document.createElement("button");
flagBtn.className = "ann-flag-btn" + (ann ? " has-ann" : "");
flagBtn.title = ann ? `${ann.tag}${ann.note ? ": " + ann.note : ""}` : "Annotate";
flagBtn.textContent = ann ? "★" : "☆";
flagBtn.dataset.msgId = msg.id;
flagBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  _openAnnotationPanel(flagBtn, msg, caseId);
});
wrap.appendChild(flagBtn);

// If annotated, add tag badge
if (ann) {
  const badge = document.createElement("span");
  badge.className = `ann-tag-badge ann-tag-${ann.tag.toLowerCase()}`;
  badge.textContent = ann.tag.replace(/_/g, " ");
  wrap.appendChild(badge);
}
```

**C. Annotation panel open/save/delete** — add these functions:

```javascript
function _openAnnotationPanel(flagBtn, msg, caseId) {
  // Close any existing open panel
  document.querySelectorAll(".ann-panel").forEach(p => p.remove());

  const tpl = document.getElementById("tpl-annotation-panel");
  const panel = tpl.content.cloneNode(true).querySelector(".ann-panel");
  const ann = _annotations.get(msg.id);

  const select = panel.querySelector(".ann-tag-select");
  const noteInput = panel.querySelector(".ann-note-input");
  const saveBtn = panel.querySelector(".ann-save-btn");
  const deleteBtn = panel.querySelector(".ann-delete-btn");
  const cancelBtn = panel.querySelector(".ann-cancel-btn");

  if (ann) {
    select.value = ann.tag;
    noteInput.value = ann.note || "";
    deleteBtn.style.display = "";
  }

  saveBtn.addEventListener("click", async () => {
    const tag = select.value;
    const note = noteInput.value.trim();
    try {
      const res = await fetch(`/api/cases/${caseId}/annotations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: msg.id, tag, note }),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = await res.json();
      _annotations.set(msg.id, updated);
      _refreshBubbleAnnotation(flagBtn, updated);
      panel.remove();
    } catch (err) {
      alert(`Failed to save annotation: ${err.message}`);
    }
  });

  deleteBtn.addEventListener("click", async () => {
    const existing = _annotations.get(msg.id);
    if (!existing) { panel.remove(); return; }
    try {
      await fetch(`/api/cases/${caseId}/annotations/${existing.id}`, { method: "DELETE" });
      _annotations.delete(msg.id);
      _refreshBubbleAnnotation(flagBtn, null);
      panel.remove();
    } catch (err) {
      alert(`Failed to delete: ${err.message}`);
    }
  });

  cancelBtn.addEventListener("click", () => panel.remove());

  // Insert panel below the flag button
  flagBtn.insertAdjacentElement("afterend", panel);
  noteInput.focus();
}

function _refreshBubbleAnnotation(flagBtn, ann) {
  flagBtn.className = "ann-flag-btn" + (ann ? " has-ann" : "");
  flagBtn.textContent = ann ? "★" : "☆";
  flagBtn.title = ann ? `${ann.tag}${ann.note ? ": " + ann.note : ""}` : "Annotate";

  // Remove old badge if present
  const oldBadge = flagBtn.parentElement?.querySelector(".ann-tag-badge");
  if (oldBadge) oldBadge.remove();

  if (ann) {
    const badge = document.createElement("span");
    badge.className = `ann-tag-badge ann-tag-${ann.tag.toLowerCase()}`;
    badge.textContent = ann.tag.replace(/_/g, " ");
    flagBtn.insertAdjacentElement("afterend", badge);
  }
}
```

---

### Step 3: Add CSS to `static/style.css`

Append after the IOC styles block:

```css
/* ══ Evidence Annotations ═══════════════════════════════════════════════════ */

/* Flag button on each bubble */
.ann-flag-btn {
  background: none; border: none; cursor: pointer; font-size: 0.85rem;
  color: var(--text-muted); padding: 0 3px; line-height: 1;
  opacity: 0; transition: opacity 0.15s;
}
.msg-wrap:hover .ann-flag-btn { opacity: 1; }
.ann-flag-btn.has-ann { opacity: 1; color: #f59e0b; }

/* Tag badge on annotated bubbles */
.ann-tag-badge {
  font-size: 0.65rem; font-weight: 700; padding: 1px 6px; border-radius: 8px;
  text-transform: uppercase; letter-spacing: 0.04em; margin-left: 4px;
  vertical-align: middle;
}
.ann-tag-key_evidence { background: rgba(245,158,11,0.18); color: #f59e0b; border: 1px solid rgba(245,158,11,0.35); }
.ann-tag-suspicious    { background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }
.ann-tag-alibi         { background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.3); }
.ann-tag-exculpatory   { background: rgba(34,197,94,0.15); color: #4ade80; border: 1px solid rgba(34,197,94,0.3); }
.ann-tag-note          { background: rgba(159,177,199,0.12); color: var(--text-muted); border: 1px solid rgba(159,177,199,0.25); }

/* Annotation panel */
.ann-panel {
  display: flex; flex-direction: column; gap: 8px;
  padding: 10px 12px; margin-top: 6px;
  background: var(--sidebar-bg); border: 1px solid rgba(159,177,199,0.25);
  border-radius: 8px; max-width: 340px;
}
.ann-tag-select, .ann-note-input {
  width: 100%; padding: 6px 8px; font-size: 0.82rem;
  background: var(--bg); border: 1px solid rgba(159,177,199,0.25);
  border-radius: 6px; color: var(--text);
}
.ann-panel-actions { display: flex; gap: 6px; }
```

---

### Step 4: Manual smoke test

```bash
flask run
# Open Conversations tab → hover a bubble → click ☆
# Select tag, add note, Save → ★ badge appears
# Click ★ again → pre-filled panel; Remove → badge gone
```

---

### Step 5: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass.

---

### Step 6: Commit

```bash
git add static/js/conversations.js templates/index.html static/style.css
git commit -m "feat(annotations): annotation flag button + panel on conversation bubbles"
```

---

## Task 4 — Report: Annotated Evidence section

**Context:** The existing HTML report in `templates/report.html` gets a new "Annotated Evidence" section inserted after the Conversation Excerpts panel. The backend query in `app/routes/reports.py` joins annotations with messages. Only cases with ≥1 annotation show the section.

**Files:**
- Modify: `app/routes/reports.py`
- Modify: `templates/report.html`
- Modify: `tests/test_reports.py`

---

### Step 1: Write the failing test

In `tests/test_reports.py`, add:

```python
def test_report_includes_annotated_evidence_section(client):
    """Report shows Annotated Evidence section when annotations exist."""
    from app.database import get_db
    # Create case
    r = client.post("/api/cases", json={"title": "Ann Report Test", "officer": "Det"})
    case_id = r.get_json()["id"]
    # Seed a message
    db = get_db()
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp) "
        "VALUES (?,?,?,?,?,?,?)",
        (case_id, "whatsapp", "incoming", "Alice", "device", "Key evidence here", "2024-01-01T10:00:00"),
    )
    db.commit()
    msg_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Add annotation via API
    client.post(f"/api/cases/{case_id}/annotations",
                json={"message_id": msg_id, "tag": "KEY_EVIDENCE", "note": "Critical"})
    # Get report
    r2 = client.get(f"/api/cases/{case_id}/report")
    assert r2.status_code == 200
    html = r2.data.decode()
    assert "Annotated Evidence" in html
    assert "KEY EVIDENCE" in html or "KEY_EVIDENCE" in html
    assert "Critical" in html
```

Run: `python -m pytest tests/test_reports.py::test_report_includes_annotated_evidence_section -v`
Expected: **FAIL** — "Annotated Evidence" not in HTML

---

### Step 2: Update `app/routes/reports.py`

**A. Add annotations query** — in `get_report()`, after the `evidence_files` query block, add:

```python
annotation_rows = db.execute(
    """
    SELECT a.id, a.tag, a.note, a.created_at,
           m.platform, m.thread_id, m.body, m.timestamp, m.direction, m.sender
    FROM annotations a
    JOIN messages m ON a.message_id = m.id
    WHERE a.case_id = ?
    ORDER BY
        CASE a.tag
            WHEN 'KEY_EVIDENCE' THEN 1
            WHEN 'SUSPICIOUS'   THEN 2
            WHEN 'ALIBI'        THEN 3
            WHEN 'EXCULPATORY'  THEN 4
            ELSE 5
        END,
        m.timestamp ASC
    """,
    (case_id,),
).fetchall()
annotations = [dict(r) for r in annotation_rows]
```

**B. Add to ctx** — in the `ctx` dict, add:

```python
"annotations": annotations,
```

---

### Step 3: Update `templates/report.html`

Add the Annotated Evidence section **after** the Conversation Excerpts panel and **before** the AI Analysis panel:

```html
<!-- ── Annotated Evidence ──────────────────────────────────────────────────── -->
{% if annotations %}
<div class="panel">
  <h2>Annotated Evidence</h2>
  <p style="color:var(--muted);font-size:0.82rem;margin:0 0 14px">
    {{ annotations|length }} message{{ 's' if annotations|length != 1 else '' }}
    flagged by the investigator.
  </p>
  <table class="data-table">
    <thead>
      <tr>
        <th>Tag</th><th>Platform</th><th>Timestamp</th>
        <th>Direction</th><th>Sender</th><th>Message</th><th>Note</th>
      </tr>
    </thead>
    <tbody>
    {% for a in annotations %}
      <tr>
        <td>
          {% set tag_colors = {
            'KEY_EVIDENCE': '#f59e0b',
            'SUSPICIOUS': '#ef4444',
            'ALIBI': '#60a5fa',
            'EXCULPATORY': '#4ade80',
            'NOTE': '#9fb1c7'
          } %}
          <span class="badge" style="background:{{ tag_colors.get(a.tag, '#9fb1c7') }}20;
            color:{{ tag_colors.get(a.tag, '#9fb1c7') }};
            border:1px solid {{ tag_colors.get(a.tag, '#9fb1c7') }}40">
            {{ a.tag | replace('_', ' ') }}
          </span>
        </td>
        <td><span class="badge badge-{{ a.platform or 'unknown' }}">{{ a.platform or '—' }}</span></td>
        <td class="mono">{{ a.timestamp[:16] if a.timestamp else '—' }}</td>
        <td>{{ a.direction or '—' }}</td>
        <td class="mono">{{ a.sender or '—' }}</td>
        <td style="max-width:300px;word-break:break-word">{{ a.body or '[no body]' }}</td>
        <td style="color:var(--muted);font-style:{{ 'normal' if a.note else 'italic' }}">
          {{ a.note or '—' }}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}
```

---

### Step 4: Run tests

```bash
python -m pytest tests/test_reports.py -v
```

Expected: **all pass** including new test.

---

### Step 5: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass.

---

### Step 6: Commit

```bash
git add app/routes/reports.py templates/report.html tests/test_reports.py
git commit -m "feat(annotations): Annotated Evidence section in HTML report"
```

---

## Files Changed Summary

| File | Task |
|---|---|
| `app/database.py` | Task 1 — annotations table + indexes |
| `tests/test_database.py` | Task 1 — table existence test |
| `app/routes/annotations.py` | Task 2 (new) — CRUD blueprint |
| `app/__init__.py` | Task 2 — register bp_annotations |
| `tests/test_annotations_routes.py` | Task 2 (new) — 10 CRUD tests |
| `static/js/conversations.js` | Task 3 — annotation map, flag buttons, panel |
| `templates/index.html` | Task 3 — annotation panel template |
| `static/style.css` | Task 3 — flag button, badge, panel styles |
| `app/routes/reports.py` | Task 4 — annotations query + ctx |
| `templates/report.html` | Task 4 — Annotated Evidence section |
| `tests/test_reports.py` | Task 4 — report section test |
