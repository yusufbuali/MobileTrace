"""Evidence annotations CRUD routes."""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from app.database import get_db

bp_annotations = Blueprint("annotations", __name__, url_prefix="/api")

_VALID_TAGS = {"KEY_EVIDENCE", "SUSPICIOUS", "ALIBI", "EXCULPATORY", "NOTE"}


@bp_annotations.get("/cases/<case_id>/annotations")
def list_annotations(case_id: str):
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
        return jsonify({"error": "case not found"}), 404
    rows = db.execute(
        """
        SELECT a.id, a.message_id, a.tag, a.note, a.created_at,
               m.platform, m.thread_id, m.body, m.timestamp, m.direction, m.sender
        FROM annotations a
        JOIN messages m ON a.message_id = m.id
        WHERE a.case_id = ?
        ORDER BY m.timestamp ASC
        """,
        (case_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp_annotations.post("/cases/<case_id>/annotations")
def create_annotation(case_id: str):
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
        return jsonify({"error": "case not found"}), 404

    body = request.get_json(force=True) or {}
    message_id = body.get("message_id")
    tag = (body.get("tag") or "KEY_EVIDENCE").upper()
    note = (body.get("note") or "")[:1000]

    if not message_id:
        return jsonify({"error": "message_id required"}), 400
    if tag not in _VALID_TAGS:
        return jsonify({"error": f"tag must be one of {sorted(_VALID_TAGS)}"}), 400

    # Upsert: delete existing annotation for this message in this case, then insert
    db.execute(
        "DELETE FROM annotations WHERE case_id=? AND message_id=?",
        (case_id, message_id),
    )
    ann_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO annotations (id, case_id, message_id, tag, note) VALUES (?,?,?,?,?)",
        (ann_id, case_id, message_id, tag, note),
    )
    db.commit()
    row = db.execute("SELECT * FROM annotations WHERE id=?", (ann_id,)).fetchone()
    return jsonify(dict(row)), 201


@bp_annotations.patch("/cases/<case_id>/annotations/<ann_id>")
def update_annotation(case_id: str, ann_id: str):
    db = get_db()
    row = db.execute(
        "SELECT * FROM annotations WHERE id=? AND case_id=?", (ann_id, case_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(force=True) or {}
    tag = body.get("tag")
    note = body.get("note")

    if tag is not None:
        tag = tag.upper()
        if tag not in _VALID_TAGS:
            return jsonify({"error": f"tag must be one of {sorted(_VALID_TAGS)}"}), 400
        db.execute("UPDATE annotations SET tag=? WHERE id=?", (tag, ann_id))
    if note is not None:
        db.execute("UPDATE annotations SET note=? WHERE id=?", (note[:1000], ann_id))
    db.commit()
    updated = db.execute("SELECT * FROM annotations WHERE id=?", (ann_id,)).fetchone()
    return jsonify(dict(updated))


@bp_annotations.delete("/cases/<case_id>/annotations/<ann_id>")
def delete_annotation(case_id: str, ann_id: str):
    db = get_db()
    row = db.execute(
        "SELECT id FROM annotations WHERE id=? AND case_id=?", (ann_id, case_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM annotations WHERE id=?", (ann_id,))
    db.commit()
    return jsonify({"deleted": ann_id})
