"""Tests for MobileAnalyzer — mocks the AI provider."""
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app import create_app
from app.database import init_db, close_db


@pytest.fixture
def db_with_data(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    import app.database as _db
    conn = _db.get_db()
    # Insert a case
    conn.execute(
        "INSERT INTO cases (id, title, officer, status) VALUES (?,?,?,?)",
        ("case-001", "Test Case", "Officer A", "open"),
    )
    # Insert messages for different platforms
    for platform in ("sms", "whatsapp", "telegram"):
        conn.execute(
            "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("case-001", platform, "incoming", "+9731234567", "device",
             f"Hello via {platform}", "2026-01-01T10:00:00+00:00", "+9731234567", "{}"),
        )
    # Insert a contact
    conn.execute(
        "INSERT INTO contacts (case_id, name, phone, email, source_app, raw_json) VALUES (?,?,?,?,?,?)",
        ("case-001", "Alice", "+9731234567", "alice@example.com", "android_contacts", "{}"),
    )
    # Insert a call log
    conn.execute(
        "INSERT INTO call_logs (case_id, number, direction, duration_s, timestamp, platform) VALUES (?,?,?,?,?,?)",
        ("case-001", "+9731234567", "incoming", 90, "2026-01-01T10:00:00+00:00", "phone"),
    )
    conn.commit()
    yield conn
    close_db()


def test_analyzer_collects_artifacts(db_with_data):
    from app.analyzer import MobileAnalyzer
    config = {"ai": {"provider": "claude", "claude": {"api_key": "fake", "model": "claude-sonnet-4-6"}}}
    with patch("app.analyzer.create_provider") as mock_factory:
        mock_provider = MagicMock()
        mock_provider.analyze.return_value = "**MEDIUM** — Nothing suspicious found."
        mock_factory.return_value = mock_provider
        analyzer = MobileAnalyzer(config)
        artifacts = analyzer._collect_artifacts("case-001", db_with_data)
    assert "sms" in artifacts
    assert "whatsapp" in artifacts
    assert "telegram" in artifacts
    assert "contacts" in artifacts
    assert "call_logs" in artifacts


def test_analyzer_analyze_case_returns_results(db_with_data):
    from app.analyzer import MobileAnalyzer
    config = {"ai": {"provider": "claude", "claude": {"api_key": "fake", "model": "claude-sonnet-4-6"}}}
    with patch("app.analyzer.create_provider") as mock_factory:
        mock_provider = MagicMock()
        mock_provider.analyze.return_value = "**LOW** — Nothing suspicious."
        mock_factory.return_value = mock_provider
        analyzer = MobileAnalyzer(config)
        results = analyzer.analyze_case("case-001", db_with_data)
    assert len(results) >= 1
    for r in results:
        assert "artifact_key" in r
        assert "result" in r
        assert "provider" in r


def test_analyzer_callback_called(db_with_data):
    from app.analyzer import MobileAnalyzer
    config = {"ai": {"provider": "claude", "claude": {"api_key": "fake", "model": "claude-sonnet-4-6"}}}
    callback_calls = []
    with patch("app.analyzer.create_provider") as mock_factory:
        mock_provider = MagicMock()
        mock_provider.analyze.return_value = "OK"
        mock_factory.return_value = mock_provider
        analyzer = MobileAnalyzer(config)
        analyzer.analyze_case("case-001", db_with_data, callback=lambda k, r: callback_calls.append(k))
    assert len(callback_calls) >= 1


def test_analyzer_provider_error_handled(db_with_data):
    from app.analyzer import MobileAnalyzer
    from app.ai_providers import AIProviderError
    config = {"ai": {"provider": "claude", "claude": {"api_key": "fake", "model": "claude-sonnet-4-6"}}}
    with patch("app.analyzer.create_provider") as mock_factory:
        mock_provider = MagicMock()
        mock_provider.analyze.side_effect = AIProviderError("rate limited")
        mock_factory.return_value = mock_provider
        analyzer = MobileAnalyzer(config)
        results = analyzer.analyze_case("case-001", db_with_data)
    # Should return error results, not raise
    for r in results:
        if "error" in r:
            assert "rate limited" in r["error"]
