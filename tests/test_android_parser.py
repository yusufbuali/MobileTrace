"""Tests for AndroidParser — Magnet Acquire ZIP+TAR and raw Android TAR."""
import sqlite3
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.parsers.android_parser import AndroidParser, _ms_to_iso, _s_to_iso
from app.parsers.dispatcher import detect_format, dispatch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_android_dbs(dest: Path) -> dict:
    """Create minimal Android sqlite DBs with sample rows."""
    # mmssms.db
    sms_path = dest / "mmssms.db"
    conn = sqlite3.connect(sms_path)
    conn.execute(
        "CREATE TABLE sms (_id INTEGER PRIMARY KEY, address TEXT, body TEXT, date INTEGER, type INTEGER)"
    )
    conn.execute("INSERT INTO sms VALUES (1, '+9665551234', 'Hello Android', 1635603921667, 1)")
    conn.execute("INSERT INTO sms VALUES (2, '+9665551234', 'Reply sent', 1635604000000, 2)")
    conn.commit(); conn.close()

    # calllog.db
    calllog_path = dest / "calllog.db"
    conn = sqlite3.connect(calllog_path)
    conn.execute(
        "CREATE TABLE calls (_id INTEGER PRIMARY KEY, number TEXT, date INTEGER, duration INTEGER, type INTEGER)"
    )
    conn.execute("INSERT INTO calls VALUES (1, '+9665551234', 1631298377000, 60, 1)")
    conn.execute("INSERT INTO calls VALUES (2, '+9669997654', 1631299000000, 0, 3)")
    conn.commit(); conn.close()

    # contacts2.db
    contacts_path = dest / "contacts2.db"
    conn = sqlite3.connect(contacts_path)
    conn.execute("CREATE TABLE raw_contacts (_id INTEGER PRIMARY KEY, display_name TEXT)")
    conn.execute("INSERT INTO raw_contacts VALUES (1, 'Ahmad Saleh')")
    conn.execute("CREATE TABLE mimetypes (_id INTEGER PRIMARY KEY, mimetype TEXT)")
    conn.execute("INSERT INTO mimetypes VALUES (5, 'vnd.android.cursor.item/phone_v2')")
    conn.execute("INSERT INTO mimetypes VALUES (7, 'vnd.android.cursor.item/name')")
    conn.execute(
        "CREATE TABLE data (_id INTEGER PRIMARY KEY, raw_contact_id INTEGER, mimetype_id INTEGER, data1 TEXT)"
    )
    conn.execute("INSERT INTO data VALUES (1, 1, 7, 'Ahmad Saleh')")
    conn.execute("INSERT INTO data VALUES (2, 1, 5, '+9665551234')")
    conn.commit(); conn.close()

    # wa.db
    wa_path = dest / "wa.db"
    conn = sqlite3.connect(wa_path)
    conn.execute(
        "CREATE TABLE wa_contacts (_id INTEGER PRIMARY KEY, jid TEXT, display_name TEXT, number TEXT)"
    )
    conn.execute("INSERT INTO wa_contacts VALUES (1, '9665551234@s.whatsapp.net', 'Ahmad Saleh', '9665551234')")
    conn.commit(); conn.close()

    # msgstore.db (old schema)
    msgstore_path = dest / "msgstore.db"
    conn = sqlite3.connect(msgstore_path)
    conn.execute(
        "CREATE TABLE messages (_id INTEGER PRIMARY KEY, key_remote_jid TEXT, data TEXT, timestamp INTEGER, key_from_me INTEGER, status INTEGER)"
    )
    conn.execute("INSERT INTO messages VALUES (1, '9665551234@s.whatsapp.net', 'Hello WA', 1638212506788, 1, 13)")
    conn.execute("INSERT INTO messages VALUES (2, '9665551234@s.whatsapp.net', 'WA reply', 1638212569000, 0, 0)")
    conn.commit(); conn.close()

    return {
        "sms": sms_path,
        "calllog": calllog_path,
        "contacts": contacts_path,
        "wa_ct": wa_path,
        "wa_msg": msgstore_path,
    }


def _tar_arc_name(key: str) -> str:
    targets = {
        "sms":      "data/data/com.android.providers.telephony/databases/mmssms.db",
        "calllog":  "data/data/com.android.providers.contacts/databases/calllog.db",
        "contacts": "data/data/com.android.providers.contacts/databases/contacts2.db",
        "wa_ct":    "data/data/com.whatsapp/databases/wa.db",
        "wa_msg":   "data/data/com.whatsapp/databases/msgstore.db",
    }
    return targets[key]


def _make_android_tar(dest: Path, dbs: dict) -> Path:
    tar_path = dest / "android_test.tar"
    with tarfile.open(tar_path, "w") as tf:
        for key, path in dbs.items():
            tf.add(path, arcname=_tar_arc_name(key))
    return tar_path


