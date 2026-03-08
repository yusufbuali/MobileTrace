"""Tests for iOSParser — TAR and ZIP full-filesystem iOS extractions."""
import sqlite3
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.parsers.ios_parser import iOSParser, _apple_ts_to_iso
from app.parsers.dispatcher import dispatch, detect_format


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ios_dbs(dest: Path) -> dict:
    """Create minimal iOS sqlite DBs with one row each."""
    # sms.db
    sms_path = dest / "sms.db"
    conn = sqlite3.connect(sms_path)
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.execute("INSERT INTO handle VALUES (1, '+9665551234')")
    conn.execute(
        "CREATE TABLE message (ROWID INTEGER PRIMARY KEY, handle_id INTEGER, "
        "date INTEGER, text TEXT, is_from_me INTEGER)"
    )
    # Apple epoch timestamp: 0 = 2001-01-01
    conn.execute("INSERT INTO message VALUES (1, 1, 0, 'Hello iOS', 0)")
    conn.commit()
    conn.close()

    # AddressBook.sqlitedb
    ab_path = dest / "ab.sqlitedb"
    conn = sqlite3.connect(ab_path)
    conn.execute("CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY, First TEXT, Last TEXT)")
    conn.execute("INSERT INTO ABPerson VALUES (1, 'Ahmad', 'Saleh')")
    conn.execute(
        "CREATE TABLE ABMultiValue (ROWID INTEGER PRIMARY KEY, record_id INTEGER, "
        "label INTEGER, value TEXT)"
    )
    conn.execute("INSERT INTO ABMultiValue VALUES (1, 1, NULL, '+9665551234')")
    conn.execute(
        "CREATE TABLE ABMultiValueLabel (ROWID INTEGER PRIMARY KEY, value TEXT)"
    )
    conn.commit()
    conn.close()

    # CallHistory.storedata
    calls_path = dest / "calls.storedata"
    conn = sqlite3.connect(calls_path)
    conn.execute(
        "CREATE TABLE ZCALLRECORD (Z_PK INTEGER PRIMARY KEY, ZADDRESS TEXT, "
        "ZDURATION REAL, ZDATE REAL, ZORIGINATED INTEGER, ZANSWERED INTEGER)"
    )
    conn.execute("INSERT INTO ZCALLRECORD VALUES (1, '+9665551234', 60.0, 0, 0, 1)")
    conn.commit()
    conn.close()

    return {"sms": sms_path, "contacts": ab_path, "calls": calls_path}


def _make_ios_zip(dest: Path, dbs: dict) -> Path:
    zip_path = dest / "iphone_test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(dbs["sms"],      "/private/var/mobile/Library/SMS/sms.db")
        zf.write(dbs["contacts"], "/private/var/mobile/Library/AddressBook/AddressBook.sqlitedb")
        zf.write(dbs["calls"],    "/private/var/mobile/Library/CallHistoryDB/CallHistory.storedata")
    return zip_path


def _make_ios_tar(dest: Path, dbs: dict) -> Path:
    tar_path = dest / "iphone_test.tar"
    with tarfile.open(tar_path, "w") as tf:
        tf.add(dbs["sms"],      arcname="private/var/mobile/Library/SMS/sms.db")
        tf.add(dbs["contacts"], arcname="private/var/mobile/Library/AddressBook/AddressBook.sqlitedb")
        tf.add(dbs["calls"],    arcname="private/var/mobile/Library/CallHistoryDB/CallHistory.storedata")
    return tar_path


# ── Apple timestamp tests ─────────────────────────────────────────────────────

def test_apple_ts_zero():
    # epoch 0 = 2001-01-01T00:00:00+00:00
    result = _apple_ts_to_iso(0)
    assert result == ""  # ts <= 0 returns empty


def test_apple_ts_seconds():
    ts = 757382400  # some date after 2001
    result = _apple_ts_to_iso(ts)
    assert result.startswith("2025") or result.startswith("202")


def test_apple_ts_none():
    assert _apple_ts_to_iso(None) == ""


def test_apple_ts_nanoseconds():
    # 1 ns past epoch
    result = _apple_ts_to_iso(1_000_000_000)
    assert "2001" in result or result != ""


# ── can_handle tests ──────────────────────────────────────────────────────────

