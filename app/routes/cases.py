"""Case CRUD routes for MobileTrace."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request

from app.database import get_db
from app.parsers.dispatcher import dispatch, detect_format

bp_cases = Blueprint("cases", __name__, url_prefix="/api")


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


@bp_cases.get("/")
def index():
    return render_template("index.html")


@bp_cases.post("/cases")
def create_case():
    body = request.get_json() or {}
    title = body.get("title", "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    case_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        """INSERT INTO cases (id, title, case_number, officer, status)
           VALUES (?, ?, ?, ?, 'open')""",
        (case_id, title, body.get("case_number"), body.get("officer")),
    )
    db.commit()
    row = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    return jsonify(_row_to_dict(row)), 201


@bp_cases.get("/cases")
def list_cases():
    status = request.args.get("status")
    db = get_db()
    if status:
        rows = db.execute(
            "SELECT * FROM cases WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM cases ORDER BY created_at DESC"
        ).fetchall()
    return jsonify([_row_to_dict(r) for r in rows])


@bp_cases.get("/cases/<case_id>")
def get_case(case_id: str):
    row = get_db().execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(_row_to_dict(row))


@bp_cases.patch("/cases/<case_id>")
def update_case(case_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    body = request.get_json() or {}
    allowed = {"title", "status", "officer", "case_number", "device_info"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return jsonify({"error": "no valid fields"}), 400
    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    db.execute(
        f"UPDATE cases SET {set_clause} WHERE id=?",
        (*updates.values(), case_id),
    )
    db.commit()
    updated = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    return jsonify(_row_to_dict(updated))


@bp_cases.delete("/cases/<case_id>")
def delete_case(case_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM cases WHERE id=?", (case_id,))
    db.commit()
    return jsonify({"deleted": case_id})


@bp_cases.post("/cases/<case_id>/evidence")
def upload_evidence(case_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400

    f = request.files["file"]
    cfg = current_app.config["MT_CONFIG"]
    cases_dir = Path(cfg["server"]["cases_dir"])
    case_dir = cases_dir / case_id
    evidence_dir = case_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(f.filename).name
    dest_path = evidence_dir / safe_name
    f.save(dest_path)

    fmt = detect_format(dest_path) or "unknown"
    ev_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO evidence_files (id, case_id, format, source_path, parse_status) VALUES (?,?,?,?,?)",
        (ev_id, case_id, fmt, str(dest_path), "parsing"),
    )
    db.commit()

    try:
        extract_dir = case_dir / "extracted"
        parsed = dispatch(dest_path, extract_dir)
        _store_parsed(db, case_id, parsed)
        db.execute(
            "UPDATE evidence_files SET parse_status='done', parsed_at=datetime('now') WHERE id=?",
            (ev_id,),
        )
        db.execute(
            "UPDATE cases SET device_info=?, updated_at=datetime('now') WHERE id=?",
            (json.dumps(parsed.device_info), case_id),
        )
        db.commit()
        return jsonify({
            "evidence_id": ev_id,
            "format": fmt,
            "device_info": parsed.device_info,
            "stats": {
                "contacts": len(parsed.contacts),
                "messages": len(parsed.messages),
                "calls": len(parsed.call_logs),
            },
        }), 201
    except Exception as exc:
        db.execute(
            "UPDATE evidence_files SET parse_status='error', parse_error=? WHERE id=?",
            (str(exc), ev_id),
        )
        db.commit()
        return jsonify({"error": str(exc)}), 422


def _store_parsed(db, case_id: str, parsed) -> None:
    """Insert ParsedCase artifacts into DB tables."""
    for c in parsed.contacts:
        db.execute(
            "INSERT INTO contacts (case_id, name, phone, email, source_app, raw_json) VALUES (?,?,?,?,?,?)",
            (case_id, c["name"], c["phone"], c["email"], c["source_app"], json.dumps(c["raw_json"])),
        )
    for m in parsed.messages:
        db.execute(
            "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (case_id, m["platform"], m["direction"], m["sender"], m["recipient"],
             m["body"], m["timestamp"], m["thread_id"], json.dumps(m["raw_json"])),
        )
    for cl in parsed.call_logs:
        db.execute(
            "INSERT INTO call_logs (case_id, number, direction, duration_s, timestamp, platform) VALUES (?,?,?,?,?,?)",
            (case_id, cl["number"], cl["direction"], cl["duration_s"], cl["timestamp"], cl["platform"]),
        )
    db.commit()
