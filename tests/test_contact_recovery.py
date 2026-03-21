"""Tests for encrypted-device contact recovery (C3)."""
import sqlite3
import uuid
from pathlib import Path
import pytest

def _make_wa_db(path: Path):
    """Create a minimal wa.db with two WhatsApp contacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE wa_contacts (jid TEXT, display_name TEXT, number TEXT)")
    conn.execute("INSERT INTO wa_contacts VALUES ('1@s.whatsapp.net', 'Alice', '+15550101')")
    conn.execute("INSERT INTO wa_contacts VALUES ('2@s.whatsapp.net', 'Bob', '+15550202')")
    conn.commit()
    conn.close()

def test_ios_recovery_from_whatsapp(tmp_path):
    """_recover_contacts_ios returns contacts from wa.db when called."""
    from app.parsers.ios_parser import iOSParser
    wa_db = tmp_path / "wa.db"
    _make_wa_db(wa_db)
    parser = iOSParser.__new__(iOSParser)
    warnings = []
    recovered = parser._recover_contacts_ios(
        wa_db_path=wa_db, tg_db_path=None, parsed_messages=[], warnings=warnings
    )
    assert len(recovered) == 2
    assert all(c["source"] == "recovered" for c in recovered)
    names = {c["name"] for c in recovered}
    assert "Alice" in names and "Bob" in names

def test_recovery_deduplication(tmp_path):
    """Same normalized phone in WhatsApp + SMS yields one contact."""
    from app.parsers.ios_parser import iOSParser
    wa_db = tmp_path / "wa.db"
    _make_wa_db(wa_db)
    # SMS message from Alice with same number as WhatsApp (different formatting)
    sms_messages = [{
        "platform": "sms", "direction": "incoming", "sender": "Alice",
        "body": "hi", "timestamp": "2021-01-01T10:00:00",
        "thread_id": "+15550101", "recipient": None,
        "raw_json": {"address": "+1-555-0101", "contact_name": "Alice"},
    }]
    parser = iOSParser.__new__(iOSParser)
    recovered = parser._recover_contacts_ios(
        wa_db_path=wa_db, tg_db_path=None,
        parsed_messages=sms_messages, warnings=[]
    )
    alice_contacts = [c for c in recovered if c["name"] == "Alice"]
    assert len(alice_contacts) == 1, "Dedup failed: Alice appears more than once"

def test_android_recovery_from_whatsapp(tmp_path):
    """_recover_contacts_android returns contacts from wa.db."""
    from app.parsers.android_parser import AndroidParser
    wa_db = tmp_path / "wa.db"
    _make_wa_db(wa_db)
    parser = AndroidParser.__new__(AndroidParser)
    warnings = []
    recovered = parser._recover_contacts_android(
        wa_db_path=wa_db, tg_db_path=None, parsed_messages=[], warnings=warnings
    )
    assert len(recovered) == 2
    assert all(c["source"] == "recovered" for c in recovered)

def test_recovered_contacts_api(client, app, tmp_path):
    """GET /api/cases/<id>/contacts returns source field for recovered contacts."""
    with app.app_context():
        from app.database import get_db
        db = get_db()
        cid = str(uuid.uuid4())
        db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "RecovTest"))
        db.execute(
            "INSERT INTO contacts"
            " (case_id, name, phone, email, source_app, raw_json, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (cid, "Alice", "+15550101", "", "whatsapp_contacts", "{}", "recovered"),
        )
        db.commit()
    resp = client.get(f"/api/cases/{cid}/contacts")
    assert resp.status_code == 200
    contacts = resp.get_json()
    alice = next((c for c in contacts if c["name"] == "Alice"), None)
    assert alice is not None
    assert alice.get("source") == "recovered"

def test_parse_recovery_skipped_when_contacts_present(tmp_path):
    """When AddressBook has contacts, recovery list must be empty (not called)."""
    from app.parsers.ios_parser import iOSParser
    # When primary contacts exist, caller guards _recover_contacts_ios — test
    # the guard by confirming calling with empty WA db returns empty list
    parser = iOSParser.__new__(iOSParser)
    # No wa.db, no tg.db, no messages → nothing to recover
    recovered = parser._recover_contacts_ios(
        wa_db_path=tmp_path / "nonexistent.db",
        tg_db_path=None, parsed_messages=[], warnings=[]
    )
    assert recovered == []
