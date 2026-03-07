"""Case CRUD routes for MobileTrace."""
from __future__ import annotations

import uuid
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from app.database import get_db

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
