"""Tests for FTS5 retrieval function."""
import pytest
from app import create_app
from app.database import init_db, close_db, get_db
from app.retriever import fts_retrieve


@pytest.fixture
def db_with_fts(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    db = get_db()

    # Insert a case
    db.execute(
        "INSERT INTO cases (id, title, officer, status) VALUES (?,?,?,?)",
        ("c1", "FTS Test", "X", "open"),
    )
    # Insert messages
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("c1", "sms", "incoming", "+9731234567", "device",
         "Meet me at the marina tonight", "2026-01-01T20:00:00+00:00", "+9731234567", "{}"),
    )
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("c1", "whatsapp", "outgoing", "device", "+9731234567",
         "Transfer done", "2026-01-02T10:00:00+00:00", "+9731234567", "{}"),
    )
    # Insert contact
    db.execute(
        "INSERT INTO contacts (case_id, name, phone, email, source_app, raw_json) VALUES (?,?,?,?,?,?)",
        ("c1", "Ali Hassan", "+9731234567", "ali@example.com", "android_contacts", "{}"),
    )
    db.commit()
    yield db
    close_db()


def test_fts_retrieve_message_hit(db_with_fts):
    results = fts_retrieve("c1", "marina", db_with_fts)
    assert len(results) >= 1
    assert any("marina" in r["body"] for r in results if r.get("source") == "message")


def test_fts_retrieve_contact_hit(db_with_fts):
    results = fts_retrieve("c1", "Hassan", db_with_fts)
    assert len(results) >= 1
    assert any(r.get("source") == "contact" for r in results)


def test_fts_retrieve_no_results(db_with_fts):
    results = fts_retrieve("c1", "xyznotexist", db_with_fts)
    assert results == []


def test_fts_retrieve_wrong_case(db_with_fts):
    """FTS search should be scoped to the requested case_id."""
    results = fts_retrieve("wrong-case", "marina", db_with_fts)
    assert results == []


def test_fts_retrieve_returns_source_field(db_with_fts):
    results = fts_retrieve("c1", "marina", db_with_fts)
    for r in results:
        assert "source" in r
