"""Arabic and RTL text support for forensic reports.

Provides utilities for handling right-to-left text in reports,
including bidirectional text detection, CSS injection for RTL
layouts, and Arabic text normalization.
"""

from __future__ import annotations

import re
from typing import Any

# Unicode ranges for Arabic, Hebrew, and other RTL scripts
_RTL_CHAR_RANGES = [
    (0x0590, 0x05FF),   # Hebrew
    (0x0600, 0x06FF),   # Arabic
    (0x0700, 0x074F),   # Syriac
    (0x0750, 0x077F),   # Arabic Supplement
    (0x0780, 0x07BF),   # Thaana
    (0x08A0, 0x08FF),   # Arabic Extended-A
    (0xFB50, 0xFDFF),   # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),   # Arabic Presentation Forms-B
]

# CSS to inject for RTL support
RTL_CSS = """
/* Arabic RTL Support */
[dir="rtl"], .rtl {
    direction: rtl;
    text-align: right;
    font-family: 'Segoe UI', 'Arial', 'Tahoma', 'Noto Sans Arabic', sans-serif;
}
[dir="rtl"] table {
    direction: rtl;
}
[dir="rtl"] th, [dir="rtl"] td {
    text-align: right;
}
/* Bidirectional text */
.bidi {
    unicode-bidi: embed;
}
/* Keep LTR content in RTL context */
.ltr-inline {
    direction: ltr;
    unicode-bidi: embed;
    display: inline-block;
}
/* Evidence hashes, IPs, paths should stay LTR */
.evidence-hash, .ip-address, .file-path, code, pre {
    direction: ltr;
    unicode-bidi: embed;
    text-align: left;
}
"""


def is_rtl_text(text: str, threshold: float = 0.3) -> bool:
    """Detect if text is predominantly right-to-left.

    Args:
        text: Text to analyze.
        threshold: Fraction of RTL characters needed to classify as RTL.

    Returns:
        True if the text contains enough RTL characters.
    """
    if not text:
        return False

    total_alpha = 0
    rtl_count = 0

    for char in text:
        code = ord(char)
        if char.isalpha():
            total_alpha += 1
            for start, end in _RTL_CHAR_RANGES:
                if start <= code <= end:
                    rtl_count += 1
                    break

    if total_alpha == 0:
        return False

    return (rtl_count / total_alpha) >= threshold


def detect_report_direction(
    investigation_context: str = "",
    case_name: str = "",
) -> str:
    """Detect the appropriate text direction for a report.

    Returns 'rtl' or 'ltr'.
    """
    combined = f"{investigation_context} {case_name}"
    return "rtl" if is_rtl_text(combined) else "ltr"


def wrap_rtl_text(text: str) -> str:
    """Wrap text with appropriate directional markers.

    Adds Unicode bidi markers around RTL text segments within
    mixed LTR/RTL content.
    """
    if not text:
        return text

    if is_rtl_text(text):
        # Right-to-Left Embedding + Pop Directional Formatting
        return f"\u202B{text}\u202C"
    return text


def inject_rtl_css(html_content: str, direction: str = "rtl") -> str:
    """Inject RTL CSS into an HTML report.

    Adds the RTL stylesheet and sets the dir attribute on the html element.
    """
    if direction != "rtl":
        return html_content

    # Add dir="rtl" to <html> tag
    html_content = re.sub(
        r"<html([^>]*)>",
        f'<html\\1 dir="rtl">',
        html_content,
        count=1,
    )

    # Inject RTL CSS before </head>
    css_block = f"<style>{RTL_CSS}</style>"
    if "</head>" in html_content:
        html_content = html_content.replace("</head>", f"{css_block}\n</head>", 1)

    return html_content


def augment_report_context(
    render_context: dict[str, Any],
    investigation_context: str = "",
    case_name: str = "",
) -> dict[str, Any]:
    """Add RTL-related fields to the report render context.

    Call this before rendering the report template.
    """
    context = dict(render_context)
    direction = detect_report_direction(investigation_context, case_name)
    context["text_direction"] = direction
    context["is_rtl"] = direction == "rtl"
    context["rtl_css"] = RTL_CSS if direction == "rtl" else ""
    return context
