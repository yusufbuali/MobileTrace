# PDF Export for Court Reports — Design

**Date:** 2026-03-21
**Status:** Approved

---

## Overview

Add a `GET /api/cases/<id>/report/pdf` endpoint that renders the existing HTML report template to a downloadable PDF using WeasyPrint. A "Download PDF" button is added to the case header alongside the existing "Report" link. No new template is required — the existing `report.html` is reused with a print-optimised CSS layer.

---

## Architecture

### Backend

**Modified:** `app/routes/reports.py`

New endpoint added to the existing `bp_reports` blueprint:

```
GET /api/cases/<case_id>/report/pdf
```

Logic:
1. Runs identical context-building logic as `get_report()` (extract to shared `_build_report_context(db, case_id)` helper)
2. Renders `report.html` to string via `render_template()`
3. Calls `weasyprint.HTML(string=html, base_url=request.host_url).write_pdf()`
4. Returns `Response(pdf_bytes, mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=case-<id>-report.pdf"})`

**Shared context helper:**
Extract the existing `get_report()` body into `_build_report_context(db, case_id) -> dict`. Both the HTML route and the new PDF route call this helper.

---

### Dependencies

**`requirements.txt`:**
```
weasyprint>=60.0
```

**`Dockerfile`** — add before pip install:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libffi-dev shared-mime-info fonts-liberation \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
```

---

### Print CSS

Added inside `report.html`'s `<style>` block:

```css
@media print {
  body { background: #ffffff !important; color: #000000 !important; }
  .panel { background: #f8f8f8 !important; border: 1px solid #ccc !important; }
  .badge, .risk-badge { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  /* page breaks */
  .panel { page-break-inside: avoid; }
  h2 { page-break-after: avoid; }
  /* hide interactive elements */
  details > summary::marker { display: none; }
}
@page {
  size: A4;
  margin: 15mm 15mm 20mm 15mm;
  @bottom-center { content: "Case Report — Page " counter(page) " of " counter(pages); font-size: 9pt; color: #666; }
}
```

---

### Frontend

**`templates/index.html`** — in the case action buttons row, add next to the "Report" anchor:

```html
<a id="btn-report-pdf" href="#" class="btn-secondary" title="Download PDF">&#128196; PDF</a>
```

**`static/js/cases.js`** — update the anchor's `href` when a case is opened:
```javascript
dom("btn-report-pdf").href = `/api/cases/${id}/report/pdf`;
```

---

## Error Handling

- Case not found → 404
- WeasyPrint import error (not installed) → 500 with JSON `{"error": "WeasyPrint not available"}` — won't happen in Docker but provides a clear message in dev
- Rendering error → 500 with error detail logged server-side

---

## Testing

WeasyPrint rendering is an integration-level concern. Tests:
- `tests/test_reports.py` — add `test_pdf_route_returns_200_and_pdf_mimetype`: call `GET /report/pdf` on a case with data, assert `200` and `Content-Type: application/pdf`
- Assert `Content-Disposition` header contains `filename=`

No visual/layout regression tests — WeasyPrint output is validated manually.

---

## Build Order Note

PDF export benefits from being built **after** annotations (so annotated messages appear in the PDF report automatically via the shared `_build_report_context()` helper).

---

## Files Changed

| File | Type |
|---|---|
| `app/routes/reports.py` | Modified — `_build_report_context()` helper + PDF endpoint |
| `templates/report.html` | Modified — `@media print` + `@page` CSS |
| `requirements.txt` | Modified — add weasyprint |
| `Dockerfile` | Modified — system libs for WeasyPrint |
| `templates/index.html` | Modified — PDF download button |
| `static/js/cases.js` | Modified — wire PDF button href |
| `tests/test_reports.py` | Modified — PDF route smoke test |
