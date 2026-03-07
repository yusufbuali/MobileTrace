"""Tests for analysis trigger, SSE stream, and results retrieval."""
import json
from unittest.mock import MagicMock, patch
import pytest

from app import create_app
from app.database import init_db, close_db


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


@pytest.fixture
def case_with_messages(client):
    """Create a case and insert messages into the DB."""
    r = client.post("/api/cases", json={"title": "Analyze Me", "officer": "X"})
    case_id = r.get_json()["id"]

    import app.database as _db
    db = _db.get_db()
    for platform in ("sms", "whatsapp"):
        db.execute(
            "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (case_id, platform, "incoming", "+9731234567", "device",
             f"Hello via {platform}", "2026-01-01T10:00:00+00:00", "+9731234567", "{}"),
        )
    db.commit()
    return case_id


def test_trigger_analysis_starts(client, case_with_messages):
    """POST /api/cases/<id>/analyze returns 202 with job info."""
    with patch("app.routes.analysis.MobileAnalyzer") as MockAnalyzer:
        mock_instance = MagicMock()
        mock_instance.analyze_case.return_value = [
            {"artifact_key": "sms", "result": "LOW — no concerns.", "provider": "claude"},
        ]
        MockAnalyzer.return_value = mock_instance

        resp = client.post(f"/api/cases/{case_with_messages}/analyze")
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["case_id"] == case_with_messages
    assert data["status"] == "started"


def test_trigger_analysis_case_not_found(client):
    resp = client.post("/api/cases/nonexistent/analyze")
    assert resp.status_code == 404


def test_get_analysis_results_empty(client, case_with_messages):
    """GET /api/cases/<id>/analysis returns empty list when no analysis run."""
    resp = client.get(f"/api/cases/{case_with_messages}/analysis")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_get_analysis_results_after_run(client, case_with_messages):
    """After inserting an analysis result, GET returns it."""
    import app.database as _db
    db = _db.get_db()
    db.execute(
        "INSERT INTO analysis_results (case_id, artifact_key, result) VALUES (?,?,?)",
        (case_with_messages, "sms", "**LOW** — nothing suspicious."),
    )
    db.commit()

    resp = client.get(f"/api/cases/{case_with_messages}/analysis")
    assert resp.status_code == 200
    results = resp.get_json()
    assert len(results) == 1
    assert results[0]["artifact_key"] == "sms"


def test_analysis_stream_returns_sse_headers(client, case_with_messages):
    """GET /api/cases/<id>/analysis/stream returns SSE content-type."""
    resp = client.get(
        f"/api/cases/{case_with_messages}/analysis/stream",
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.content_type
