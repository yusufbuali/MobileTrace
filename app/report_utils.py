"""Report utilities — Markdown-to-HTML renderer and confidence highlighting.

Ported from AIFT-DEPLOYMENT-2/app/reporter.py.
Provides format_markdown_block() for use as a Jinja2 filter.
"""
from __future__ import annotations

import re
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
