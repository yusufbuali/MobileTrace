"""Tests for media file serving and _store_parsed media arm (A4)."""
import uuid
from pathlib import Path

def test_media_route_streams_file(client, app, tmp_path):
    with app.app_context():
        from app.database import get_db
        from flask import current_app
        db = get_db()
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "MediaTest"))

        cfg = current_app.config["MT_CONFIG"]
        cases_dir = Path(cfg["server"]["cases_dir"])
        media_path = cases_dir / cid / "media"
        media_path.mkdir(parents=True, exist_ok=True)
        fake_file = media_path / f"{mid}.jpg"
        fake_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

        db.execute(
            "INSERT INTO media_files (id, case_id, message_id, filename,"
            " mime_type, size_bytes, filepath) VALUES (?,?,?,?,?,?,?)",
            (mid, cid, None, "photo.jpg", "image/jpeg", 24,
             f"{cid}/media/{mid}.jpg"),
        )
        db.commit()

    resp = client.get(f"/api/cases/{cid}/media/{mid}")
    assert resp.status_code == 200
    assert "image/jpeg" in resp.content_type

def test_media_route_404_wrong_case(client, app):
    """media_id belonging to case A must 404 when requested under case B."""
    with app.app_context():
        from app.database import get_db
        from flask import current_app
        db = get_db()
        cid_a = str(uuid.uuid4())
        cid_b = str(uuid.uuid4())
        mid   = str(uuid.uuid4())
        db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid_a, "A"))
        db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid_b, "B"))

        cfg = current_app.config["MT_CONFIG"]
        cases_dir = Path(cfg["server"]["cases_dir"])
        media_path = cases_dir / cid_a / "media"
        media_path.mkdir(parents=True, exist_ok=True)
        fake = media_path / f"{mid}.jpg"
        fake.write_bytes(b"\xff\xd8\xff")

        db.execute(
            "INSERT INTO media_files (id, case_id, message_id, filename,"
            " mime_type, size_bytes, filepath) VALUES (?,?,?,?,?,?,?)",
            (mid, cid_a, None, "photo.jpg", "image/jpeg", 3,
             f"{cid_a}/media/{mid}.jpg"),
        )
        db.commit()

    # Request mid under cid_b — must 404
    resp = client.get(f"/api/cases/{cid_b}/media/{mid}")
    assert resp.status_code == 404

def test_media_route_404_missing_file(client, app):
    """Return 404 if DB row exists but file is missing from disk."""
    with app.app_context():
        from app.database import get_db
        db = get_db()
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "Ghost"))
        db.execute(
            "INSERT INTO media_files (id, case_id, message_id, filename,"
            " mime_type, size_bytes, filepath) VALUES (?,?,?,?,?,?,?)",
            (mid, cid, None, "ghost.jpg", "image/jpeg", 100,
             f"{cid}/media/{mid}.jpg"),  # file not on disk
        )
        db.commit()
    resp = client.get(f"/api/cases/{cid}/media/{mid}")
    assert resp.status_code == 404

def test_store_parsed_skips_large_media(app, tmp_path):
    """_store_parsed() must not insert media_files rows > 50 MB."""
    with app.app_context():
        from app.database import get_db
        from app.routes.cases import _store_parsed
        from app.parsers.base import ParsedCase
        db = get_db()
        cid = str(uuid.uuid4())
        db.execute("INSERT INTO cases (id, title) VALUES (?,?)", (cid, "BigMedia"))
        db.commit()

        fake = tmp_path / "big.mp4"
        fake.write_bytes(b"x" * 100)
        parsed = ParsedCase(format="test")
        parsed.media_files = [{
            "message_id": None, "filename": "big.mp4",
            "mime_type": "video/mp4",
            "size_bytes": 60 * 1024 * 1024,  # > 50 MB limit
            "tmp_path": str(fake),
        }]
        _store_parsed(db, cid, parsed)
        rows = db.execute("SELECT * FROM media_files WHERE case_id=?", (cid,)).fetchall()
        assert len(rows) == 0, "Large file should have been skipped"
