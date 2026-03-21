# PDF Export for Court Reports — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `GET /api/cases/<id>/report/pdf` endpoint that renders the existing HTML report to a downloadable PDF using WeasyPrint, with a "Download PDF" button next to the existing Report link.

**Architecture:** Extract `get_report()`'s context-building into a shared `_build_report_context(db, case_id)` helper; the new PDF endpoint calls the helper, renders HTML via `render_template`, then calls `weasyprint.HTML(string=...).write_pdf()`. A `@media print` + `@page` CSS block in `report.html` handles white background and page numbers. The PDF button in the UI is a plain anchor whose `href` is set to the PDF endpoint URL when a case is opened.

**Tech Stack:** Python 3.12, Flask, WeasyPrint ≥60, system libs installed in Dockerfile

**Important:** Build this **after** the annotations plan is implemented so the PDF automatically includes the Annotated Evidence section via the shared context helper.

---

## Task 1 — Add WeasyPrint dependency

**Context:** WeasyPrint needs Cairo, Pango, and GDK-Pixbuf system libraries. In Docker/Linux these are standard. We add them to the Dockerfile before the pip install step so they are available at wheel build time. `weasyprint>=60.0` is the stable API used here.

**Files:**
- Modify: `requirements.txt`
- Modify: `Dockerfile`

---

### Step 1: Add to `requirements.txt`

Open `requirements.txt` and add on a new line:

```
weasyprint>=60.0
```

---

### Step 2: Update `Dockerfile`

Find the line(s) that run `apt-get` or `pip install` (it should look like `RUN pip install -r requirements.txt` or similar). **Before** the pip install line, add:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
```

---

### Step 3: Verify WeasyPrint installs locally (optional, skip if on Windows)

```bash
pip install "weasyprint>=60.0"
python -c "import weasyprint; print(weasyprint.__version__)"
```

Expected: version number printed, no errors.

---

### Step 4: Commit

```bash
git add requirements.txt Dockerfile
git commit -m "feat(pdf): add weasyprint dependency + Dockerfile system libs"
```

---

## Task 2 — Refactor `get_report()` to shared context helper

**Context:** Currently `get_report()` in `app/routes/reports.py` builds all the template context inline. To avoid duplicating 80+ lines for the PDF endpoint, we extract everything from the `case = ...` lookup through to the `ctx = augment_report_context(...)` call into a standalone `_build_report_context(db, case_id)` function. `get_report()` and the new `get_report_pdf()` both call it.

**Files:**
- Modify: `app/routes/reports.py`
- Modify: `tests/test_reports.py`

---

### Step 1: Write the failing test

In `tests/test_reports.py`, add:

```python
def test_build_report_context_returns_dict(populated_case, client):
    """_build_report_context returns a dict with expected top-level keys."""
    from app.routes.reports import _build_report_context
    from app.database import get_db
    case_id = populated_case  # fixture returns case_id string
    with client.application.app_context():
        db = get_db()
        ctx = _build_report_context(db, case_id)
    for key in ("case", "messages", "contacts", "calls", "analysis",
                "evidence_files", "executive_summary", "conversation_excerpts",
                "stats", "generated_at"):
        assert key in ctx, f"missing key: {key}"
