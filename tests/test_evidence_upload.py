"""Tests for evidence file upload and parser dispatch."""
import io
import zipfile

import pytest
from app import create_app
from app.database import init_db, close_db


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


def make_ufdr_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Metadata.xml", """<project>
            <model>iPhone 14</model><imei>999</imei><platform>iOS 16</platform>
        </project>""")
    return buf.getvalue()


def test_upload_ufdr(client):
    r = client.post("/api/cases", json={"title": "Test", "officer": "X"})
    case_id = r.get_json()["id"]
    resp = client.post(
        f"/api/cases/{case_id}/evidence",
        data={"file": (io.BytesIO(make_ufdr_bytes()), "test.ufdr")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["format"] == "ufdr"
    assert "iPhone" in data["device_info"]["model"]


def test_upload_unknown_format(client):
    r = client.post("/api/cases", json={"title": "Test2", "officer": "Y"})
    case_id = r.get_json()["id"]
    resp = client.post(
        f"/api/cases/{case_id}/evidence",
        data={"file": (io.BytesIO(b"not a real evidence file"), "mystery.bin")},
        content_type="multipart/form-data",
    )
    # unknown format — dispatch raises ValueError → 422
    assert resp.status_code == 422


def test_upload_no_file(client):
    r = client.post("/api/cases", json={"title": "Test3", "officer": "Z"})
    case_id = r.get_json()["id"]
    resp = client.post(f"/api/cases/{case_id}/evidence", data={},
                       content_type="multipart/form-data")
    assert resp.status_code == 400


def test_upload_case_not_found(client):
    resp = client.post(
        "/api/cases/nonexistent/evidence",
        data={"file": (io.BytesIO(b"x"), "x.ufdr")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 404
