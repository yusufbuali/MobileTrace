"""Tests for case CRUD API endpoints."""
import pytest
from app import create_app
from app.database import init_db, close_db


@pytest.fixture
def client(tmp_path):
    app = create_app(testing=True)
    app.config["MT_CONFIG"]["server"]["database_path"] = str(tmp_path / "test.db")
    init_db(str(tmp_path / "test.db"))
    app.config["MT_CONFIG"]["server"]["cases_dir"] = str(tmp_path / "cases")
    with app.test_client() as c:
        yield c
    close_db()


def test_create_case(client):
    resp = client.post("/api/cases", json={
        "title": "Drug Investigation",
        "officer": "Det. Smith",
        "case_number": "CID-2026-001",
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["title"] == "Drug Investigation"
    assert "id" in data


def test_list_cases(client):
    client.post("/api/cases", json={"title": "Case A", "officer": "Smith"})
    client.post("/api/cases", json={"title": "Case B", "officer": "Jones"})
    resp = client.get("/api/cases")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 2


def test_get_case(client):
    r = client.post("/api/cases", json={"title": "My Case", "officer": "X"})
    case_id = r.get_json()["id"]
    resp = client.get(f"/api/cases/{case_id}")
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "My Case"


def test_get_case_not_found(client):
    resp = client.get("/api/cases/nonexistent")
    assert resp.status_code == 404


def test_update_case_status(client):
    r = client.post("/api/cases", json={"title": "Case X", "officer": "Y"})
    case_id = r.get_json()["id"]
    resp = client.patch(f"/api/cases/{case_id}", json={"status": "closed"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "closed"


def test_delete_case(client):
    r = client.post("/api/cases", json={"title": "Delete Me", "officer": "Z"})
    case_id = r.get_json()["id"]
    resp = client.delete(f"/api/cases/{case_id}")
    assert resp.status_code == 200
    assert client.get(f"/api/cases/{case_id}").status_code == 404
