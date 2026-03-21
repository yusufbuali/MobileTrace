"""CRUD tests for /api/cases/<id>/annotations."""
import json
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


def _make_case(client):
    r = client.post("/api/cases", json={"title": "Ann Test", "officer": "Det"})
    assert r.status_code == 201
    return r.get_json()["id"]


def _seed_message(case_id) -> int:
    """Insert a message directly and return its integer id."""
    db = get_db()
    db.execute(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp) "
        "VALUES (?,?,?,?,?,?,?)",
        (case_id, "whatsapp", "incoming", "Alice", "device", "Suspicious text", "2024-01-01T10:00:00"),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_annotation(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    r = client.post(
        f"/api/cases/{case_id}/annotations",
        json={"message_id": msg_id, "tag": "KEY_EVIDENCE", "note": "Important message"},
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data["tag"] == "KEY_EVIDENCE"
    assert data["note"] == "Important message"
    assert "id" in data


def test_create_annotation_missing_message_id(client):
    case_id = _make_case(client)
    r = client.post(f"/api/cases/{case_id}/annotations", json={"tag": "NOTE"})
    assert r.status_code == 400


def test_create_annotation_invalid_tag(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    r = client.post(
        f"/api/cases/{case_id}/annotations",
        json={"message_id": msg_id, "tag": "INVALID_TAG"},
    )
    assert r.status_code == 400


def test_create_annotation_404_case(client):
    r = client.post("/api/cases/nope/annotations", json={"message_id": 1, "tag": "NOTE"})
    assert r.status_code == 404


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_annotations_empty(client):
    case_id = _make_case(client)
    r = client.get(f"/api/cases/{case_id}/annotations")
    assert r.status_code == 200
    assert r.get_json() == []


def test_list_annotations_returns_message_fields(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    client.post(f"/api/cases/{case_id}/annotations",
                json={"message_id": msg_id, "tag": "SUSPICIOUS", "note": "x"})
    r = client.get(f"/api/cases/{case_id}/annotations")
    data = r.get_json()
    assert len(data) == 1
    ann = data[0]
    for field in ("id", "message_id", "tag", "note", "created_at",
                  "platform", "thread_id", "body", "timestamp", "direction"):
        assert field in ann, f"missing field: {field}"


# ── Upsert (duplicate) ────────────────────────────────────────────────────────

def test_upsert_annotation_replaces(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    client.post(f"/api/cases/{case_id}/annotations",
                json={"message_id": msg_id, "tag": "NOTE", "note": "first"})
    client.post(f"/api/cases/{case_id}/annotations",
                json={"message_id": msg_id, "tag": "KEY_EVIDENCE", "note": "updated"})
    r = client.get(f"/api/cases/{case_id}/annotations")
    data = r.get_json()
    assert len(data) == 1   # not duplicated
    assert data[0]["tag"] == "KEY_EVIDENCE"
    assert data[0]["note"] == "updated"


# ── Patch ─────────────────────────────────────────────────────────────────────

def test_patch_annotation(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    r = client.post(f"/api/cases/{case_id}/annotations",
                    json={"message_id": msg_id, "tag": "NOTE", "note": "old"})
    ann_id = r.get_json()["id"]
    r2 = client.patch(f"/api/cases/{case_id}/annotations/{ann_id}",
                      json={"note": "updated note"})
    assert r2.status_code == 200
    assert r2.get_json()["note"] == "updated note"


def test_patch_annotation_404(client):
    case_id = _make_case(client)
    r = client.patch(f"/api/cases/{case_id}/annotations/nonexistent", json={"note": "x"})
    assert r.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_annotation(client):
    case_id = _make_case(client)
    msg_id = _seed_message(case_id)
    r = client.post(f"/api/cases/{case_id}/annotations",
                    json={"message_id": msg_id, "tag": "NOTE"})
    ann_id = r.get_json()["id"]
    r2 = client.delete(f"/api/cases/{case_id}/annotations/{ann_id}")
    assert r2.status_code == 200
    # Verify gone
    r3 = client.get(f"/api/cases/{case_id}/annotations")
    assert r3.get_json() == []


def test_delete_annotation_404(client):
    case_id = _make_case(client)
    r = client.delete(f"/api/cases/{case_id}/annotations/nonexistent")
    assert r.status_code == 404
