"""IOC extraction route for MobileTrace."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.database import get_db
from app.ioc_extractor import extract_iocs

bp_ioc = Blueprint("ioc", __name__, url_prefix="/api")


@bp_ioc.get("/cases/<case_id>/ioc")
def get_iocs(case_id: str):
    db = get_db()

    # 1. Verify case exists
    case = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if case is None:
        return jsonify({"error": "Case not found"}), 404

    # 2. Load messages
    rows = db.execute(
        "SELECT id, platform, thread_id, body, timestamp, direction "
        "FROM messages WHERE case_id=?",
        (case_id,),
    ).fetchall()
    messages = [dict(r) for r in rows]

    # 3. Load contacts
    rows = db.execute(
        "SELECT id, name, phone, email FROM contacts WHERE case_id=?",
        (case_id,),
    ).fetchall()
    contacts = [dict(r) for r in rows]

    # 4. Extract IOCs (with optional type filter)
    ioc_type_filter = request.args.get("type", "")
    result = extract_iocs(messages, contacts, ioc_type_filter=ioc_type_filter)

    # 5. Return JSON
    return jsonify(result)
