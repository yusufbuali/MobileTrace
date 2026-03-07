"""Reports routes — HTML court-ready report + linkage graph data."""
from __future__ import annotations

import json
import re as _re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template

from app.database import get_db
from app.rtl_support import augment_report_context
from app.routes.analysis import _safe_json_parse

bp_reports = Blueprint("reports", __name__, url_prefix="/api")


@bp_reports.get("/cases/<case_id>/report")
def get_report(case_id: str):
    """Render a court-ready HTML report for the case."""
    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not case:
        return jsonify({"error": "not found"}), 404

    case_dict = dict(case)
    try:
        case_dict["device_info"] = json.loads(case_dict.get("device_info") or "{}")
    except Exception:
        case_dict["device_info"] = {}

    messages = db.execute(
        "SELECT platform, direction, sender, recipient, body, timestamp "
        "FROM messages WHERE case_id=? ORDER BY timestamp ASC LIMIT 1000",
        (case_id,),
    ).fetchall()

    contacts = db.execute(
        "SELECT name, phone, email, source_app FROM contacts WHERE case_id=? ORDER BY name ASC",
        (case_id,),
    ).fetchall()

    calls = db.execute(
        "SELECT number, direction, duration_s, timestamp, platform "
        "FROM call_logs WHERE case_id=? ORDER BY timestamp ASC",
        (case_id,),
    ).fetchall()

    analysis_rows = db.execute(
        "SELECT artifact_key, result, provider, created_at "
        "FROM analysis_results WHERE case_id=? ORDER BY created_at ASC",
        (case_id,),
    ).fetchall()

    analysis = []
    for r in analysis_rows:
        row = dict(r)
        row["result_parsed"] = _safe_json_parse(row.get("result") or "", _re)
        analysis.append(row)

    stats = {
        "messages": len(messages),
        "contacts": len(contacts),
        "calls": len(calls),
        "analyses": len(analysis),
    }

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    ctx = augment_report_context(
        {
            "case": case_dict,
            "messages": [dict(r) for r in messages],
            "contacts": [dict(r) for r in contacts],
            "calls": [dict(r) for r in calls],
            "analysis": [dict(r) for r in analysis],
            "stats": stats,
            "generated_at": generated_at,
        },
        case_name=case_dict.get("title", ""),
    )
    return render_template("report.html", **ctx)


@bp_reports.get("/cases/<case_id>/graph")
def get_graph_data(case_id: str):
    """Return nodes + edges for the D3.js contact linkage graph."""
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
        return jsonify({"error": "not found"}), 404

    # Build nodes from contacts
    node_map: dict[str, dict] = {}
    for c in db.execute(
        "SELECT name, phone FROM contacts WHERE case_id=?", (case_id,)
    ).fetchall():
        phone = (c["phone"] or "").strip()
        if phone:
            node_map[phone] = {"id": phone, "label": c["name"] or phone, "type": "contact"}

    # Build edges from messages (unique sender↔recipient pairs with counts)
    edge_map: dict[tuple, int] = {}
    for m in db.execute(
        "SELECT sender, recipient FROM messages WHERE case_id=?", (case_id,)
    ).fetchall():
        src = m["sender"] or ""
        dst = m["recipient"] or ""
        if src and dst and src != "device" and dst != "device":
            key = tuple(sorted([src, dst]))
            edge_map[key] = edge_map.get(key, 0) + 1
        # Ensure both endpoints appear as nodes
        for num in (src, dst):
            if num and num != "device" and num not in node_map:
                node_map[num] = {"id": num, "label": num, "type": "number"}

    # Build edges from calls
    for cl in db.execute(
        "SELECT number FROM call_logs WHERE case_id=?", (case_id,)
    ).fetchall():
        num = cl["number"] or ""
        if num:
            if num not in node_map:
                node_map[num] = {"id": num, "label": num, "type": "number"}
            key = tuple(sorted(["device", num]))
            edge_map[key] = edge_map.get(key, 0) + 1

    # Add device owner node if any edges exist
    if edge_map:
        node_map["device"] = {"id": "device", "label": "Device Owner", "type": "device"}

    nodes = list(node_map.values())
    edges = [{"source": k[0], "target": k[1], "weight": v} for k, v in edge_map.items()]

    return jsonify({"nodes": nodes, "edges": edges})


# ── Count endpoints used by the dashboard stats ───────────────────────────────

@bp_reports.get("/cases/<case_id>/messages/count")
def messages_count(case_id: str):
    db = get_db()
    row = db.execute("SELECT COUNT(*) AS count FROM messages WHERE case_id=?", (case_id,)).fetchone()
    return jsonify({"count": row["count"]})


@bp_reports.get("/cases/<case_id>/contacts/count")
def contacts_count(case_id: str):
    db = get_db()
    row = db.execute("SELECT COUNT(*) AS count FROM contacts WHERE case_id=?", (case_id,)).fetchone()
    return jsonify({"count": row["count"]})


@bp_reports.get("/cases/<case_id>/calls/count")
def calls_count(case_id: str):
    db = get_db()
    row = db.execute("SELECT COUNT(*) AS count FROM call_logs WHERE case_id=?", (case_id,)).fetchone()
    return jsonify({"count": row["count"]})


@bp_reports.get("/cases/<case_id>/evidence")
def list_evidence(case_id: str):
    db = get_db()
    rows = db.execute(
        "SELECT id, format, source_path, parse_status, parse_error, parsed_at "
        "FROM evidence_files WHERE case_id=? ORDER BY rowid ASC",
        (case_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])
