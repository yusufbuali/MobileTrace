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
