"""GET /api/cases/<id>/media/<media_id> — stream extracted media files (A4)."""
from pathlib import Path
from flask import Blueprint, abort, current_app, send_file
from app.database import get_db

bp_media = Blueprint("media", __name__, url_prefix="/api")

@bp_media.get("/cases/<case_id>/media/<media_id>")
def get_media(case_id, media_id):
    db = get_db()
    # UUID lookup — no path traversal possible
    row = db.execute(
        "SELECT filepath, mime_type FROM media_files WHERE id=? AND case_id=?",
        (media_id, case_id),
    ).fetchone()
    if not row:
        abort(404)

    cfg = current_app.config["MT_CONFIG"]
    cases_dir = Path(cfg["server"]["cases_dir"])
    full_path = cases_dir / row["filepath"]
    if not full_path.exists():
        abort(404)

    resp = send_file(full_path, mimetype=row["mime_type"])
    resp.headers["Cache-Control"] = "max-age=86400, immutable"
    return resp
