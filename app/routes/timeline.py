"""GET /api/cases/<id>/timeline — chronological cross-platform event feed."""
import json
from flask import Blueprint, jsonify, request, abort
from app.database import get_db

bp_timeline = Blueprint("timeline", __name__, url_prefix="/api")


def _platform_risk_map(db, case_id: str) -> dict[str, str]:
    """Return {platform: 'HIGH'|'CRITICAL'} from the most recent analysis per artifact."""
    risk_map: dict[str, str] = {}
    seen: set[str] = set()
    for row in db.execute(
        "SELECT artifact_key, result FROM analysis_results"
        " WHERE case_id=? ORDER BY created_at DESC",
        (case_id,),
    ).fetchall():
        ak = row["artifact_key"] or ""
        if ak in seen:
            continue
        seen.add(ak)
        try:
            parsed = json.loads(row["result"] or "null") or {}
            rl = (parsed.get("risk_level") or "").upper()
            if rl in ("HIGH", "CRITICAL"):
                platform = ak.split("_")[0]
                risk_map.setdefault(platform, rl)
        except Exception:
            pass
    return risk_map


@bp_timeline.get("/cases/<case_id>/timeline")
def get_timeline(case_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone():
        abort(404)

    limit = min(int(request.args.get("limit", 100)), 500)
    cursor_ts  = request.args.get("cursor_ts", "")
    cursor_key = request.args.get("cursor_key", "")
    platforms_raw = request.args.get("platforms", "")
    platform_filter = [p.strip() for p in platforms_raw.split(",") if p.strip()]

    # row_key is namespaced to prevent id collision between messages and call_logs
    # (both tables use INTEGER PRIMARY KEY AUTOINCREMENT starting from 1)
    msg_sql = (
        "SELECT id, 'message' AS type, platform, timestamp, direction,"
        "       sender, recipient, body, thread_id,"
        "       'msg-' || id AS row_key"
        " FROM messages WHERE case_id=:cid"
    )
    call_sql = (
        "SELECT id, 'call' AS type, platform, timestamp, direction,"
        "       CASE WHEN direction='incoming' THEN number ELSE NULL END AS sender,"
        "       CASE WHEN direction='outgoing' THEN number ELSE NULL END AS recipient,"
        "       NULL AS body, NULL AS thread_id,"
        "       'call-' || id AS row_key"
        " FROM call_logs WHERE case_id=:cid"
    )

    params: dict = {"cid": case_id}

    if platform_filter:
        ph = ",".join(f":pf{i}" for i in range(len(platform_filter)))
        msg_sql  += f" AND platform IN ({ph})"
        call_sql += f" AND platform IN ({ph})"
        for i, pf in enumerate(platform_filter):
            params[f"pf{i}"] = pf

    sql = f"SELECT * FROM ({msg_sql} UNION ALL {call_sql})"

    if cursor_ts and cursor_key:
        sql += (
            " WHERE (timestamp > :cur_ts)"
            " OR (timestamp = :cur_ts AND row_key > :cur_key)"
        )
        params["cur_ts"]  = cursor_ts
        params["cur_key"] = cursor_key

    sql += " ORDER BY timestamp ASC, row_key ASC LIMIT :lim"
    params["lim"] = limit + 1  # fetch one extra to detect next page

    rows = db.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]

    risk_map = _platform_risk_map(db, case_id)

    items = []
    for r in rows:
        item = {
            "id":       r["id"],
            "type":     r["type"],
            "platform": r["platform"],
            "timestamp": r["timestamp"],
            "direction": r["direction"],
            "sender":   r["sender"],
            "recipient": r["recipient"],
            "body":     r["body"],
            "thread_id": r["thread_id"],
            "row_key":  r["row_key"],
            "risk_level": risk_map.get(r["platform"]),
        }
        if r["type"] == "call":
            cl = db.execute(
                "SELECT duration_s FROM call_logs WHERE id=?", (r["id"],)
            ).fetchone()
            item["duration_seconds"] = cl["duration_s"] if cl else None
        items.append(item)

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = {"ts": last["timestamp"], "key": last["row_key"]}

    return jsonify({"items": items, "next_cursor": next_cursor})