def _make_magnet_zip(dest: Path, dbs: dict) -> Path:
    tar_path = dest / "_inner.tar"
    with tarfile.open(tar_path, "w") as tf:
        for key, path in dbs.items():
            tf.add(path, arcname=_tar_arc_name(key))
    zip_path = dest / "Magnet_test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(tar_path, "Magnet Acquire/Android Data.tar")
        zf.writestr("Magnet Acquire/image_info.txt", "Imager Product: Magnet ACQUIRE\n")
    return zip_path


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def test_ms_to_iso():
    ts = _ms_to_iso(1635603921667)
    assert "2021" in ts


def test_ms_to_iso_zero():
    assert _ms_to_iso(0) == ""


def test_s_to_iso():
    ts = _s_to_iso(1631298377)
    assert "2021" in ts


# ── can_handle tests ──────────────────────────────────────────────────────────

def test_can_handle_android_tar(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    assert AndroidParser().can_handle(tar_path) is True


def test_can_handle_magnet_zip(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    zip_path = _make_magnet_zip(tmp_path, dbs)
    assert AndroidParser().can_handle(zip_path) is True


def test_cannot_handle_ios_zip(tmp_path):
    p = tmp_path / "ios.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("private/var/mobile/Library/SMS/sms.db", b"")
    assert AndroidParser().can_handle(p) is False


def test_cannot_handle_plain_zip(tmp_path):
    p = tmp_path / "other.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("readme.txt", "hello")
    assert AndroidParser().can_handle(p) is False


# ── TAR parse tests ───────────────────────────────────────────────────────────

def test_parse_tar_sms(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    result = AndroidParser().parse(tar_path, tmp_path / "out")
    sms = [m for m in result.messages if m["platform"] == "sms"]
    assert len(sms) == 2
    assert sms[0]["body"] == "Hello Android"
    assert sms[0]["direction"] == "incoming"
    assert sms[1]["direction"] == "outgoing"


def test_parse_tar_calls(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    result = AndroidParser().parse(tar_path, tmp_path / "out")
    assert len(result.call_logs) == 2
    assert result.call_logs[0]["direction"] == "incoming"
    assert result.call_logs[1]["direction"] == "missed"
    assert result.call_logs[0]["duration_s"] == 60


def test_parse_tar_contacts(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    result = AndroidParser().parse(tar_path, tmp_path / "out")
    android_contacts = [c for c in result.contacts if c["source_app"] == "android_contacts"]
    assert any(c["name"] == "Ahmad Saleh" for c in android_contacts)


def test_parse_tar_wa_contacts(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    result = AndroidParser().parse(tar_path, tmp_path / "out")
    wa_contacts = [c for c in result.contacts if c["source_app"] == "whatsapp_contacts"]
    assert len(wa_contacts) == 1
    assert wa_contacts[0]["name"] == "Ahmad Saleh"


def test_parse_tar_whatsapp_messages(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    result = AndroidParser().parse(tar_path, tmp_path / "out")
    wa_msgs = [m for m in result.messages if m["platform"] == "whatsapp"]
    assert len(wa_msgs) == 2
    assert wa_msgs[0]["body"] == "Hello WA"
    assert wa_msgs[0]["direction"] == "outgoing"
    assert wa_msgs[1]["direction"] == "incoming"


def test_parse_tar_format_field(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    result = AndroidParser().parse(tar_path, tmp_path / "out")
    assert result.format == "android_tar"
    assert result.device_info["platform"] == "android"


# ── Magnet ZIP parse tests ────────────────────────────────────────────────────

def test_parse_magnet_zip_sms(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    zip_path = _make_magnet_zip(tmp_path, dbs)
    result = AndroidParser().parse(zip_path, tmp_path / "out")
    sms = [m for m in result.messages if m["platform"] == "sms"]
    assert len(sms) == 2


def test_parse_magnet_zip_calls(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    zip_path = _make_magnet_zip(tmp_path, dbs)
    result = AndroidParser().parse(zip_path, tmp_path / "out")
    assert len(result.call_logs) == 2


def test_parse_magnet_zip_wa(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    zip_path = _make_magnet_zip(tmp_path, dbs)
    result = AndroidParser().parse(zip_path, tmp_path / "out")
    wa = [m for m in result.messages if m["platform"] == "whatsapp"]
    assert len(wa) == 2


# ── Dispatcher integration ────────────────────────────────────────────────────

def test_dispatcher_detects_android_tar(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    assert detect_format(tar_path) == "android_tar"


def test_dispatcher_detects_magnet_zip(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    zip_path = _make_magnet_zip(tmp_path, dbs)
    assert detect_format(zip_path) == "android_tar"


def test_dispatcher_parses_android_tar(tmp_path):
    Path(tmp_path / "dbs").mkdir()
    dbs = _make_android_dbs(tmp_path / "dbs")
    tar_path = _make_android_tar(tmp_path, dbs)
    result = dispatch(tar_path, tmp_path / "out")
    assert result.format == "android_tar"
    assert len(result.messages) >= 2


# ── Signal decryption tests ───────────────────────────────────────────────────

def test_signal_read_accepts_key_kwarg(tmp_path):
    """_read_signal() accepts signal_key kwarg. None path -> empty list, no crash."""
    from app.parsers.android_parser import AndroidParser
    result = AndroidParser()._read_signal(None, [], signal_key="aa" * 32)
    assert result == []
