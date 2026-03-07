"""Tests for all communications extractors."""
import sqlite3
from pathlib import Path
import pytest

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

        CREATE TABLE wa_contacts (
            jid TEXT PRIMARY KEY,
            display_name TEXT
        );
        INSERT INTO wa_contacts VALUES ('9731234567@s.whatsapp.net', 'Alice');
    """)
    conn.commit()
    conn.close()
    return db


def test_whatsapp_extracts_messages(tmp_path):
    db = make_whatsapp_android_db(tmp_path)
    msgs = extract_whatsapp(db, platform="android")
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "whatsapp"
    assert "Hello" in msgs[0]["body"]


def test_whatsapp_direction(tmp_path):
    db = make_whatsapp_android_db(tmp_path)
    msgs = extract_whatsapp(db, platform="android")
    directions = {m["direction"] for m in msgs}
    assert "incoming" in directions
    assert "outgoing" in directions


# ---------------------------------------------------------------------------
# Task 14: Telegram
# ---------------------------------------------------------------------------
from app.extractors.telegram import extract_telegram


def make_telegram_db(path: Path) -> Path:
    db = path / "cache4.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE users (
            uid INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT
        );
        INSERT INTO users VALUES (1001, 'Bob', '+441234567890');
        INSERT INTO users VALUES (1002, 'Alice', '+9731234567');

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
    conn.commit()
    conn.close()
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


# ---------------------------------------------------------------------------
# Task 15: Signal
# ---------------------------------------------------------------------------
from app.extractors.signal import extract_signal


def make_signal_db(path: Path) -> Path:
    db = path / "signal.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE sms (
            _id INTEGER PRIMARY KEY,
            address TEXT,
            body TEXT,
            date INTEGER,
            type INTEGER,
            thread_id INTEGER
        );
        INSERT INTO sms VALUES (1, '+9731234567', 'Signal msg in', 1700000000000, 1, 10);
        INSERT INTO sms VALUES (2, '+9731234567', 'Signal msg out', 1700001000000, 2, 10);
    """)
    conn.commit()
    conn.close()
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


# ---------------------------------------------------------------------------
# Task 16: SMS / MMS
# ---------------------------------------------------------------------------
from app.extractors.sms import extract_sms


def make_sms_db(path: Path) -> Path:
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
    conn.commit()
    conn.close()
    return db


def test_sms_extracts_messages(tmp_path):
    db = make_sms_db(tmp_path)
    msgs = extract_sms(db)
    assert len(msgs) == 2
    assert msgs[0]["platform"] == "sms"


def test_sms_body(tmp_path):
    db = make_sms_db(tmp_path)
    msgs = extract_sms(db)
    assert any("Hello" in m["body"] for m in msgs)


def test_sms_direction(tmp_path):
    db = make_sms_db(tmp_path)
    msgs = extract_sms(db)
    directions = {m["direction"] for m in msgs}
    assert "incoming" in directions
    assert "outgoing" in directions


# ---------------------------------------------------------------------------
# Task 17: Call logs
# ---------------------------------------------------------------------------
from app.extractors.call_logs import extract_call_logs


def make_calls_db(path: Path) -> Path:
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
    conn.commit()
    conn.close()
    return db


def test_call_logs_extracted(tmp_path):
    db = make_calls_db(tmp_path)
    calls = extract_call_logs(db)
    assert len(calls) == 2
    assert calls[0]["platform"] == "phone"


def test_call_logs_duration(tmp_path):
    db = make_calls_db(tmp_path)
    calls = extract_call_logs(db)
    assert calls[0]["duration_s"] == 90


def test_call_logs_direction(tmp_path):
    db = make_calls_db(tmp_path)
    calls = extract_call_logs(db)
    directions = {c["direction"] for c in calls}
    assert "incoming" in directions
    assert "missed" in directions