```

Check what `populated_case` returns — if it's the `client` fixture it may need adjusting. Looking at the existing test file, `populated_case` is a fixture that returns a `case_id` string (check the fixture definition and adjust accordingly).

Run: `python -m pytest tests/test_reports.py::test_build_report_context_returns_dict -v`
Expected: **FAIL** — `ImportError: cannot import name '_build_report_context'`

---

### Step 2: Refactor `app/routes/reports.py`

**A. Extract the context builder.** Replace the entire body of `get_report()` (everything from `db = get_db()` through `return render_template(...)`) with a call to a new helper:

```python
def _build_report_context(db, case_id: str) -> dict | None:
    """Build the full Jinja2 context for the case report.

    Returns None if the case does not exist.
    """
    case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not case:
        return None

    case_dict = dict(case)
    try:
        case_dict["device_info"] = json.loads(case_dict.get("device_info") or "{}")
    except Exception:
        case_dict["device_info"] = {}

    messages = db.execute(
        "SELECT platform, direction, sender, recipient, body, timestamp "
        "FROM messages WHERE case_id=? ORDER BY timestamp ASC LIMIT 1000",
        (case_id,),
    ).fetchall()

    contacts = db.execute(
        "SELECT name, phone, email, source_app FROM contacts WHERE case_id=? ORDER BY name ASC",
        (case_id,),
    ).fetchall()

    calls = db.execute(
        "SELECT number, direction, duration_s, timestamp, platform "
        "FROM call_logs WHERE case_id=? ORDER BY timestamp ASC",
        (case_id,),
    ).fetchall()

    analysis_rows = db.execute(
        "SELECT artifact_key, result, provider, created_at "
        "FROM analysis_results WHERE case_id=? ORDER BY created_at ASC",
        (case_id,),
    ).fetchall()

    analysis = []
    for r in analysis_rows:
        row = dict(r)
        row["result_parsed"] = _safe_json_parse(row.get("result") or "", _re)
        analysis.append(row)

    evidence_files = db.execute(
        "SELECT format, source_path, parse_status, parse_error, parsed_at "
        "FROM evidence_files WHERE case_id=? ORDER BY rowid ASC",
        (case_id,),
    ).fetchall()

    # Executive summary
    _summary_parts = []
    for a in analysis:
        p = a.get("result_parsed") or {}
        rsum = p.get("risk_level_summary") or p.get("executive_summary") or p.get("summary")
        if rsum:
            _summary_parts.append(f"**{a['artifact_key'].title()}:** {rsum}")
        elif a.get("result") and not p:
            snippet = str(a["result"])[:300].strip()
            if snippet:
                _summary_parts.append(f"**{a['artifact_key'].title()}:** {snippet}")
    executive_summary = "\n\n".join(_summary_parts)

    # Conversation excerpts
    _EXCERPT_PLATFORMS = ["whatsapp", "telegram", "signal", "sms"]
    _THREADS_PER_PLATFORM = 5
    _MSGS_PER_THREAD = 25
    conversation_excerpts = []
    for platform in _EXCERPT_PLATFORMS:
        thread_rows = db.execute(
            """
            SELECT COALESCE(thread_id, sender, recipient) AS thread,
                   COUNT(*) AS cnt, MAX(timestamp) AS last_ts
            FROM messages
            WHERE case_id=? AND platform=?
            GROUP BY thread ORDER BY cnt DESC LIMIT ?
            """,
            (case_id, platform, _THREADS_PER_PLATFORM),
        ).fetchall()
        if not thread_rows:
            continue
        threads = []
        for tr in thread_rows:
            thread_id = tr["thread"]
            msg_rows = db.execute(
                """
                SELECT direction, sender, recipient, body, timestamp
                FROM messages
                WHERE case_id=? AND platform=?
                  AND COALESCE(thread_id, sender, recipient) = ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (case_id, platform, thread_id, _MSGS_PER_THREAD),
            ).fetchall()
            threads.append({
                "thread_id": thread_id,
                "message_count": tr["cnt"],
                "messages": list(reversed([dict(r) for r in msg_rows])),
            })
        conversation_excerpts.append({"platform": platform, "threads": threads})

    # Per-artifact enhanced stats
    _CONFIDENCE_RE = _re.compile(r'\b(CRITICAL|HIGH|MEDIUM|LOW)\b', _re.IGNORECASE)
    per_artifact_enhanced = []
    for a in analysis:
        p = a.get("result_parsed") or {}
        artifact_key = a["artifact_key"]
        if artifact_key in ("sms", "whatsapp", "telegram", "signal"):
            count_row = db.execute(
                "SELECT COUNT(*) AS cnt FROM messages WHERE case_id=? AND platform=?",
                (case_id, artifact_key),
            ).fetchone()
        elif artifact_key == "call_logs":
            count_row = db.execute(
                "SELECT COUNT(*) AS cnt FROM call_logs WHERE case_id=?", (case_id,)
            ).fetchone()
        elif artifact_key == "contacts":
            count_row = db.execute(
                "SELECT COUNT(*) AS cnt FROM contacts WHERE case_id=?", (case_id,)
            ).fetchone()
        else:
            count_row = None
        record_count = count_row["cnt"] if count_row else 0

        if artifact_key in ("sms", "whatsapp", "telegram", "signal"):
            ts_row = db.execute(
                "SELECT MIN(timestamp) AS ts_min, MAX(timestamp) AS ts_max "
                "FROM messages WHERE case_id=? AND platform=? AND timestamp != ''",
                (case_id, artifact_key),
            ).fetchone()
        elif artifact_key == "call_logs":
            ts_row = db.execute(
                "SELECT MIN(timestamp) AS ts_min, MAX(timestamp) AS ts_max "
                "FROM call_logs WHERE case_id=? AND timestamp != ''",
                (case_id,),
            ).fetchone()
        else:
            ts_row = None
        time_start = (ts_row["ts_min"] or "N/A") if ts_row else "N/A"
        time_end = (ts_row["ts_max"] or "N/A") if ts_row else "N/A"

        result_text = a.get("result") or ""
        explicit_conf = p.get("confidence") or p.get("confidence_level") or ""
        if explicit_conf:
            conf_label = explicit_conf.strip().upper()
        else:
            m = _CONFIDENCE_RE.search(result_text)
            conf_label = m.group(1).upper() if m else "UNSPECIFIED"
        conf_class = {"CRITICAL": "risk-CRITICAL", "HIGH": "risk-HIGH",
                      "MEDIUM": "risk-MEDIUM", "LOW": "risk-LOW"}.get(conf_label, "")

        per_artifact_enhanced.append({
            **a,
            "record_count": record_count,
            "time_start": time_start,
            "time_end": time_end,
            "confidence_label": conf_label,
            "confidence_class": conf_class,
        })

    # Annotations (added in evidence-annotations task; gracefully empty if table missing)
    try:
        annotation_rows = db.execute(
            """
            SELECT a.id, a.tag, a.note, a.created_at,
                   m.platform, m.thread_id, m.body, m.timestamp, m.direction, m.sender
            FROM annotations a
            JOIN messages m ON a.message_id = m.id
            WHERE a.case_id = ?
            ORDER BY
                CASE a.tag WHEN 'KEY_EVIDENCE' THEN 1 WHEN 'SUSPICIOUS' THEN 2
                           WHEN 'ALIBI' THEN 3 WHEN 'EXCULPATORY' THEN 4 ELSE 5 END,
                m.timestamp ASC
            """,
            (case_id,),
        ).fetchall()
        annotations = [dict(r) for r in annotation_rows]
    except Exception:
        annotations = []

    stats = {
        "messages": len(messages),
        "contacts": len(contacts),
        "calls": len(calls),
        "analyses": len(analysis),
    }
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return augment_report_context(
        {
            "case": case_dict,
            "messages": [dict(r) for r in messages],
            "contacts": [dict(r) for r in contacts],
            "calls": [dict(r) for r in calls],
            "analysis": per_artifact_enhanced,
            "evidence_files": [dict(r) for r in evidence_files],
            "executive_summary": executive_summary,
            "conversation_excerpts": conversation_excerpts,
            "annotations": annotations,
            "stats": stats,
            "generated_at": generated_at,
        },
        case_name=case_dict.get("title", ""),
    )
```

**B. Slim down `get_report()` to call the helper:**

```python
@bp_reports.get("/cases/<case_id>/report")
def get_report(case_id: str):
    """Render a court-ready HTML report for the case."""
    db = get_db()
    ctx = _build_report_context(db, case_id)
    if ctx is None:
        return jsonify({"error": "not found"}), 404
    return render_template("report.html", **ctx)
```

---

### Step 3: Run tests

```bash
python -m pytest tests/test_reports.py -v
```

Expected: **all pass** (existing tests + new helper test)

---

### Step 4: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass.

---

### Step 5: Commit

```bash
git add app/routes/reports.py tests/test_reports.py
git commit -m "refactor(report): extract _build_report_context() shared helper"
```

---

## Task 3 — PDF endpoint

**Context:** New `GET /api/cases/<case_id>/report/pdf` endpoint in the same blueprint. Calls `_build_report_context()`, renders the HTML, hands it to WeasyPrint, and returns the PDF bytes. WeasyPrint import is wrapped in a try/except so a missing install gives a clear 500 rather than a cryptic error.

**Files:**
- Modify: `app/routes/reports.py`
- Modify: `tests/test_reports.py`

---

### Step 1: Write the failing test

In `tests/test_reports.py`, add:

```python
def test_pdf_route_returns_pdf(populated_case, client):
    """GET /report/pdf returns 200 with application/pdf content type."""
    pytest.importorskip("weasyprint")   # skip if weasyprint not installed in test env
    case_id = populated_case
    r = client.get(f"/api/cases/{case_id}/report/pdf")
    assert r.status_code == 200
    assert r.content_type == "application/pdf"
    assert b"%PDF" in r.data[:10]


def test_pdf_route_404_for_missing_case(client):
    pytest.importorskip("weasyprint")
    r = client.get("/api/cases/nonexistent/report/pdf")
    assert r.status_code == 404


def test_pdf_content_disposition(populated_case, client):
    pytest.importorskip("weasyprint")
    case_id = populated_case
    r = client.get(f"/api/cases/{case_id}/report/pdf")
    assert r.status_code == 200
    cd = r.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert ".pdf" in cd
```

Run: `python -m pytest tests/test_reports.py::test_pdf_route_returns_pdf -v`
Expected: **FAIL** — 404 (endpoint doesn't exist yet) or SKIP (if weasyprint not installed locally)

---

### Step 2: Add PDF endpoint to `app/routes/reports.py`

Add the import at the top of the file (with the other imports):

```python
from flask import Blueprint, jsonify, render_template, Response, request
```

Add the endpoint after `get_report()`:

```python
@bp_reports.get("/cases/<case_id>/report/pdf")
def get_report_pdf(case_id: str):
    """Render the case report as a downloadable PDF using WeasyPrint."""
    try:
        import weasyprint
    except ImportError:
        return jsonify({"error": "WeasyPrint not available — install it with pip install weasyprint"}), 500

    db = get_db()
    ctx = _build_report_context(db, case_id)
    if ctx is None:
        return jsonify({"error": "not found"}), 404

    html_string = render_template("report.html", **ctx)
    pdf_bytes = weasyprint.HTML(
        string=html_string,
        base_url=request.host_url,
    ).write_pdf()

    safe_title = (ctx["case"].get("title") or case_id)[:50]
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in safe_title)
    filename = f"report-{safe_title}.pdf"

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

---

### Step 3: Run tests

```bash
python -m pytest tests/test_reports.py -v
```

Expected: PDF tests **PASS** (or SKIP if weasyprint not installed in dev), all other tests pass.

---

### Step 4: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass (PDF tests skip gracefully in dev if weasyprint absent).

---

### Step 5: Commit

```bash
git add app/routes/reports.py tests/test_reports.py
git commit -m "feat(pdf): GET /report/pdf endpoint via WeasyPrint"
```

---

## Task 4 — Print CSS in `report.html`

**Context:** WeasyPrint renders the `report.html` template as-is. The dark background (`#0b1018`) needs to become white for print. A `@page` rule adds A4 margins and an auto page-number footer. `page-break-inside: avoid` on `.panel` prevents splitting tables across pages.

**Files:**
- Modify: `templates/report.html`

---

### Step 1: Add print CSS inside the existing `<style>` block in `report.html`

Find the closing `</style>` tag and insert **before** it:

```css
/* ── Print / WeasyPrint ───────────────────────────────────────────────────── */
@media print {
  body {
    background: #ffffff !important;
    color: #000000 !important;
    font-size: 10pt;
  }
  .panel {
    background: #f8f9fa !important;
    border: 1px solid #cccccc !important;
    page-break-inside: avoid;
    margin-bottom: 12pt;
  }
  h1, h2, h3 { color: #000000 !important; page-break-after: avoid; }
  .badge, .risk-badge, .confidence-inline {
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  /* Hide interactive / decorative elements */
  details > summary::marker { display: none; }
  .panel-alt { background: #f0f0f0 !important; }
  table { border-collapse: collapse; }
  th, td { border: 1px solid #cccccc !important; color: #000000 !important; }
  th { background: #e8e8e8 !important; }
  a { color: #000000 !important; text-decoration: none; }
}

@page {
  size: A4;
  margin: 15mm 15mm 20mm 15mm;
  @bottom-center {
    content: "MobileTrace Report — Page " counter(page) " of " counter(pages);
    font-size: 8pt;
    color: #666666;
  }
}
```

---

### Step 2: Verify manually (Docker)

```bash
docker compose up -d --build
# Open http://localhost:5000 → open a case with evidence → click PDF button
# PDF downloads; open in viewer → verify white background, page numbers, content intact
```

---

### Step 3: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass.

---

### Step 4: Commit

```bash
git add templates/report.html
git commit -m "feat(pdf): add @media print and @page CSS to report template"
```

---

## Task 5 — PDF download button in the UI

**Context:** A small "PDF" anchor button is added to the case header row (next to the existing "Report" anchor). Its `href` is set to the PDF endpoint when a case is opened — same pattern as the existing `btn-report` anchor.

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/cases.js`

---

### Step 1: Add button to `templates/index.html`

Find the line containing `<a id="btn-report"` and add the PDF button immediately after it:

```html
<a id="btn-report-pdf" href="#" target="_blank" class="btn-secondary"
   title="Download court-ready PDF" style="display:none">&#128196; PDF</a>
```

---

### Step 2: Wire in `static/js/cases.js`

Find the function `openCase(id)` (or wherever `btn-report`'s `href` is set) and add alongside it:

```javascript
const btnPdf = document.getElementById("btn-report-pdf");
if (btnPdf) {
  btnPdf.href = `/api/cases/${id}/report/pdf`;
  btnPdf.style.display = "";
}
```

---

### Step 3: Manual smoke test

```bash
flask run
# Open a case → PDF button appears in header → click → PDF downloads
```

---

### Step 4: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass.

---

### Step 5: Commit

```bash
git add templates/index.html static/js/cases.js
git commit -m "feat(pdf): PDF download button in case header"
```

---

## Files Changed Summary

| File | Task |
|---|---|
| `requirements.txt` | Task 1 — weasyprint dependency |
| `Dockerfile` | Task 1 — system libs |
| `app/routes/reports.py` | Task 2 (refactor helper) + Task 3 (PDF endpoint) |
| `tests/test_reports.py` | Task 2 + Task 3 — new tests |
| `templates/report.html` | Task 4 — print CSS |
| `templates/index.html` | Task 5 — PDF button |
| `static/js/cases.js` | Task 5 — wire PDF button href |
