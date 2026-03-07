"""Smoke tests for GET /api/cases/<id>/threads and GET /api/cases/<id>/messages."""
import json
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


def _make_case(client, title="Test Case"):
    r = client.post("/api/cases", json={"title": title, "officer": "Det. Test"})
    assert r.status_code == 201
    return r.get_json()["id"]


def _seed_messages(client, case_id):
    """Directly insert test messages via the DB (bypasses evidence upload)."""
    from app.database import get_db
    db = get_db()
    db.executemany(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [
            (case_id, "whatsapp", "incoming", "+97312345678", "+97387654321",
             "Hello from WA", "2026-03-01T10:00:00", "+97312345678"),
            (case_id, "whatsapp", "outgoing", "+97387654321", "+97312345678",
             "Reply here", "2026-03-01T10:01:00", "+97312345678"),
            (case_id, "sms", "incoming", "+96655551234", "+97387654321",
             "Hello SMS", "2026-03-01T11:00:00", None),
        ],
    )
    db.commit()


def test_threads_returns_grouped(client):
    case_id = _make_case(client)
    _seed_messages(client, case_id)
    r = client.get(f"/api/cases/{case_id}/threads")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert len(data) == 2  # whatsapp thread + sms thread
    platforms = {t["platform"] for t in data}
    assert "whatsapp" in platforms
    assert "sms" in platforms
    for t in data:
        assert "thread" in t
        assert "message_count" in t
        assert "last_ts" in t


def test_messages_returns_all(client):
    case_id = _make_case(client)
    _seed_messages(client, case_id)
    r = client.get(f"/api/cases/{case_id}/messages")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list)
    assert len(data) == 3
    # Check expected fields present
    for m in data:
        for field in ("id", "platform", "direction", "sender", "recipient", "body", "timestamp"):
            assert field in m


def test_messages_platform_filter(client):
    case_id = _make_case(client)
    _seed_messages(client, case_id)
    r = client.get(f"/api/cases/{case_id}/messages?platform=sms")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 1
    assert data[0]["platform"] == "sms"


def test_messages_search(client):
    case_id = _make_case(client)
    _seed_messages(client, case_id)
    r = client.get(f"/api/cases/{case_id}/messages?q=Hello")
    assert r.status_code == 200
    data = r.get_json()
    # Should match at least the two "Hello" messages (whatsapp + sms)
    assert isinstance(data, list)
    bodies = [m["body"] for m in data]
    assert any("Hello" in b for b in bodies)


def test_threads_nonexistent_case(client):
    r = client.get("/api/cases/nonexistent-id/threads")
    assert r.status_code == 404


def test_messages_nonexistent_case(client):
    r = client.get("/api/cases/nonexistent-id/messages")
    assert r.status_code == 404
