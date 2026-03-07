"""SQLite database layer for MobileTrace."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

_local = threading.local()
_db_path: str = "data/mobiletrace.db"

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cases (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    case_number TEXT,
    officer     TEXT,
    status      TEXT DEFAULT 'open',
    device_info TEXT DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS evidence_files (
    id           TEXT PRIMARY KEY,
    case_id      TEXT REFERENCES cases(id) ON DELETE CASCADE,
    format       TEXT NOT NULL,
    source_path  TEXT,
    parse_status TEXT DEFAULT 'pending',
    parse_error  TEXT,
    parsed_at    TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT REFERENCES cases(id) ON DELETE CASCADE,
    name       TEXT,
    phone      TEXT,
    email      TEXT,
    source_app TEXT,
    raw_json   TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT REFERENCES cases(id) ON DELETE CASCADE,
    platform   TEXT NOT NULL,
    direction  TEXT DEFAULT 'unknown',
    sender     TEXT,
    recipient  TEXT,
    body       TEXT,
    timestamp  TEXT,
    thread_id  TEXT,
    raw_json   TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS call_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT REFERENCES cases(id) ON DELETE CASCADE,
    number     TEXT,
    direction  TEXT DEFAULT 'unknown',
    duration_s INTEGER DEFAULT 0,
    timestamp  TEXT,
    platform   TEXT DEFAULT 'phone'
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT REFERENCES cases(id) ON DELETE CASCADE,
    artifact_key TEXT NOT NULL,
    result       TEXT DEFAULT '',
    provider     TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(case_id, artifact_key)
);

CREATE TABLE IF NOT EXISTS chat_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT REFERENCES cases(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    context_ids TEXT DEFAULT '[]',
    created_at  TEXT DEFAULT (datetime('now'))
);

-- FTS5 virtual tables
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    body, sender, recipient,
    content='messages',
    content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS contacts_fts USING fts5(
    name, phone, email,
    content='contacts',
    content_rowid='id'
);

-- Triggers to keep FTS5 in sync
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, body, sender, recipient)
    VALUES (new.id, new.body, new.sender, new.recipient);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body, sender, recipient)
    VALUES ('delete', old.id, old.body, old.sender, old.recipient);
END;

CREATE TRIGGER IF NOT EXISTS contacts_ai AFTER INSERT ON contacts BEGIN
    INSERT INTO contacts_fts(rowid, name, phone, email)
    VALUES (new.id, new.name, new.phone, new.email);
END;

CREATE TRIGGER IF NOT EXISTS contacts_ad AFTER DELETE ON contacts BEGIN
    INSERT INTO contacts_fts(contacts_fts, rowid, name, phone, email)
    VALUES ('delete', old.id, old.name, old.phone, old.email);
END;
"""


def init_db(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def get_db() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(_db_path)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def close_db() -> None:
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None
