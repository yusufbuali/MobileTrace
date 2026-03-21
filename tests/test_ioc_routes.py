"""Smoke tests for GET /api/cases/<case_id>/ioc endpoint."""
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
    """Case with messages containing known IOCs."""
    r = client.post("/api/cases", json={"title": "IOC Test Case", "officer": "Smith"})
    case_id = r.get_json()["id"]
    db = get_db()
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            case_id,
            "whatsapp",
            "incoming",
            "+97312345678",
            "device",
            "Call me on +97312345678 or email test@example.com",
            "2024-01-01T10:00:00",
            "thread_1",
            "{}",
        ),
    )
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            case_id,
            "sms",
            "outgoing",
            "device",
            "+97312345678",
            "Check https://example.com for details",
            "2024-01-03T14:30:00",
            "thread_1",
            "{}",
        ),
    )
    db.execute(
        "INSERT INTO contacts (case_id, name, phone, email, source_app, raw_json) VALUES (?,?,?,?,?,?)",
        (case_id, "Ali", "+97399999999", "ali@contact.com", "android_contacts", "{}"),
    )
    db.commit()
    return case_id


@pytest.fixture
def empty_case(client):
    """Case with no messages or contacts."""
    r = client.post("/api/cases", json={"title": "Empty Case", "officer": "Jones"})
    return r.get_json()["id"]


# 1. GET /ioc returns 200 and JSON with "iocs" + "summary" keys for a case with messages
def test_ioc_returns_200_with_correct_keys(client, case_with_messages):
    resp = client.get(f"/api/cases/{case_with_messages}/ioc")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "iocs" in data
    assert "summary" in data


# 2. GET /ioc returns empty iocs list for case with no messages
def test_ioc_empty_case_returns_empty_list(client, empty_case):
    resp = client.get(f"/api/cases/{empty_case}/ioc")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["iocs"] == []
    assert data["summary"]["total"] == 0


# 3. GET /ioc?type=phone returns only phone IOCs
def test_ioc_type_filter_phone_only(client, case_with_messages):
    resp = client.get(f"/api/cases/{case_with_messages}/ioc?type=phone")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["iocs"]) > 0
    for ioc in data["iocs"]:
        assert ioc["type"] == "phone"


# 4. GET /ioc returns 404 for non-existent case_id
def test_ioc_404_for_nonexistent_case(client):
    resp = client.get("/api/cases/does-not-exist/ioc")
    assert resp.status_code == 404


# 5. GET /ioc includes IOCs from contacts
def test_ioc_includes_contact_iocs(client, case_with_messages):
    resp = client.get(f"/api/cases/{case_with_messages}/ioc?type=phone")
    data = resp.get_json()
    phone_values = [ioc["value"] for ioc in data["iocs"]]
    # +97399999999 comes exclusively from the contact record
    assert any("97399999999" in v for v in phone_values)


# 6. Summary "total" matches len(iocs)
def test_ioc_summary_total_matches_iocs_length(client, case_with_messages):
    resp = client.get(f"/api/cases/{case_with_messages}/ioc")
    data = resp.get_json()
    assert data["summary"]["total"] == len(data["iocs"])
