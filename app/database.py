"""SQLite database layer for MobileTrace."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

_local = threading.local()
_db_path: str = "data/mobiletrace.db"

_SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    models TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    artifact_filter TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_case_id ON analysis_runs(case_id);

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

CREATE TABLE IF NOT EXISTS annotations (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    message_id  INTEGER NOT NULL,
    tag         TEXT NOT NULL DEFAULT 'KEY_EVIDENCE',
    note        TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_annotations_case    ON annotations(case_id);
CREATE INDEX IF NOT EXISTS idx_annotations_message ON annotations(message_id);

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

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_messages_case_id     ON messages(case_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp   ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_platform    ON messages(platform);
CREATE INDEX IF NOT EXISTS idx_messages_thread_id   ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_calls_case_id        ON call_logs(case_id);
CREATE INDEX IF NOT EXISTS idx_calls_timestamp      ON call_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_contacts_case_id     ON contacts(case_id);
CREATE INDEX IF NOT EXISTS idx_analysis_case_id     ON analysis_results(case_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_case_id ON chat_history(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_case_id     ON evidence_files(case_id);

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

CREATE TABLE IF NOT EXISTS media_files (
    id           TEXT PRIMARY KEY,
    case_id      TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    message_id   INTEGER,
    filename     TEXT NOT NULL,
    mime_type    TEXT NOT NULL,
    size_bytes   INTEGER,
    filepath     TEXT NOT NULL,
    extracted_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_media_files_case    ON media_files(case_id);
CREATE INDEX IF NOT EXISTS idx_media_files_message ON media_files(message_id);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply schema migrations that cannot be expressed as idempotent DDL."""
    cursor = conn.cursor()

    # Migrate analysis_results: drop inline UNIQUE(case_id, artifact_key), add run_id
    cursor.execute("PRAGMA table_info(analysis_results)")
    cols = {r[1] for r in cursor.fetchall()}

    if "run_id" not in cols:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS analysis_results_v2 (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id      TEXT REFERENCES cases(id) ON DELETE CASCADE,
            artifact_key TEXT NOT NULL,
            result       TEXT DEFAULT '',
            provider     TEXT,
            run_id       TEXT REFERENCES analysis_runs(id),
            created_at   TEXT DEFAULT (datetime('now'))
        );
        INSERT OR IGNORE INTO analysis_results_v2
            (id, case_id, artifact_key, result, provider, created_at)
            SELECT id, case_id, artifact_key, result, provider, created_at
            FROM analysis_results;
        DROP TABLE analysis_results;
        ALTER TABLE analysis_results_v2 RENAME TO analysis_results;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_results_multi
            ON analysis_results(case_id, artifact_key, COALESCE(run_id,''), COALESCE(provider,''));
        """)

    # Add source column to contacts (idempotent)
    try:
        conn.execute("ALTER TABLE contacts ADD COLUMN source TEXT DEFAULT NULL")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            raise

    # Add status + error_message to analysis_results (idempotent)
    for col, definition in [("status", "TEXT DEFAULT 'ok'"), ("error_message", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE analysis_results ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise

    # Add sha256 to evidence_files (idempotent)
    try:
        conn.execute("ALTER TABLE evidence_files ADD COLUMN sha256 TEXT")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            raise


def init_db(db_path: str) -> None:
    global _db_path
    _db_path = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
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
