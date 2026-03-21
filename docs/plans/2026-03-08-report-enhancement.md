# Report Enhancement — AIFT-Style Deep Rendering

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Elevate MobileTrace's HTML report to match AIFT-DEPLOYMENT-2's forensic-grade output by adding full Markdown rendering, chat conversation excerpts (bubble UI), executive summary, evidence files section, and AIFT-style confidence pills on per-artifact cards.

**Architecture:** All rendering logic lives in a new `app/report_utils.py` utility module (ported from AIFT's `reporter.py`). The Jinja filter `format_markdown_block` is registered in `create_app()`. The report route (`routes/reports.py`) is enhanced to compute four new context variables. `templates/report.html` gains four new sections and updates existing ones.

**Tech Stack:** Python 3.12, Flask/Jinja2, sqlite3 (stdlib), pytest

---

## Task 1 — Markdown renderer utility + Jinja filter

**Context:** AIFT-DEPLOYMENT-2 ships a `_markdown_to_html()` function inside `reporter.py` that converts full Markdown (headings h1–h6, bold/italic/inline-code, fenced code blocks, ordered and unordered lists, tables, paragraphs) to safe HTML. It also highlights `CRITICAL/HIGH/MEDIUM/LOW` tokens in text with colour-coded `<span>` tags. MobileTrace currently renders LLM output as raw plain text — any Markdown the model returns shows as `## Heading` literal text. This task ports that function as a standalone utility and registers it as a Jinja filter so every template can call `{{ value | format_markdown_block }}`.

**Files:**
- Create: `app/report_utils.py`
- Modify: `app/__init__.py`
- Modify: `tests/test_report_utils.py` (new file)

### Step 1: Write the failing tests

Create `tests/test_report_utils.py`:

```python
"""Tests for report_utils: markdown renderer and confidence highlighting."""
import pytest
from app.report_utils import format_markdown_block, _markdown_to_html


def test_heading_h2():
    html = _markdown_to_html("## Summary")
    assert "<h2>Summary</h2>" in html


def test_bold():
    html = _markdown_to_html("**important**")
    assert "<strong>important</strong>" in html


def test_unordered_list():
    html = _markdown_to_html("- item one\n- item two")
    assert "<ul>" in html
    assert "<li>item one</li>" in html


def test_ordered_list():
    html = _markdown_to_html("1. first\n2. second")
    assert "<ol>" in html
    assert "<li>first</li>" in html


def test_code_fence():
    html = _markdown_to_html("```\ncode here\n```")
    assert "<pre><code>" in html
    assert "code here" in html


def test_inline_code():
    html = _markdown_to_html("use `SELECT *` statement")
    assert "<code>SELECT *</code>" in html


def test_table():
    md = "| Col A | Col B |\n|---|---|\n| v1 | v2 |"
    html = _markdown_to_html(md)
    assert "<table>" in html
    assert "<th>" in html
    assert "v1" in html


def test_confidence_highlight():
    html = _markdown_to_html("Risk is HIGH and severity is CRITICAL")
    assert 'confidence-high' in html
    assert 'confidence-critical' in html


def test_empty_returns_na():
    result = format_markdown_block("")
    assert "N/A" in result


def test_paragraph():
    html = _markdown_to_html("This is a paragraph.")
    assert "<p>This is a paragraph.</p>" in html
```

Run: `python -m pytest tests/test_report_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.report_utils'`

### Step 2: Create `app/report_utils.py`

Port AIFT's markdown engine as a standalone module:

```python
"""Report utilities — Markdown-to-HTML renderer and confidence highlighting.

Ported from AIFT-DEPLOYMENT-2/app/reporter.py.
Provides format_markdown_block() for use as a Jinja2 filter.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


# Confidence token patterns (CRITICAL/HIGH/MEDIUM/LOW)
_CONFIDENCE_PATTERN = re.compile(r"\b(CRITICAL|HIGH|MEDIUM|LOW)\b", re.IGNORECASE)
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_MARKDOWN_OL = re.compile(r"^\d+\.\s+(.*)$")
_MARKDOWN_UL = re.compile(r"^[-*]\s+(.*)$")
_MARKDOWN_BOLD_STAR = re.compile(r"\*\*(.+?)\*\*")
_MARKDOWN_BOLD_US = re.compile(r"__(.+?)__")
_MARKDOWN_ITALIC_STAR = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_MARKDOWN_ITALIC_US = re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_MARKDOWN_TABLE_SEP = re.compile(r"^:?-{3,}:?$")

_CONFIDENCE_CLASS = {
    "CRITICAL": "confidence-critical",
    "HIGH": "confidence-high",
    "MEDIUM": "confidence-medium",
    "LOW": "confidence-low",
}


def _escape(text: str) -> str:
    """HTML-escape a string."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _highlight_confidence(text: str) -> str:
    def _replace(m: re.Match) -> str:
        token = m.group(1).upper()
        cls = _CONFIDENCE_CLASS.get(token, "confidence-unknown")
        return f'<span class="confidence-inline {cls}">{token}</span>'
    return _CONFIDENCE_PATTERN.sub(_replace, text)


def _render_inline(value: str) -> str:
    source = str(value or "")
    if not source:
        return ""
    parts = re.split(r"(`[^`\n]*`)", source)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{_escape(part[1:-1])}</code>")
            continue
        escaped = _escape(part)
        escaped = _MARKDOWN_BOLD_STAR.sub(r"<strong>\1</strong>", escaped)
        escaped = _MARKDOWN_BOLD_US.sub(r"<strong>\1</strong>", escaped)
        escaped = _MARKDOWN_ITALIC_STAR.sub(r"<em>\1</em>", escaped)
        escaped = _MARKDOWN_ITALIC_US.sub(r"<em>\1</em>", escaped)
        escaped = _highlight_confidence(escaped)
        out.append(escaped)
    return "".join(out)


