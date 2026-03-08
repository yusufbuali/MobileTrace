"""Analysis routes — trigger LLM analysis + SSE progress stream + results retrieval."""
from __future__ import annotations

import json
import queue
import threading
from typing import Generator

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from app.analyzer import MobileAnalyzer
from app.database import get_db

bp_analysis = Blueprint("analysis", __name__, url_prefix="/api")

# In-memory queues for SSE: case_id → queue of SSE event strings
_progress_queues: dict[str, "queue.Queue[str | None]"] = {}
_queues_lock = threading.Lock()

_cancel_events: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


def _get_cancel_event(case_id: str) -> threading.Event:
    with _cancel_lock:
        if case_id not in _cancel_events:
            _cancel_events[case_id] = threading.Event()
        return _cancel_events[case_id]


def _get_or_create_queue(case_id: str) -> "queue.Queue[str | None]":
    with _queues_lock:
        if case_id not in _progress_queues:
            _progress_queues[case_id] = queue.Queue(maxsize=200)
        return _progress_queues[case_id]


def _push_event(case_id: str, event_type: str, data: dict) -> None:
    q = _get_or_create_queue(case_id)
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    try:
        q.put_nowait(payload)
    except queue.Full:
        pass


def _close_stream(case_id: str) -> None:
    q = _get_or_create_queue(case_id)
    try:
        q.put_nowait(None)  # sentinel → close stream
    except queue.Full:
        pass


@bp_analysis.post("/cases/<case_id>/analyze")
def trigger_analysis(case_id: str):
    """Start background LLM analysis for selected artifacts in a case."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    # Parse optional artifact filter from request body
    body = request.get_json(silent=True) or {}
    artifact_filter = body.get("artifacts")  # list of keys or None (= all)

    config = current_app.config["MT_CONFIG"]
    cancel_evt = _get_cancel_event(case_id)
    cancel_evt.clear()  # reset from any previous cancel

    def _run():
        def _callback(artifact_key: str, result: dict) -> None:
            _push_event(case_id, "artifact_done", {
                "artifact_key": artifact_key,
                "provider": result.get("provider", ""),
                "error": result.get("error"),
            })

        try:
            analyzer = MobileAnalyzer(config)
            analyzer.analyze_case(
                case_id, get_db(),
                callback=_callback,
                artifact_filter=artifact_filter,
                cancel_event=cancel_evt,
            )
            if cancel_evt.is_set():
                _push_event(case_id, "cancelled", {"case_id": case_id})
            else:
                _push_event(case_id, "complete", {"case_id": case_id})
        except Exception as exc:
            _push_event(case_id, "error", {"message": str(exc)})
        finally:
            _close_stream(case_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"case_id": case_id, "status": "started"}), 202


@bp_analysis.get("/cases/<case_id>/analysis/preview")
def analysis_preview(case_id: str):
    """Return per-artifact data counts so the UI can show what will be analyzed."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    # Evidence files
    evidence = [
        dict(r) for r in db.execute(
            "SELECT id, format, source_path, parse_status FROM evidence_files WHERE case_id=?",
            (case_id,),
        ).fetchall()
    ]

    # Per-platform message counts (single query)
    msg_counts = {p: 0 for p in ("sms", "whatsapp", "telegram", "signal")}
    for row in db.execute(
        "SELECT platform, COUNT(*) as c FROM messages WHERE case_id=? GROUP BY platform",
        (case_id,),
    ).fetchall():
        if row["platform"] in msg_counts:
            msg_counts[row["platform"]] = row["c"]

    # Call log count
    call_count = db.execute(
        "SELECT COUNT(*) as c FROM call_logs WHERE case_id=?", (case_id,)
    ).fetchone()["c"]

    # Contact count
    contact_count = db.execute(
        "SELECT COUNT(*) as c FROM contacts WHERE case_id=?", (case_id,)
    ).fetchone()["c"]

    artifacts = []
    for platform in ("sms", "whatsapp", "telegram", "signal"):
        artifacts.append({
            "key": platform,
            "label": platform.upper() if platform == "sms" else platform.title(),
            "type": "messages",
            "count": msg_counts[platform],
        })
    artifacts.append({"key": "call_logs", "label": "Call Logs", "type": "calls", "count": call_count})
    artifacts.append({"key": "contacts", "label": "Contacts", "type": "contacts", "count": contact_count})

    return jsonify({
        "evidence": evidence,
        "artifacts": artifacts,
        "total_messages": sum(msg_counts.values()),
        "total_calls": call_count,
        "total_contacts": contact_count,
    })


@bp_analysis.post("/cases/<case_id>/analysis/cancel")
def cancel_analysis(case_id: str):
    """Signal the running analysis to stop after current artifact."""
    evt = _get_cancel_event(case_id)
    evt.set()
    _push_event(case_id, "cancelled", {"case_id": case_id})
    _close_stream(case_id)
    return jsonify({"status": "cancel_requested"}), 200


@bp_analysis.get("/cases/<case_id>/analysis/stream")
def analysis_stream(case_id: str):
    """SSE endpoint — streams analysis progress events for a case."""
    q = _get_or_create_queue(case_id)

    def _generate() -> Generator[str, None, None]:
        yield "event: connected\ndata: {}\n\n"
        while True:
            try:
                event = q.get(timeout=30)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if event is None:  # sentinel
                break
            yield event

    return Response(
        stream_with_context(_generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@bp_analysis.get("/cases/<case_id>/analysis")
def get_analysis(case_id: str):
    """Return all analysis results for a case."""
    import re as _re
    db = get_db()
    rows = db.execute(
        "SELECT artifact_key, result, provider, created_at FROM analysis_results "
        "WHERE case_id=? ORDER BY created_at ASC",
        (case_id,),
    ).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        row["result_parsed"] = _safe_json_parse(row.get("result") or "", _re)
        out.append(row)
    return jsonify(out)


def _safe_json_parse(s: str, re_mod) -> dict | None:
    """Try JSON parse; on failure apply common LLM formatting fixes and retry."""
    s = s.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        pass
    # Fix {"key": "stringval": number} → {"key": "stringval"}
    cleaned = re_mod.sub(r'":\s*"([^"\\]*)"\s*:\s*[\d.]+', r'": "\1"', s)
    # Remove trailing commas before } or ]
    cleaned = re_mod.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        return None
