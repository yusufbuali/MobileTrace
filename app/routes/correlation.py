"""Correlation route — cross-platform contact network and communication heatmap."""
from __future__ import annotations

import json
import re as _re
from datetime import datetime

from flask import Blueprint, jsonify

from app.database import get_db

bp_correlation = Blueprint("correlation", __name__, url_prefix="/api")


def _norm_phone(s: str) -> str:
    """Strip to digits only; handle WhatsApp JIDs like '9731234567@s.whatsapp.net'."""
    if not s:
        return ""
    s = s.split("@")[0]
    s = _re.sub(r"\D", "", s)
    return s[-10:] if len(s) > 10 else s


def _safe_json(s: str) -> dict:
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


@bp_correlation.get("/cases/<case_id>/correlation")
def get_correlation(case_id: str):
    """Return contact network graph, timeline, heatmap, and stats for a case."""
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
        return jsonify({"error": "case not found"}), 404

    msgs = db.execute(
        "SELECT platform, direction, sender, recipient, timestamp, thread_id, body "
        "FROM messages WHERE case_id=? ORDER BY timestamp",
        (case_id,),
    ).fetchall()

    calls = db.execute(
        "SELECT number, direction, duration_s, timestamp, platform "
        "FROM call_logs WHERE case_id=? ORDER BY timestamp",
        (case_id,),
    ).fetchall()

    contacts = db.execute(
        "SELECT name, phone FROM contacts WHERE case_id=?",
        (case_id,),
    ).fetchall()
    name_map: dict[str, str] = {}
    for c in contacts:
        k = _norm_phone(c["phone"] or "")
        if k:
            name_map[k] = c["name"] or c["phone"]

    # LLM analysis results → risk per thread
    all_ar = db.execute(
        "SELECT artifact_key, result FROM analysis_results WHERE case_id=?",
        (case_id,),
    ).fetchall()
    thread_risk: dict[str, dict] = {}
    for row in all_ar:
        parsed = _safe_json(row["result"] or "")
        if not parsed:
            continue
        for t in (parsed.get("conversation_risk_assessment") or []):
            tid = _norm_phone(str(t.get("thread_id") or ""))
            rs = t.get("risk_score") or 0
            rl = (t.get("risk_level") or "LOW").upper()
            if rs > thread_risk.get(tid, {}).get("risk_score", -1):
                thread_risk[tid] = {"risk_score": rs, "risk_level": rl, "categories": []}
        for ci in (parsed.get("crime_indicators") or []):
            cat = (ci.get("category") or "").upper()
            for ref in (ci.get("evidence_refs") or []):
                tid = _norm_phone(str(ref.get("thread_id") or ""))
                if tid in thread_risk:
                    if cat not in thread_risk[tid]["categories"]:
                        thread_risk[tid]["categories"].append(cat)

    DEVICE = "DEVICE"
    nodes: dict[str, dict] = {}
    links: dict[tuple, dict] = {}
    timeline: list[dict] = []
    heatmap_hour = [0] * 24
    heatmap_dow = [0] * 7

    nodes[DEVICE] = {
        "id": DEVICE,
        "label": "Device Owner",
        "platforms": set(),
        "msg_count": 0,
        "call_count": 0,
        "duration_s": 0,
        "is_device_owner": True,
        "risk_level": "NONE",
        "risk_score": 0,
        "categories": [],
        "first_ts": None,
        "last_ts": None,
    }

    def _upsert_node(cid: str, ts: str, platform: str) -> None:
        if cid not in nodes:
            nodes[cid] = {
                "id": cid,
                "label": name_map.get(cid, cid),
                "platforms": set(),
                "msg_count": 0,
                "call_count": 0,
                "duration_s": 0,
                "is_device_owner": False,
                "risk_level": "NONE",
                "risk_score": 0,
                "categories": [],
                "first_ts": ts,
                "last_ts": ts,
            }
        n = nodes[cid]
        n["platforms"].add(platform)
        if ts:
            if not n["first_ts"] or ts < n["first_ts"]:
                n["first_ts"] = ts
            if not n["last_ts"] or ts > n["last_ts"]:
                n["last_ts"] = ts
        ri = thread_risk.get(cid, {})
        if ri.get("risk_score", 0) > n["risk_score"]:
            n["risk_score"] = ri["risk_score"]
            n["risk_level"] = ri["risk_level"]
            n["categories"] = ri["categories"]

    def _upsert_link(a: str, b: str, platform: str, weight: int = 1) -> None:
        key = (min(a, b), max(a, b))
        if key not in links:
            links[key] = {
                "source": key[0],
                "target": key[1],
                "weight": 0,
                "platforms": set(),
                "risk_level": "NONE",
            }
        links[key]["weight"] += weight
        links[key]["platforms"].add(platform)

    for m in msgs:
        ts = m["timestamp"] or ""
        plat = m["platform"]
        contact = _norm_phone(m["sender"] if m["direction"] == "incoming" else m["recipient"])
        if not contact:
            continue
        _upsert_node(contact, ts, plat)
        nodes[DEVICE]["platforms"].add(plat)
        nodes[DEVICE]["msg_count"] += 1
        nodes[contact]["msg_count"] += 1
        _upsert_link(DEVICE, contact, plat)
        timeline.append({
            "ts": ts,
            "type": "message",
            "platform": plat,
            "contact_id": contact,
            "direction": m["direction"],
            "summary": (m["body"] or "")[:80],
        })
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", ""))
                heatmap_hour[dt.hour] += 1
                heatmap_dow[dt.weekday()] += 1
            except Exception:
                pass

    for c in calls:
        ts = c["timestamp"] or ""
        plat = c["platform"] or "phone"
        contact = _norm_phone(c["number"] or "")
        if not contact:
            continue
        _upsert_node(contact, ts, plat)
        nodes[DEVICE]["call_count"] += 1
        nodes[contact]["call_count"] += 1
        nodes[contact]["duration_s"] += c["duration_s"] or 0
        _upsert_link(DEVICE, contact, plat, weight=2)
        timeline.append({
            "ts": ts,
            "type": "call",
            "platform": plat,
            "contact_id": contact,
            "direction": c["direction"],
            "summary": f"{c['duration_s'] or 0}s call",
        })

    # Serialize sets → lists for JSON
    for n in nodes.values():
        n["platforms"] = sorted(n["platforms"])
    for lnk in links.values():
        lnk["platforms"] = sorted(lnk["platforms"])
        src_r = nodes.get(lnk["source"], {}).get("risk_score", 0)
        tgt_r = nodes.get(lnk["target"], {}).get("risk_score", 0)
        max_r = max(src_r, tgt_r)
        lnk["risk_level"] = next(
            (k for k, v in {"CRITICAL": 9, "HIGH": 6, "MEDIUM": 3, "LOW": 1}.items() if max_r >= v),
            "NONE",
        )

    timeline.sort(key=lambda x: x["ts"])

    node_list = list(nodes.values())
    link_list = list(links.values())

    contacts_count = len(node_list) - 1  # exclude DEVICE
    cross_platform = sum(
        1 for n in node_list if not n["is_device_owner"] and len(n["platforms"]) > 1
    )
    high_risk = sum(
        1 for n in node_list if not n["is_device_owner"] and n["risk_level"] in ("HIGH", "CRITICAL")
    )
    total_interactions = sum(lnk["weight"] for lnk in link_list)

    return jsonify({
        "nodes": node_list,
        "links": link_list,
        "timeline": timeline,
        "heatmap": {
            "by_hour": heatmap_hour,
            "by_weekday": heatmap_dow,
        },
        "stats": {
            "total_contacts": contacts_count,
            "cross_platform_contacts": cross_platform,
            "high_risk_contacts": high_risk,
            "total_interactions": total_interactions,
        },
    })
