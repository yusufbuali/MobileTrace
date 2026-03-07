"""Tests for all communications extractors — correct schemas per platform."""
import sqlite3
from pathlib import Path
import pytest

_APPLE_EPOCH_OFFSET = 978307200  # seconds since 2001-01-01


# ---------------------------------------------------------------------------
# Task 13: WhatsApp
# ---------------------------------------------------------------------------
from app.extractors.whatsapp import extract_whatsapp


def make_whatsapp_android_db(path: Path) -> Path:
    db = path / "msgstore.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE messages (
            _id INTEGER PRIMARY KEY,
            key_remote_jid TEXT,
            key_from_me INTEGER,
            data TEXT,
            timestamp INTEGER,
            status INTEGER
        );
        INSERT INTO messages VALUES (1, '9731234567@s.whatsapp.net', 0, 'Hello there', 1700000000000, 5);
        INSERT INTO messages VALUES (2, '9731234567@s.whatsapp.net', 1, 'Hi back', 1700001000000, 5);
    """)
    conn.commit(); conn.close()
    return db


def make_whatsapp_ios_db(path: Path) -> Path:
    """iOS ChatStorage.sqlite — ZWAMESSAGE + ZWACHATSESSION."""
    db = path / "ChatStorage.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ZWACHATSESSION (
            Z_PK INTEGER PRIMARY KEY,
            ZCONTACTJID TEXT
        );
        INSERT INTO ZWACHATSESSION VALUES (1, '9731234567@s.whatsapp.net');

        CREATE TABLE ZWAMESSAGE (
            Z_PK INTEGER PRIMARY KEY,
            ZCHATSESSION INTEGER,
            ZFROMJID TEXT,
            ZTOJID TEXT,
            ZISFROMME INTEGER,
            ZTEXT TEXT,
            ZMESSAGEDATE REAL
        );
        INSERT INTO ZWAMESSAGE VALUES (1, 1, '9731234567@s.whatsapp.net', NULL, 0, 'iOS incoming', 666000000.0);
        INSERT INTO ZWAMESSAGE VALUES (2, 1, NULL, '9731234567@s.whatsapp.net', 1, 'iOS outgoing', 666001000.0);
    """)
    conn.commit(); conn.close()
    return db


def test_whatsapp_android_extracts_messages(tmp_path):
    db = make_whatsapp_android_db(tmp_path)
    msgs = extract_whatsapp(db, platform="android")
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "whatsapp"
    assert "Hello" in msgs[0]["body"]


def test_whatsapp_android_direction(tmp_path):
    db = make_whatsapp_android_db(tmp_path)
    msgs = extract_whatsapp(db, platform="android")
    directions = {m["direction"] for m in msgs}
    assert "incoming" in directions
    assert "outgoing" in directions


def test_whatsapp_ios_extracts_messages(tmp_path):
    db = make_whatsapp_ios_db(tmp_path)
    msgs = extract_whatsapp(db, platform="ios")
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "whatsapp"


def test_whatsapp_ios_direction(tmp_path):
    db = make_whatsapp_ios_db(tmp_path)
    msgs = extract_whatsapp(db, platform="ios")
    directions = {m["direction"] for m in msgs}
    assert "incoming" in directions
    assert "outgoing" in directions


# ---------------------------------------------------------------------------
# Task 14: Telegram — correct users schema (first_name, last_name, username)
# ---------------------------------------------------------------------------
from app.extractors.telegram import extract_telegram