def _split_table_row(line: str) -> list[str]:
    t = line.strip()
    if "|" not in t:
        return []
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|"):
        t = t[:-1]
    return [c.strip() for c in t.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(_MARKDOWN_TABLE_SEP.match(c) for c in cells)


def _render_table(header: list[str], body_rows: list[list[str]]) -> str:
    th = "".join(f"<th>{_render_inline(c)}</th>" for c in header)
    rows_html = ""
    for row in body_rows:
        td = "".join(f"<td>{_render_inline(c)}</td>" for c in row)
        rows_html += f"<tr>{td}</tr>"
    body = f"<tbody>{rows_html}</tbody>" if body_rows else ""
    return f"<table><thead><tr>{th}</tr></thead>{body}</table>"


def _markdown_to_html(value: str) -> str:
    """Convert Markdown text to HTML. Safe for embedding in reports."""
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    para: list[str] = []
    list_items: list[str] = []
    list_type = ""
    in_fence = False
    fence_lines: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if not para:
            return
        rendered = _render_inline("\n".join(para)).replace("\n", "<br>\n")
        blocks.append(f"<p>{rendered}</p>")
        para = []

    def flush_list() -> None:
        nonlocal list_items, list_type
        if not list_items or not list_type:
            list_items = []
            list_type = ""
            return
        items = "".join(f"<li>{item}</li>" for item in list_items)
        blocks.append(f"<{list_type}>{items}</{list_type}>")
        list_items = []
        list_type = ""

    def flush_fence() -> None:
        nonlocal fence_lines
        code = _escape("\n".join(fence_lines))
        blocks.append(f"<pre><code>{code}</code></pre>")
        fence_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if in_fence:
            if stripped.startswith("```"):
                in_fence = False
                flush_fence()
            else:
                fence_lines.append(line)
            i += 1
            continue

        if stripped.startswith("```"):
            flush_para()
            flush_list()
            in_fence = True
            fence_lines = []
            i += 1
            continue

        if not stripped:
            flush_para()
            flush_list()
            i += 1
            continue

        # Table detection
        header_cells = _split_table_row(line)
        if header_cells and i + 1 < len(lines):
            sep_cells = _split_table_row(lines[i + 1])
            if sep_cells and len(header_cells) == len(sep_cells) and _is_separator_row(sep_cells):
                flush_para()
                flush_list()
                n = len(header_cells)
                body_rows: list[list[str]] = []
                i += 2
                while i < len(lines):
                    bl = lines[i].strip()
                    if not bl:
                        break
                    rc = _split_table_row(lines[i])
                    if not rc:
                        break
                    # normalise row length
                    row = (rc + [""] * n)[:n]
                    body_rows.append(row)
                    i += 1
                blocks.append(_render_table(header_cells, body_rows))
                continue

        # Headings
        hm = _MARKDOWN_HEADING.match(stripped)
        if hm:
            flush_para()
            flush_list()
            lvl = len(hm.group(1))
            blocks.append(f"<h{lvl}>{_render_inline(hm.group(2))}</h{lvl}>")
            i += 1
            continue

        # Ordered list
        om = _MARKDOWN_OL.match(stripped)
        if om:
            flush_para()
            if list_type != "ol":
                flush_list()
                list_type = "ol"
            list_items.append(_render_inline(om.group(1)))
            i += 1
            continue

        # Unordered list
        um = _MARKDOWN_UL.match(stripped)
        if um:
            flush_para()
            if list_type != "ul":
                flush_list()
                list_type = "ul"
            list_items.append(_render_inline(um.group(1)))
            i += 1
            continue

        flush_list()
        para.append(stripped)
        i += 1

    if in_fence:
        flush_fence()
    flush_para()
    flush_list()

    return "\n".join(blocks)


def format_markdown_block(value: Any) -> str:
    """Jinja2 filter: render Markdown to HTML. Returns N/A span if empty."""
    text = str(value or "").strip()
    if not text:
        return '<span class="empty-value">N/A</span>'
    return _markdown_to_html(text)
```

### Step 3: Register the Jinja filter in `app/__init__.py`

Add after `app = Flask(...)` in `create_app()`:

```python
from .report_utils import format_markdown_block
app.jinja_env.filters["format_markdown_block"] = format_markdown_block
```

### Step 4: Run tests

```bash
python -m pytest tests/test_report_utils.py -v
```
Expected: all 10 pass.

### Step 5: Commit

```bash
git add app/report_utils.py app/__init__.py tests/test_report_utils.py
git commit -m "feat(report): add AIFT-style markdown renderer as Jinja filter"
```

---

## Task 2 — Evidence Files section in report

**Context:** When evidence is uploaded, MobileTrace stores rows in `evidence_files` (columns: `id, case_id, format, source_path, parse_status, parse_error, parsed_at`). The current report does not show these. AIFT's report includes a full Evidence Summary panel showing what file was processed.

**Files:**
- Modify: `app/routes/reports.py`
- Modify: `templates/report.html`

### Step 1: Modify `get_report()` in `routes/reports.py`

Add query for evidence files after the existing queries (before building `ctx`):

```python
evidence_files = db.execute(
    "SELECT format, source_path, parse_status, parse_error, parsed_at "
    "FROM evidence_files WHERE case_id=? ORDER BY rowid ASC",
    (case_id,),
).fetchall()
```

Add to `ctx`:
```python
"evidence_files": [dict(r) for r in evidence_files],
```

### Step 2: Add Evidence Files section to `report.html`

After the Case Information panel, add:

```html
<!-- ── Evidence Files ──────────────────────────────────────────────────────── -->
{% if evidence_files %}
<div class="panel">
  <h2>Evidence Files</h2>
  <table class="data-table">
    <thead>
      <tr><th>Format</th><th>Source</th><th>Status</th><th>Parsed At</th></tr>
    </thead>
    <tbody>
    {% for ev in evidence_files %}
      <tr>
        <td><span class="badge badge-{{ ev.format or 'unknown' }}">{{ ev.format or '—' }}</span></td>
        <td class="mono" style="word-break:break-all;font-size:0.75rem">{{ ev.source_path or '—' }}</td>
        <td>
          {% if ev.parse_status == 'done' %}
            <span class="badge" style="background:#0d2e1b;color:#22c55e">done</span>
          {% elif ev.parse_status == 'error' %}
            <span class="badge" style="background:#2d0a0a;color:#f04438" title="{{ ev.parse_error or '' }}">error</span>
          {% else %}
            <span class="badge" style="background:#1a1f2e;color:#9fb1c7">{{ ev.parse_status or '—' }}</span>
          {% endif %}
        </td>
        <td class="mono">{{ ev.parsed_at or '—' }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}
```

### Step 3: Run existing tests (no new tests needed — route change is additive)

```bash
python -m pytest tests/ -v
```
Expected: all existing tests pass.

### Step 4: Commit

```bash
git add app/routes/reports.py templates/report.html
git commit -m "feat(report): add Evidence Files section to report"
```

---

## Task 3 — Executive Summary section

**Context:** AIFT extracts an `executive_summary` field from analysis results. MobileTrace's LLM prompts return JSON that may include a `risk_level_summary` or top-level analysis text. This task synthesises a single Executive Summary panel at the top of the report by: (1) collecting the `risk_level_summary` from each parsed analysis result; (2) falling back to the raw result text for non-JSON responses. The summary is rendered using `format_markdown_block`.

**Files:**
- Modify: `app/routes/reports.py`
- Modify: `templates/report.html`

### Step 1: Add `executive_summary` builder to `get_report()`

After building `analysis`, add:

```python
# Build executive summary from analysis results
_summary_parts = []
for a in analysis:
    p = a.get("result_parsed") or {}
    rsum = p.get("risk_level_summary") or p.get("executive_summary") or p.get("summary")
    if rsum:
        _summary_parts.append(f"**{a['artifact_key'].title()}:** {rsum}")
    elif a.get("result") and not p:
        # Non-JSON result — use first 300 chars
        snippet = str(a["result"])[:300].strip()
        if snippet:
            _summary_parts.append(f"**{a['artifact_key'].title()}:** {snippet}")
executive_summary = "\n\n".join(_summary_parts)
```

Add to `ctx`:
```python
"executive_summary": executive_summary,
```

### Step 2: Add Executive Summary section to `report.html`

Add **before** the AI Analysis Results panel (after Evidence Files panel):

```html
<!-- ── Executive Summary ───────────────────────────────────────────────────── -->
{% if executive_summary %}
<div class="panel">
  <h2>Executive Summary</h2>
  <div class="panel-alt markdown-output">
    {{ executive_summary | format_markdown_block | safe }}
  </div>
</div>
{% endif %}
```

Also add the CSS class `markdown-output` styling in the `<style>` block (already partially present as `.findings-block`). Add if not present:

```css
/* ── Markdown output ──────────────────────────────────────────── */
.markdown-output { font-size: 0.85rem; line-height: 1.65; }
.markdown-output h1, .markdown-output h2, .markdown-output h3,
.markdown-output h4, .markdown-output h5, .markdown-output h6 { margin: 10px 0 6px; color: #f4f8ff; }
.markdown-output p { margin: 0 0 8px; }
.markdown-output ul, .markdown-output ol { margin: 0 0 8px; padding-left: 20px; }
.markdown-output li { margin: 0 0 3px; }
.markdown-output code { font-family: 'Consolas', monospace; font-size: 0.88em;
  background: rgba(11,16,24,0.75); border: 1px solid rgba(159,177,199,0.25);
  border-radius: 4px; padding: 1px 5px; }
.markdown-output pre { margin: 0 0 8px; padding: 10px; overflow-x: auto;
  border: 1px solid rgba(159,177,199,0.25); border-radius: 8px;
  background: rgba(11,16,24,0.85); }
.markdown-output pre code { border: 0; padding: 0; background: transparent; }
.markdown-output table { width: 100%; border-collapse: collapse; margin: 0 0 8px; }
.markdown-output th, .markdown-output td { border: 1px solid rgba(159,177,199,0.25);
  padding: 7px 9px; text-align: left; vertical-align: top; }
.markdown-output th { background: rgba(255,255,255,0.04); color: #e9f0ff; font-weight: 600; }
.confidence-inline { padding: 1px 5px; border-radius: 4px; font-weight: 700;
  font-size: 0.88em; margin: 0 2px; }
.confidence-critical { color: #fff1f0; background: #ef4444; }
.confidence-high { color: #2f0d04; background: #ffb38f; }
.confidence-medium { color: #302600; background: #ffe47a; }
.confidence-low { color: #021a35; background: #9ec9ff; }
.confidence-unknown { color: #132234; background: #cbd5e1; }
```

### Step 3: Run tests

```bash
python -m pytest tests/ -v
```
Expected: all pass.

### Step 4: Commit

```bash
git add app/routes/reports.py templates/report.html
git commit -m "feat(report): add Executive Summary section with markdown rendering"
```

---

## Task 4 — Chat Conversation Excerpts (bubble UI)

**Context:** AIFT renders actual chat bubbles in its report — grouped by artifact (platform), then by thread, showing the last 25 messages of the top 5 threads per platform. This makes the report evidence-rich and self-contained. MobileTrace's current report has a flat 1000-message table with no threading or visual grouping. This task adds a conversation excerpts section ABOVE the flat messages table, using CSS chat bubbles (sent = right, received = left) exactly matching AIFT's report_template.html style.

**Files:**
- Modify: `app/routes/reports.py`
- Modify: `templates/report.html`

### Step 1: Add `conversation_excerpts` builder to `get_report()`

Replace the existing messages query with a more comprehensive one, and add the thread grouping logic. Add **after** the calls query:

```python
# Build conversation excerpts: top 5 threads per platform, last 25 messages each
_EXCERPT_PLATFORMS = ["whatsapp", "telegram", "signal", "sms"]
_THREADS_PER_PLATFORM = 5
_MSGS_PER_THREAD = 25

conversation_excerpts = []
for platform in _EXCERPT_PLATFORMS:
    # Find top threads by message count
    thread_rows = db.execute(
        """
        SELECT COALESCE(thread_id, sender, recipient) AS thread,
               COUNT(*) AS cnt,
               MAX(timestamp) AS last_ts
        FROM messages
        WHERE case_id=? AND platform=?
        GROUP BY thread
        ORDER BY cnt DESC
        LIMIT ?
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
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (case_id, platform, thread_id, _MSGS_PER_THREAD),
        ).fetchall()
        msgs_reversed = list(reversed([dict(r) for r in msg_rows]))
        threads.append({
            "thread_id": thread_id,
            "message_count": tr["cnt"],
            "messages": msgs_reversed,
        })
    conversation_excerpts.append({
        "platform": platform,
        "threads": threads,
    })
```

Add to `ctx`:
```python
"conversation_excerpts": conversation_excerpts,
```

### Step 2: Add Conversation Excerpts section to `report.html`

Add CSS for chat bubbles inside `<style>` (before closing `</style>`):

```css
/* ── Chat bubbles ─────────────────────────────────────────────── */
.chat-thread { border: 1px solid rgba(159,177,199,0.2); border-radius:10px;
  background: var(--panel-alt); margin-bottom:10px; overflow:hidden; }
.chat-thread-header { display:flex; justify-content:space-between; align-items:center;
  padding:10px 14px; background:rgba(255,255,255,0.02);
  border-bottom:1px solid rgba(159,177,199,0.15); }
.chat-title { font-weight:600; font-size:0.92rem; }
.chat-meta { font-size:0.78rem; color:var(--muted); }
.chat-messages { padding:10px 14px; display:flex; flex-direction:column; gap:6px; }
.msg-bubble { max-width:72%; padding:7px 12px; border-radius:10px;
  font-size:0.85rem; line-height:1.45; word-break:break-word; }
.msg-sent { align-self:flex-end; background:#1a3a5c;
  border:1px solid rgba(87,179,255,0.25); border-bottom-right-radius:3px; }
.msg-received { align-self:flex-start; background:rgba(255,255,255,0.04);
  border:1px solid rgba(159,177,199,0.18); border-bottom-left-radius:3px; }
.msg-sender { font-weight:600; font-size:0.75rem; margin-bottom:2px; color:var(--accent); }
.msg-time { font-size:0.7rem; color:var(--muted); margin-top:3px; }
.platform-section-title { font-size:0.75rem; font-weight:700; text-transform:uppercase;
  letter-spacing:0.06em; color:var(--muted); margin:14px 0 8px; }
```

Add conversation excerpts section **after the Executive Summary panel** and **before the AI Analysis panel**:

```html
<!-- ── Conversation Excerpts ──────────────────────────────────────────────── -->
{% if conversation_excerpts %}
<div class="panel">
  <h2>Conversation Excerpts</h2>
  <p style="color:var(--muted);font-size:0.82rem;margin:0 0 14px">
    Top {{ _THREADS_PER_PLATFORM }} threads per platform, last {{ _MSGS_PER_THREAD }} messages each.
  </p>
  {% for platform_block in conversation_excerpts %}
    <div class="platform-section-title">
      <span class="badge badge-{{ platform_block.platform }}">{{ platform_block.platform }}</span>
    </div>
    {% for thread in platform_block.threads %}
      <details class="chat-thread" {% if loop.first %}open{% endif %}>
        <summary class="chat-thread-header">
          <span class="chat-title mono" style="font-size:0.82rem">{{ thread.thread_id }}</span>
          <span class="chat-meta">{{ thread.message_count }} messages total</span>
        </summary>
        <div class="chat-messages">
          {% for msg in thread.messages %}
            <div class="msg-bubble {{ 'msg-sent' if msg.direction == 'outgoing' else 'msg-received' }}">
              {% if msg.direction == 'incoming' and msg.sender and msg.sender != 'device' %}
                <div class="msg-sender">{{ msg.sender }}</div>
              {% endif %}
              {{ msg.body or '[no body]' }}
              <div class="msg-time">{{ msg.timestamp or '' }}</div>
            </div>
          {% endfor %}
        </div>
      </details>
    {% endfor %}
  {% endfor %}
</div>
{% endif %}
```

Note: The template variables `_THREADS_PER_PLATFORM` and `_MSGS_PER_THREAD` shown in the `<p>` tag should be hardcoded as their literal values (`5` and `25`) since Jinja doesn't see Python constants:

```html
<p style="color:var(--muted);font-size:0.82rem;margin:0 0 14px">
  Top 5 threads per platform, last 25 messages each.
</p>
```

### Step 3: Run tests

```bash
python -m pytest tests/ -v
```
Expected: all pass.

### Step 4: Commit

```bash
git add app/routes/reports.py templates/report.html
git commit -m "feat(report): add chat conversation excerpts with bubble UI"
```

---

## Task 5 — Enhanced Per-Artifact with confidence pills + markdown

**Context:** The existing AI Analysis Results section renders structured JSON (risk badges, thread cards, key_findings) but the main analysis body is shown as raw LLM text in a `<pre>` block. This task: (1) renders the analysis body through `format_markdown_block` so Markdown headings/lists/tables display properly; (2) adds AIFT-style confidence pills (`CRITICAL/HIGH/MEDIUM/LOW`) derived from the CONFIDENCE_PATTERN matching in `report_utils`; (3) adds a `per_artifact_enhanced` context variable with record counts and time ranges computed from the DB.

**Files:**
- Modify: `app/routes/reports.py`
- Modify: `templates/report.html`

### Step 1: Add `per_artifact_enhanced` to `get_report()`

Add after `analysis` is built:

```python
# Compute per-artifact DB stats for enhanced display
_CONFIDENCE_RE = __import__('re').compile(
    r'\b(CRITICAL|HIGH|MEDIUM|LOW)\b', __import__('re').IGNORECASE
)
per_artifact_enhanced = []
for a in analysis:
    p = a.get("result_parsed") or {}
    artifact_key = a["artifact_key"]

    # Record count from DB
    if artifact_key in ("sms", "whatsapp", "telegram", "signal"):
        count_row = db.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE case_id=? AND platform=?",
            (case_id, artifact_key),
        ).fetchone()
        record_count = count_row["cnt"] if count_row else 0
    elif artifact_key == "call_logs":
        count_row = db.execute(
            "SELECT COUNT(*) AS cnt FROM call_logs WHERE case_id=?", (case_id,)
        ).fetchone()
        record_count = count_row["cnt"] if count_row else 0
    elif artifact_key == "contacts":
        count_row = db.execute(
            "SELECT COUNT(*) AS cnt FROM contacts WHERE case_id=?", (case_id,)
        ).fetchone()
        record_count = count_row["cnt"] if count_row else 0
    else:
        record_count = 0

    # Time range from DB
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

    # Confidence from explicit field or pattern match in result text
    explicit_conf = p.get("confidence") or p.get("confidence_level") or ""
    result_text = a.get("result") or ""
    if explicit_conf:
        conf_label = explicit_conf.strip().upper()
    else:
        m = _CONFIDENCE_RE.search(result_text)
        conf_label = m.group(1).upper() if m else "UNSPECIFIED"
    conf_class_map = {
        "CRITICAL": "risk-CRITICAL", "HIGH": "risk-HIGH",
        "MEDIUM": "risk-MEDIUM", "LOW": "risk-LOW",
    }
    conf_class = conf_class_map.get(conf_label, "")

    per_artifact_enhanced.append({
        **a,
        "record_count": record_count,
        "time_start": time_start,
        "time_end": time_end,
        "confidence_label": conf_label,
        "confidence_class": conf_class,
    })
```

Replace `"analysis": [dict(r) for r in analysis]` in `ctx` with:
```python
"analysis": per_artifact_enhanced,
```

### Step 2: Update the AI Analysis section in `report.html`

Replace the fallback `<pre class="json-raw">{{ a.result }}</pre>` block with:

```html
{% else %}
  <div class="panel-alt markdown-output" style="padding:12px 14px">
    {{ a.result | format_markdown_block | safe }}
  </div>
{% endif %}
```

Add record count + time range metadata to the analysis-card summary in the existing template. After the opening `<details class="analysis-card" open>` summary line, inside `<div class="analysis-body">`, add before the risk-summary-banner block:

```html
<div style="display:flex;gap:16px;margin-bottom:12px;font-size:0.78rem;color:var(--muted)">
  <span>&#128203; <strong style="color:var(--text)">{{ a.record_count }}</strong> records</span>
  {% if a.time_start != 'N/A' %}
  <span>&#128197; {{ a.time_start[:10] if a.time_start|length > 10 else a.time_start }}
    &rarr; {{ a.time_end[:10] if a.time_end|length > 10 else a.time_end }}</span>
  {% endif %}
</div>
```

Also replace the summary risk-badge with the confidence-label from the enhanced data.
Find and replace the existing badge line in the summary:

```html
{# OLD — inside summary #}
{% set lvl = p.get('risk_level_summary', p.get('risk_level', p.get('confidence_level', ''))) %}
{% set lvl_word = lvl.split()[0].upper() if lvl else '' %}
{% if lvl_word in ['HIGH','CRITICAL','MEDIUM','LOW'] %}
<span class="risk-badge risk-{{ lvl_word }}">{{ lvl_word }}</span>
{% endif %}
```

Replace with:

```html
{% if a.confidence_label and a.confidence_label != 'UNSPECIFIED' %}
<span class="risk-badge risk-{{ a.confidence_label }}">{{ a.confidence_label }}</span>
{% endif %}
```

### Step 3: Run tests

```bash
python -m pytest tests/ -v
```
Expected: all pass.

### Step 4: Commit

```bash
git add app/routes/reports.py templates/report.html
git commit -m "feat(report): enhanced per-artifact cards with markdown, confidence pills, DB stats"
```

---

## Files Changed Summary

| File | Task |
|---|---|
| `app/report_utils.py` | Task 1 (new — markdown renderer + Jinja filter) |
| `app/__init__.py` | Task 1 (register filter) |
| `tests/test_report_utils.py` | Task 1 (new — tests) |
| `app/routes/reports.py` | Tasks 2, 3, 4, 5 |
| `templates/report.html` | Tasks 2, 3, 4, 5 |
