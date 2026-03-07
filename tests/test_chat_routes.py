"""Tests for chatbot route — FTS5 retrieval + LLM context injection."""
from unittest.mock import MagicMock, patch
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


@pytest.fixture
def case_with_messages(client):
    r = client.post("/api/cases", json={"title": "Chat Test", "officer": "X"})
    case_id = r.get_json()["id"]
    db = get_db()
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (case_id, "sms", "incoming", "+9731234567", "device",
         "Meet at the marina", "2026-01-01T20:00:00+00:00", "+9731234567", "{}"),
    )
    db.commit()
    return case_id


def test_chat_returns_response(client, case_with_messages):
    with patch("app.routes.chat.create_provider") as mock_factory:
        mock_provider = MagicMock()
        mock_provider.analyze.return_value = "No suspicious activity found."
        mock_factory.return_value = mock_provider

        resp = client.post(
            f"/api/cases/{case_with_messages}/chat",
            json={"message": "marina"},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "response" in data
    assert data["response"] == "No suspicious activity found."
    assert "context_count" in data


def test_chat_saves_history(client, case_with_messages):
    with patch("app.routes.chat.create_provider") as mock_factory:
        mock_provider = MagicMock()
        mock_provider.analyze.return_value = "The message mentions marina."
        mock_factory.return_value = mock_provider

        client.post(f"/api/cases/{case_with_messages}/chat", json={"message": "What do we know?"})

    db = get_db()
    rows = db.execute(
        "SELECT role, content FROM chat_history WHERE case_id=? ORDER BY id",
        (case_with_messages,),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"


def test_chat_returns_history(client, case_with_messages):
    with patch("app.routes.chat.create_provider") as mock_factory:
        mock_provider = MagicMock()
        mock_provider.analyze.return_value = "Answer."
        mock_factory.return_value = mock_provider
        client.post(f"/api/cases/{case_with_messages}/chat", json={"message": "Hello"})

    resp = client.get(f"/api/cases/{case_with_messages}/chat/history")
    assert resp.status_code == 200
    history = resp.get_json()
    assert len(history) == 2


def test_chat_missing_message(client, case_with_messages):
    resp = client.post(f"/api/cases/{case_with_messages}/chat", json={})
    assert resp.status_code == 400


def test_chat_case_not_found(client):
    resp = client.post("/api/cases/nonexistent/chat", json={"message": "test"})
    assert resp.status_code == 404