def make_telegram_db(path: Path) -> Path:
    db = path / "cache4.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE users (
            uid INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            phone TEXT
        );
        INSERT INTO users VALUES (1001, 'Bob', 'Smith', 'bobsmith', '+441234567890');
        INSERT INTO users VALUES (1002, 'Alice', 'Doe', 'alicedoe', '+9731234567');

        CREATE TABLE messages (
            mid INTEGER PRIMARY KEY,
            uid INTEGER,
            out INTEGER,
            message TEXT,
            date INTEGER,
            dialog_id INTEGER
        );
        INSERT INTO messages VALUES (1, 1001, 0, 'Hey from Bob', 1700000000, 1001);
        INSERT INTO messages VALUES (2, 1002, 1, 'Reply from me', 1700001000, 1001);
    """)
    conn.commit(); conn.close()
    return db


def test_telegram_extracts_messages(tmp_path):
    db = make_telegram_db(tmp_path)
    msgs = extract_telegram(db)
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "telegram"


def test_telegram_direction(tmp_path):
    db = make_telegram_db(tmp_path)
    msgs = extract_telegram(db)
    directions = {m["direction"] for m in msgs}
    assert "incoming" in directions
    assert "outgoing" in directions


def test_telegram_body(tmp_path):
    db = make_telegram_db(tmp_path)
    msgs = extract_telegram(db)
    bodies = [m["body"] for m in msgs]
    assert "Hey from Bob" in bodies


def test_telegram_user_name_resolved(tmp_path):
    """Sender name should be resolved from users table, not raw uid."""
    db = make_telegram_db(tmp_path)
    msgs = extract_telegram(db)
    incoming = [m for m in msgs if m["direction"] == "incoming"]
    assert len(incoming) == 1
    assert incoming[0]["sender"] == "Bob Smith"


def test_telegram_encrypted_db_handled_gracefully(tmp_path):
    """Non-SQLite file (simulating encrypted DB) should return [] without crash."""
    fake_db = tmp_path / "cache4.db"
    fake_db.write_bytes(b"SQLCipher encrypted data\x00" * 100)
    msgs = extract_telegram(fake_db)
    assert msgs == []


# ---------------------------------------------------------------------------
# Task 15: Signal — correct schema (date_sent, type bitmask)
# ---------------------------------------------------------------------------
from app.extractors.signal import extract_signal


def make_signal_db(path: Path) -> Path:
    """Older Signal Android schema: sms table with date_sent."""
    db = path / "signal.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE sms (
            _id INTEGER PRIMARY KEY,
            address TEXT,
            date_sent INTEGER,
            body TEXT,
            type INTEGER,
            thread_id INTEGER
        );
        INSERT INTO sms VALUES (1, '+9731234567', 1700000000000, 'Signal msg in', 1, 10);
        INSERT INTO sms VALUES (2, '+9731234567', 1700001000000, 'Signal msg out', 2, 10);
    """)
    conn.commit(); conn.close()
    return db


def make_signal_new_db(path: Path) -> Path:
    """Newer Signal (v5+) schema: message table instead of sms."""
    db = path / "signal_new.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE message (
            _id INTEGER PRIMARY KEY,
            to_recipient_id TEXT,
            date_sent INTEGER,
            body TEXT,
            type INTEGER
        );
        INSERT INTO message VALUES (1, '+9731234567', 1700000000000, 'New Signal in', 1);
        INSERT INTO message VALUES (2, '+441112223333', 1700001000000, 'New Signal out', 2);
    """)
    conn.commit(); conn.close()
    return db


def test_signal_extracts_messages(tmp_path):
    db = make_signal_db(tmp_path)
    msgs = extract_signal(db)
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "signal"


def test_signal_direction(tmp_path):
    db = make_signal_db(tmp_path)
    msgs = extract_signal(db)
    directions = {m["direction"] for m in msgs}
    assert "incoming" in directions
    assert "outgoing" in directions


def test_signal_new_schema_fallback(tmp_path):
    """Extractor should fall back to 'message' table when 'sms' is absent."""
    db = make_signal_new_db(tmp_path)
    msgs = extract_signal(db)
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "signal"


def test_signal_ios_returns_empty_with_warning(tmp_path, caplog):
    import logging
    db = tmp_path / "signal.sqlite"
    db.write_bytes(b"fake")
    with caplog.at_level(logging.WARNING):
        msgs = extract_signal(db, platform="ios")
    assert msgs == []
    assert "grdb" in caplog.text.lower() or "ios" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Task 16: SMS — correct Android + iOS schemas
# ---------------------------------------------------------------------------
from app.extractors.sms import extract_sms


def make_android_sms_db(path: Path) -> Path:
    db = path / "mmssms.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE sms (
            _id INTEGER PRIMARY KEY,
            address TEXT,
            body TEXT,
            date INTEGER,
            type INTEGER
        );
        INSERT INTO sms VALUES (1, '+9731234567', 'Hello by SMS', 1700000000000, 1);
        INSERT INTO sms VALUES (2, '+9731234567', 'SMS reply', 1700001000000, 2);
    """)
    conn.commit(); conn.close()
    return db


def make_ios_sms_db(path: Path) -> Path:
    """iOS sms.db — message table joined with handle, Apple epoch dates."""
    db = path / "sms.db"
    conn = sqlite3.connect(db)
    # Apple epoch date: 666000000 s ≈ 2022-02-07
    conn.executescript("""
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY,
            id TEXT
        );
        INSERT INTO handle VALUES (1, '+9731234567');

        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            handle_id INTEGER,
            text TEXT,
            date INTEGER,
            is_from_me INTEGER
        );
        INSERT INTO message VALUES (1, 1, 'iOS SMS incoming', 666000000, 0);
        INSERT INTO message VALUES (2, 1, 'iOS SMS outgoing', 666001000, 1);
    """)
    conn.commit(); conn.close()
    return db


def test_sms_android_extracts(tmp_path):
    db = make_android_sms_db(tmp_path)
    msgs = extract_sms(db, platform="android")
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "sms"
    assert any("Hello" in m["body"] for m in msgs)


