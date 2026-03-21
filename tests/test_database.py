"""Tests for database schema and FTS5 setup."""
import sqlite3
import pytest
from app.database import init_db, get_db, close_db


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    yield path
    close_db()


def test_tables_created(db_path):
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "cases" in tables
    assert "messages" in tables
    assert "contacts" in tables
    assert "call_logs" in tables
    assert "analysis_results" in tables
    assert "chat_history" in tables
    assert "evidence_files" in tables
    assert "annotations" in tables


def test_fts5_tables_created(db_path):
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "messages_fts" in tables
    assert "contacts_fts" in tables


def test_insert_and_retrieve_case(db_path):
    init_db(db_path)
    db = get_db()
    db.execute(
        "INSERT INTO cases (id, title, officer, status) VALUES (?, ?, ?, ?)",
        ("case-001", "Test Case", "Officer A", "open"),
    )
    db.commit()
    row = db.execute("SELECT title FROM cases WHERE id=?", ("case-001",)).fetchone()
    assert row["title"] == "Test Case"


def test_annotations_table_exists(app):
    from app.database import get_db
    with app.app_context():
        db = get_db()
        # Should not raise — table must exist
        db.execute("SELECT id, case_id, message_id, tag, note, created_at FROM annotations LIMIT 1")


def test_contacts_source_column(app):
    """contacts table must have a source column defaulting to NULL."""
    with app.app_context():
        from app.database import get_db
        db = get_db()
        info = db.execute("PRAGMA table_info(contacts)").fetchall()
        cols = [r["name"] for r in info]
        assert "source" in cols


def test_media_files_table_exists(app):
    """media_files table must exist with required columns."""
    with app.app_context():
        from app.database import get_db
        db = get_db()
        info = db.execute("PRAGMA table_info(media_files)").fetchall()
        cols = [r["name"] for r in info]
        for col in ["id", "case_id", "message_id", "filename", "mime_type", "size_bytes", "filepath"]:
            assert col in cols, f"Missing column: {col}"
