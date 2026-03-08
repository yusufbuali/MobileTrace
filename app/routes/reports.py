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

    evidence_files = db.execute(
        "SELECT format, source_path, parse_status, parse_error, parsed_at "
        "FROM evidence_files WHERE case_id=? ORDER BY rowid ASC",
        (case_id,),
    ).fetchall()

    # Build executive summary from analysis results
    _summary_parts = []
    for a in analysis:
        p = a.get("result_parsed") or {}
        rsum = p.get("risk_level_summary") or p.get("executive_summary") or p.get("summary")
        if rsum:
            _summary_parts.append(f"**{a['artifact_key'].title()}:** {rsum}")
        elif a.get("result") and not p:
            snippet = str(a["result"])[:300].strip()
            if snippet:
                _summary_parts.append(f"**{a['artifact_key'].title()}:** {snippet}")
    executive_summary = "\n\n".join(_summary_parts)

    # Build conversation excerpts: top 5 threads per platform, last 25 messages each
    _EXCERPT_PLATFORMS = ["whatsapp", "telegram", "signal", "sms"]
    _THREADS_PER_PLATFORM = 5
    _MSGS_PER_THREAD = 25

    conversation_excerpts = []
    for platform in _EXCERPT_PLATFORMS:
        thread_rows = db.execute(
            """
            SELECT COALESCE(thread_id, sender, recipient) AS thread,
                   COUNT(*) AS cnt,
                   MAX(timestamp) AS last_ts
            FROM messages
            WHERE case_id=? AND platform=?
            GROUP BY thread
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (case_id, platform, _THREADS_PER_PLATFORM),
        ).fetchall()
        if not thread_rows:
            continue
        threads = []
        for tr in thread_rows:
            thread_id = tr["thread"]
            msg_rows = db.execute(
                """
                SELECT direction, sender, recipient, body, timestamp
                FROM messages
                WHERE case_id=? AND platform=?
                  AND COALESCE(thread_id, sender, recipient) = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (case_id, platform, thread_id, _MSGS_PER_THREAD),
            ).fetchall()
            msgs_reversed = list(reversed([dict(r) for r in msg_rows]))
            threads.append({
                "thread_id": thread_id,
                "message_count": tr["cnt"],
                "messages": msgs_reversed,
            })
        conversation_excerpts.append({
            "platform": platform,
            "threads": threads,
        })

    # Compute per-artifact DB stats for enhanced display
    _CONFIDENCE_RE = _re.compile(r'\b(CRITICAL|HIGH|MEDIUM|LOW)\b', _re.IGNORECASE)
    per_artifact_enhanced = []
    for a in analysis:
        p = a.get("result_parsed") or {}
        artifact_key = a["artifact_key"]

        if artifact_key in ("sms", "whatsapp", "telegram", "signal"):
            count_row = db.execute(
                "SELECT COUNT(*) AS cnt FROM messages WHERE case_id=? AND platform=?",
                (case_id, artifact_key),
            ).fetchone()
            record_count = count_row["cnt"] if count_row else 0
        elif artifact_key == "call_logs":
            count_row = db.execute(
                "SELECT COUNT(*) AS cnt FROM call_logs WHERE case_id=?", (case_id,)
            ).fetchone()
            record_count = count_row["cnt"] if count_row else 0
        elif artifact_key == "contacts":
            count_row = db.execute(
                "SELECT COUNT(*) AS cnt FROM contacts WHERE case_id=?", (case_id,)
            ).fetchone()
            record_count = count_row["cnt"] if count_row else 0
        else:
            record_count = 0

        if artifact_key in ("sms", "whatsapp", "telegram", "signal"):
            ts_row = db.execute(
                "SELECT MIN(timestamp) AS ts_min, MAX(timestamp) AS ts_max "
                "FROM messages WHERE case_id=? AND platform=? AND timestamp != ''",
                (case_id, artifact_key),
            ).fetchone()
        elif artifact_key == "call_logs":
            ts_row = db.execute(
                "SELECT MIN(timestamp) AS ts_min, MAX(timestamp) AS ts_max "
                "FROM call_logs WHERE case_id=? AND timestamp != ''",
                (case_id,),
            ).fetchone()
        else:
            ts_row = None
        time_start = (ts_row["ts_min"] or "N/A") if ts_row else "N/A"
        time_end = (ts_row["ts_max"] or "N/A") if ts_row else "N/A"

        explicit_conf = p.get("confidence") or p.get("confidence_level") or ""
        result_text = a.get("result") or ""
        if explicit_conf:
            conf_label = explicit_conf.strip().upper()
        else:
            m = _CONFIDENCE_RE.search(result_text)
            conf_label = m.group(1).upper() if m else "UNSPECIFIED"
        conf_class_map = {
            "CRITICAL": "risk-CRITICAL", "HIGH": "risk-HIGH",
            "MEDIUM": "risk-MEDIUM", "LOW": "risk-LOW",
        }
        conf_class = conf_class_map.get(conf_label, "")

        per_artifact_enhanced.append({
            **a,
            "record_count": record_count,
            "time_start": time_start,
            "time_end": time_end,
            "confidence_label": conf_label,
            "confidence_class": conf_class,
        })

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
            "analysis": per_artifact_enhanced,
            "evidence_files": [dict(r) for r in evidence_files],
            "executive_summary": executive_summary,
            "conversation_excerpts": conversation_excerpts,
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