def test_sms_android_direction(tmp_path):
    db = make_android_sms_db(tmp_path)
    msgs = extract_sms(db, platform="android")
    directions = {m["direction"] for m in msgs}
    assert "incoming" in directions
    assert "outgoing" in directions


def test_sms_ios_extracts(tmp_path):
    db = make_ios_sms_db(tmp_path)
    msgs = extract_sms(db, platform="ios")
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "sms"


def test_sms_ios_direction(tmp_path):
    db = make_ios_sms_db(tmp_path)
    msgs = extract_sms(db, platform="ios")
    directions = {m["direction"] for m in msgs}
    assert "incoming" in directions
    assert "outgoing" in directions


def test_sms_ios_address_from_handle(tmp_path):
    """Phone number should come from the handle table join."""
    db = make_ios_sms_db(tmp_path)
    msgs = extract_sms(db, platform="ios")
    assert any("+9731234567" in (m["sender"] + m["recipient"]) for m in msgs)


# ---------------------------------------------------------------------------
# Task 17: Call logs — correct Android + iOS (ZCALLRECORD) schemas
# ---------------------------------------------------------------------------
from app.extractors.call_logs import extract_call_logs


def make_android_calls_db(path: Path) -> Path:
    db = path / "contacts2.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE calls (
            _id INTEGER PRIMARY KEY,
            number TEXT,
            duration INTEGER,
            date INTEGER,
            type INTEGER
        );
        INSERT INTO calls VALUES (1, '+9731234567', 90, 1700000000000, 1);
        INSERT INTO calls VALUES (2, '+441234567890', 0, 1700001000000, 3);
    """)
    conn.commit(); conn.close()
    return db


def make_ios_calls_db(path: Path) -> Path:
    """iOS call_history.db — ZCALLRECORD Core Data table, Apple epoch."""
    db = path / "call_history.db"
    conn = sqlite3.connect(db)
    # ZORIGINATED=0 incoming answered, ZORIGINATED=1 outgoing, ZORIGINATED=0+ZANSWERED=0 missed
    conn.executescript("""
        CREATE TABLE ZCALLRECORD (
            Z_PK INTEGER PRIMARY KEY,
            ZADDRESS TEXT,
            ZDURATION REAL,
            ZDATE REAL,
            ZORIGINATED INTEGER,
            ZANSWERED INTEGER,
            ZCALLTYPE INTEGER
        );
        INSERT INTO ZCALLRECORD VALUES (1, '+9731234567', 120.0, 666000000.0, 0, 1, 1);
        INSERT INTO ZCALLRECORD VALUES (2, '+441234567890', 60.0, 666001000.0, 1, 1, 1);
        INSERT INTO ZCALLRECORD VALUES (3, '+9731111111', 0.0, 666002000.0, 0, 0, 1);
    """)
    conn.commit(); conn.close()
    return db


def test_call_logs_android_extracted(tmp_path):
    db = make_android_calls_db(tmp_path)
    calls = extract_call_logs(db, platform="android")
    assert len(calls) == 2
    assert calls[0]["platform"] == "phone"


def test_call_logs_android_duration(tmp_path):
    db = make_android_calls_db(tmp_path)
    calls = extract_call_logs(db, platform="android")
    assert calls[0]["duration_s"] == 90


def test_call_logs_android_direction(tmp_path):
    db = make_android_calls_db(tmp_path)
    calls = extract_call_logs(db, platform="android")
    directions = {c["direction"] for c in calls}
    assert "incoming" in directions
    assert "missed" in directions


def test_call_logs_ios_extracted(tmp_path):
    db = make_ios_calls_db(tmp_path)
    calls = extract_call_logs(db, platform="ios")
    assert len(calls) == 3


def test_call_logs_ios_direction(tmp_path):
    db = make_ios_calls_db(tmp_path)
    calls = extract_call_logs(db, platform="ios")
    directions = {c["direction"] for c in calls}
    assert "incoming" in directions
    assert "outgoing" in directions
    assert "missed" in directions


def test_call_logs_ios_facetime_type(tmp_path):
    """ZCALLTYPE=8 should map to facetime_video platform."""
    db = tmp_path / "call_history.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ZCALLRECORD (
            Z_PK INTEGER PRIMARY KEY, ZADDRESS TEXT, ZDURATION REAL,
            ZDATE REAL, ZORIGINATED INTEGER, ZANSWERED INTEGER, ZCALLTYPE INTEGER
        );
        INSERT INTO ZCALLRECORD VALUES (1, '+9731234567', 300.0, 666000000.0, 0, 1, 8);
    """)
    conn.commit(); conn.close()
    calls = extract_call_logs(db, platform="ios")
    assert calls[0]["platform"] == "facetime_video"