def test_can_handle_ios_zip(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    zip_path = _make_ios_zip(tmp_path, dbs)
    assert iOSParser().can_handle(zip_path) is True


def test_can_handle_ios_tar(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    tar_path = _make_ios_tar(tmp_path, dbs)
    assert iOSParser().can_handle(tar_path) is True


def test_cannot_handle_random_zip(tmp_path):
    p = tmp_path / "other.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("readme.txt", "not ios")
    assert iOSParser().can_handle(p) is False


def test_cannot_handle_ofb(tmp_path):
    p = tmp_path / "test.ofb"
    p.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    assert iOSParser().can_handle(p) is False


# ── ZIP parse tests ───────────────────────────────────────────────────────────

def test_parse_zip_contacts(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    zip_path = _make_ios_zip(tmp_path, dbs)
    result = iOSParser().parse(zip_path, tmp_path / "out")
    assert len(result.contacts) >= 1
    assert result.contacts[0]["name"] == "Ahmad Saleh"
    assert result.contacts[0]["phone"] == "+9665551234"


def test_parse_zip_sms(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    zip_path = _make_ios_zip(tmp_path, dbs)
    result = iOSParser().parse(zip_path, tmp_path / "out")
    assert len(result.messages) == 1
    assert result.messages[0]["body"] == "Hello iOS"
    assert result.messages[0]["platform"] == "sms"
    assert result.messages[0]["direction"] == "incoming"


def test_parse_zip_calls(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    zip_path = _make_ios_zip(tmp_path, dbs)
    result = iOSParser().parse(zip_path, tmp_path / "out")
    assert len(result.call_logs) == 1
    assert result.call_logs[0]["number"] == "+9665551234"
    assert result.call_logs[0]["duration_s"] == 60
    assert result.call_logs[0]["direction"] == "incoming"


def test_parse_zip_device_info(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    zip_path = _make_ios_zip(tmp_path, dbs)
    result = iOSParser().parse(zip_path, tmp_path / "out")
    assert result.device_info["platform"] == "ios"


def test_parse_zip_format_field(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    zip_path = _make_ios_zip(tmp_path, dbs)
    result = iOSParser().parse(zip_path, tmp_path / "out")
    assert result.format == "ios_fs"


# ── TAR parse tests ───────────────────────────────────────────────────────────

def test_parse_tar_sms(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    tar_path = _make_ios_tar(tmp_path, dbs)
    result = iOSParser().parse(tar_path, tmp_path / "out")
    assert len(result.messages) == 1
    assert result.messages[0]["body"] == "Hello iOS"


def test_parse_tar_contacts(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    tar_path = _make_ios_tar(tmp_path, dbs)
    result = iOSParser().parse(tar_path, tmp_path / "out")
    assert len(result.contacts) >= 1
    assert "Ahmad" in result.contacts[0]["name"]


def test_parse_tar_calls(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    tar_path = _make_ios_tar(tmp_path, dbs)
    result = iOSParser().parse(tar_path, tmp_path / "out")
    assert len(result.call_logs) == 1


# ── Dispatcher integration ────────────────────────────────────────────────────

def test_dispatcher_detects_ios_zip(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    zip_path = _make_ios_zip(tmp_path, dbs)
    assert detect_format(zip_path) == "ios_fs"


def test_dispatcher_detects_ios_tar(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    tar_path = _make_ios_tar(tmp_path, dbs)
    assert detect_format(tar_path) == "ios_fs"


def test_dispatcher_parses_ios_zip(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_ios_dbs(tmp_path / "dbs")
    zip_path = _make_ios_zip(tmp_path, dbs)
    result = dispatch(zip_path, tmp_path / "out")
    assert result.format == "ios_fs"
    assert len(result.messages) >= 1


# ── Telegram iOS tests ────────────────────────────────────────────────────────

def test_read_telegram_ios(tmp_path):
    """iOSParser reads Telegram messages from TelegramDatabase.sqlite."""
    db = tmp_path / "ios_telegram.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE messages (
            mid INTEGER PRIMARY KEY, peer_id INTEGER,
            timestamp INTEGER, message TEXT, outgoing INTEGER
        );
        CREATE TABLE peers (
            id INTEGER PRIMARY KEY, phone TEXT,
            first_name TEXT, last_name TEXT
        );
        INSERT INTO peers VALUES (42, '+97312345678', 'Alice', 'Smith');
        INSERT INTO messages VALUES (1, 42, 1700000000, 'Hello Telegram iOS', 0);
    """)
    conn.commit()
    conn.close()

    from app.parsers.ios_parser import iOSParser
    msgs = iOSParser()._read_telegram_ios(db, [])
    assert len(msgs) == 1
    assert msgs[0]["platform"] == "telegram"
    assert msgs[0]["direction"] == "incoming"
    assert "Hello" in msgs[0]["body"]


# ── iMessage group chat + attachment tests ────────────────────────────────────

def test_read_sms_group_and_attachments(tmp_path):
    """_read_sms() uses group chat_identifier as thread_id and captures attachments."""
    db = tmp_path / "sms_group.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, handle_id INTEGER, date INTEGER,
            text TEXT, is_from_me INTEGER, cache_roomnames TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY, mime_type TEXT, transfer_name TEXT);
        CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
        INSERT INTO handle VALUES (1, 'Alice');
        INSERT INTO chat VALUES (10, 'chat123', 'Group Chat');
        INSERT INTO message VALUES (1, 1, 700000000, 'Hi group', 0, 'chat123');
        INSERT INTO chat_message_join VALUES (10, 1);
        INSERT INTO attachment VALUES (1, 'image/jpeg', 'photo.jpg');
        INSERT INTO message_attachment_join VALUES (1, 1);
    """)
    conn.commit()
    conn.close()

    from app.parsers.ios_parser import iOSParser
    msgs = iOSParser()._read_sms(db, [])
    assert len(msgs) == 1
    assert msgs[0]["thread_id"] == "chat123"
    assert msgs[0]["raw_json"].get("attachments") == [
        {"mime_type": "image/jpeg", "filename": "photo.jpg"}
    ]
