"""Dashboard routes — aggregate stats across all cases."""
from __future__ import annotations

import re as _re
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from app.database import get_db
from .analysis import _RISK_RANK, _safe_json_parse

bp_dashboard = Blueprint("dashboard", __name__, url_prefix="/api")

_RANK_TO_LEVEL = {4: "CRITICAL", 3: "HIGH", 2: "MEDIUM", 1: "LOW"}


@bp_dashboard.get("/dashboard/stats")
def dashboard_stats():
    db = get_db()

    # ── All cases ────────────────────────────────────────────────────────────
    cases = [dict(r) for r in db.execute(
        "SELECT id, title, case_number, officer, status, created_at FROM cases ORDER BY created_at DESC"
    ).fetchall()]
    all_case_ids = [c["id"] for c in cases]

    # ── Status pipeline ──────────────────────────────────────────────────────
    status_rows = db.execute("SELECT status, COUNT(*) AS cnt FROM cases GROUP BY status").fetchall()
    status_pipeline = {"open": 0, "in_review": 0, "on_hold": 0, "closed": 0}
    for r in status_rows:
        key = (r["status"] or "open").replace(" ", "_").lower()
        status_pipeline[key] = status_pipeline.get(key, 0) + r["cnt"]

    # ── Artifact counts per case ─────────────────────────────────────────────
    msg_rows = db.execute("SELECT case_id, COUNT(*) AS cnt FROM messages GROUP BY case_id").fetchall()
    call_rows = db.execute("SELECT case_id, COUNT(*) AS cnt FROM call_logs GROUP BY case_id").fetchall()
    contact_rows = db.execute("SELECT case_id, COUNT(*) AS cnt FROM contacts GROUP BY case_id").fetchall()

    artifact_map: dict[str, int] = {}
    for r in msg_rows:
        artifact_map[r["case_id"]] = artifact_map.get(r["case_id"], 0) + r["cnt"]
    for r in call_rows:
        artifact_map[r["case_id"]] = artifact_map.get(r["case_id"], 0) + r["cnt"]
    for r in contact_rows:
        artifact_map[r["case_id"]] = artifact_map.get(r["case_id"], 0) + r["cnt"]

    total_artifacts = sum(artifact_map.values())

    # ── Risk + crime aggregation (Python loop over analysis_results) ─────────
    all_ar = db.execute("SELECT case_id, result FROM analysis_results").fetchall()
    case_risk: dict[str, int] = {}          # case_id -> best rank
    crime_counter: dict[str, int] = {}      # category -> total count
    case_crime_count: dict[str, int] = {}   # case_id -> indicator count

    for row in all_ar:
        parsed = _safe_json_parse(row["result"] or "", _re)
        if not parsed:
            continue
        cl = (parsed.get("confidence_level") or "").upper()
        rank = _RISK_RANK.get(cl, 0)
        if rank > case_risk.get(row["case_id"], 0):
            case_risk[row["case_id"]] = rank
        for ci in (parsed.get("crime_indicators") or []):
            cat = (ci.get("category") or "").upper()
            if cat:
                crime_counter[cat] = crime_counter.get(cat, 0) + 1
                case_crime_count[row["case_id"]] = case_crime_count.get(row["case_id"], 0) + 1

    # Build risk_distribution
    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "NOT_ANALYZED": 0}
    high_risk = 0
    for cid in all_case_ids:
        rank = case_risk.get(cid, 0)
        level = _RANK_TO_LEVEL.get(rank, "NOT_ANALYZED")
        risk_dist[level] += 1
        if rank >= 3:
            high_risk += 1

    total_indicators = sum(crime_counter.values())
    crime_categories = sorted(
        [{"category": k, "count": v} for k, v in crime_counter.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    # ── Recent activity ───────────────────────────────────────────────────────
    ev_rows = db.execute(
        """SELECT 'evidence_imported' AS type, e.case_id, c.title AS case_title,
                  e.format AS detail, e.parsed_at AS ts
           FROM evidence_files e JOIN cases c ON c.id=e.case_id
           WHERE e.parse_status='done' AND e.parsed_at IS NOT NULL
           ORDER BY e.parsed_at DESC LIMIT 20"""
    ).fetchall()

    ar_rows = db.execute(
        """SELECT 'analysis_completed' AS type, ar.case_id, c.title AS case_title,
                  ar.artifact_key AS detail, ar.created_at AS ts
           FROM analysis_results ar JOIN cases c ON c.id=ar.case_id
           ORDER BY ar.created_at DESC LIMIT 20"""
    ).fetchall()

    case_rows = db.execute(
        """SELECT 'case_created' AS type, id AS case_id, title AS case_title,
                  '' AS detail, created_at AS ts
           FROM cases ORDER BY created_at DESC LIMIT 10"""
    ).fetchall()

    activity = []
    for r in list(ev_rows) + list(ar_rows) + list(case_rows):
        activity.append({
            "type": r["type"],
            "case_id": r["case_id"],
            "case_title": r["case_title"],
            "detail": r["detail"],
            "timestamp": r["ts"] or "",
        })
    activity.sort(key=lambda x: x["timestamp"], reverse=True)
    activity = activity[:20]

    # ── Cases table ───────────────────────────────────────────────────────────
    cases_table = []
    for c in cases:
        cid = c["id"]
        rank = case_risk.get(cid, 0)
        cases_table.append({
            "id": cid,
            "title": c["title"],
            "case_number": c["case_number"] or "",
            "officer": c["officer"] or "",
            "status": c["status"] or "open",
            "risk_level": _RANK_TO_LEVEL.get(rank, "NOT_ANALYZED"),
            "crime_count": case_crime_count.get(cid, 0),
            "artifact_count": artifact_map.get(cid, 0),
            "created_at": c["created_at"] or "",
        })

    return jsonify({
        "kpis": {
            "total_cases": len(all_case_ids),
            "high_risk_cases": high_risk,
            "crime_indicators_found": total_indicators,
            "total_artifacts": total_artifacts,
        },
        "risk_distribution": risk_dist,
        "status_pipeline": status_pipeline,
        "crime_categories": crime_categories,
        "recent_activity": activity,
        "cases_table": cases_table,
    })
