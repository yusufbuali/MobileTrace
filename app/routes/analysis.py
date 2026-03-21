"""Analysis routes — trigger LLM analysis + SSE progress stream + results retrieval."""
from __future__ import annotations

import json
import queue
import threading
import uuid
from typing import Generator

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from app.analyzer import MobileAnalyzer
from app.database import get_db

bp_analysis = Blueprint("analysis", __name__, url_prefix="/api")

_RISK_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

# In-memory queues for SSE: case_id → queue of SSE event strings
_progress_queues: dict[str, "queue.Queue[str | None]"] = {}
_queues_lock = threading.Lock()

# Per-run queues for multi-model SSE: run_id → queue
_run_queues: dict[str, "queue.Queue[str | None]"] = {}
_run_queues_lock = threading.Lock()

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


def _get_or_create_run_queue(run_id: str) -> "queue.Queue[str | None]":
    with _run_queues_lock:
        if run_id not in _run_queues:
            _run_queues[run_id] = queue.Queue(maxsize=500)
        return _run_queues[run_id]


def _push_run_event(run_id: str, event_type: str, data: dict) -> None:
    q = _get_or_create_run_queue(run_id)
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    try:
        q.put_nowait(payload)
    except queue.Full:
        pass


def _close_run_stream(run_id: str) -> None:
    q = _get_or_create_run_queue(run_id)
    try:
        q.put_nowait(None)
    except queue.Full:
        pass


@bp_analysis.post("/cases/<case_id>/analyze/multi")
def trigger_multi_analysis(case_id: str):
    """Start a multi-model analysis run (2–5 OpenRouter models)."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    body = request.get_json(silent=True) or {}
    models = body.get("models")
    artifact_filter = body.get("artifacts")  # list or None

    if not models or not isinstance(models, list):
        return jsonify({"error": "models list required"}), 400
    if len(models) < 2 or len(models) > 5:
        return jsonify({"error": "select 2–5 models"}), 400

    run_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO analysis_runs (id, case_id, models, status, artifact_filter) VALUES (?,?,?,?,?)",
        (run_id, case_id, json.dumps(models),
         "running",
         json.dumps(artifact_filter) if artifact_filter else None),
    )
    db.commit()

    config = current_app.config["MT_CONFIG"]
    cancel_evt = threading.Event()

    def _run():
        def _callback(event_type: str, data: dict) -> None:
            _push_run_event(run_id, event_type, data)

        try:
            analyzer = MobileAnalyzer(config)
            analyzer.analyze_multi(
                run_id=run_id,
                case_id=case_id,
                models=models,
                artifact_filter=artifact_filter,
                cancel_event=cancel_evt,
                progress_callback=_callback,
                db=get_db(),
            )
            get_db().execute(
                "UPDATE analysis_runs SET status='complete' WHERE id=?", (run_id,)
            )
            get_db().commit()
            _push_run_event(run_id, "complete", {"run_id": run_id, "case_id": case_id})
        except Exception as exc:
            try:
                get_db().execute(
                    "UPDATE analysis_runs SET status='error' WHERE id=?", (run_id,)
                )
                get_db().commit()
            except Exception:
                pass
            _push_run_event(run_id, "error", {"message": str(exc)})
        finally:
            _close_run_stream(run_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"run_id": run_id}), 202


@bp_analysis.get("/cases/<case_id>/analysis/multi")
def list_multi_runs(case_id: str):
    """List all multi-model analysis runs for a case."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    runs = db.execute(
        "SELECT id, models, status, artifact_filter, created_at FROM analysis_runs "
        "WHERE case_id=? ORDER BY created_at DESC",
        (case_id,),
    ).fetchall()

    out = []
    for r in runs:
        out.append({
            "id": r["id"],
            "models": json.loads(r["models"]),
            "status": r["status"],
            "artifact_filter": json.loads(r["artifact_filter"]) if r["artifact_filter"] else None,
            "created_at": r["created_at"],
        })
    return jsonify(out)


@bp_analysis.get("/cases/<case_id>/analysis/multi/<run_id>")
def get_multi_run_results(case_id: str, run_id: str):
    """Return all results for a specific multi-model run, grouped by artifact."""
    import re as _re
    db = get_db()

    run_row = db.execute(
        "SELECT id, models, status, created_at FROM analysis_runs WHERE id=? AND case_id=?",
        (run_id, case_id),
    ).fetchone()
    if not run_row:
        return jsonify({"error": "run not found"}), 404

    rows = db.execute(
        "SELECT artifact_key, result, provider, created_at FROM analysis_results "
        "WHERE run_id=? ORDER BY artifact_key, provider",
        (run_id,),
    ).fetchall()

    # Group by artifact_key
    artifact_map: dict[str, dict] = {}
    for r in rows:
        akey = r["artifact_key"]
        if akey not in artifact_map:
            artifact_map[akey] = {"artifact_key": akey, "consensus": None, "models_breakdown": []}
        parsed = _safe_json_parse(r["result"] or "", _re)
        entry = {
            "provider": r["provider"],
            "result": r["result"],
            "result_parsed": parsed,
            "created_at": r["created_at"],
        }
        if r["provider"] == "consensus":
            artifact_map[akey]["consensus"] = entry
        else:
            artifact_map[akey]["models_breakdown"].append(entry)

    return jsonify({
        "run": {
            "id": run_row["id"],
            "models": json.loads(run_row["models"]),
            "status": run_row["status"],
            "created_at": run_row["created_at"],
        },
        "artifacts": list(artifact_map.values()),
    })


@bp_analysis.get("/cases/<case_id>/analysis/multi/<run_id>/stream")
def multi_run_stream(case_id: str, run_id: str):
    """SSE endpoint for multi-model run progress."""
    q = _get_or_create_run_queue(run_id)

    def _generate() -> Generator[str, None, None]:
        yield "event: connected\ndata: {}\n\n"
        while True:
            try:
                event = q.get(timeout=30)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if event is None:
                break
            yield event

    return Response(
        stream_with_context(_generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp_analysis.get("/cases/<case_id>/analysis/summary")
def get_analysis_summary(case_id: str):
    import re as _re
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    rows = db.execute(
        "SELECT artifact_key, result, provider, created_at "
        "FROM analysis_results WHERE case_id=? ORDER BY created_at ASC",
        (case_id,)
    ).fetchall()

    if not rows:
        return jsonify({"has_analysis": False})

    analyzed_at = rows[-1]["created_at"]
    artifacts_analyzed, risk_rank = [], 0
    crime_map, top_risk_threads = {}, []
    risk_level_summaries, data_coverage = [], []

    for r in rows:
        key = r["artifact_key"]
        parsed = _safe_json_parse(r["result"] or "", _re)
        if not parsed:
            continue
        artifacts_analyzed.append(key)

        cl = (parsed.get("confidence_level") or "").upper()
        rank = _RISK_RANK.get(cl, 0)
        if rank > risk_rank:
            risk_rank = rank

        summary_text = parsed.get("risk_level_summary", "")
        if summary_text:
            risk_level_summaries.append({"artifact": key, "summary": summary_text})

        for ci in (parsed.get("crime_indicators") or []):
            cat = (ci.get("category") or "").upper()
            if not cat:
                continue
            ci_rank = _RISK_RANK.get((ci.get("confidence") or "LOW").upper(), 0)
            existing = crime_map.get(cat)
            if not existing or ci_rank > _RISK_RANK.get((existing.get("confidence") or "LOW").upper(), 0):
                crime_map[cat] = {
                    "category": cat,
                    "confidence": ci.get("confidence", "LOW"),
                    "severity": ci.get("severity", ci.get("confidence", "LOW")),
                    "artifact": key,
                }

        for t in (parsed.get("conversation_risk_assessment") or []):
            try:
                score = float(t.get("risk_score", 0))
            except (TypeError, ValueError):
                score = 0
            top_risk_threads.append({
                "thread_id": t.get("thread_id", ""),
                "risk_score": score,
                "risk_level": (t.get("risk_level") or "").upper(),
                "artifact": key,
                "indicators": (t.get("key_indicators") or [])[:3],
            })

        cov = parsed.get("data_coverage") or {}
        if cov:
            data_coverage.append({
                "artifact": key,
                "records_analyzed": cov.get("records_analyzed", 0),
                "total_records": cov.get("total_records", 0),
                "coverage_percent": cov.get("coverage_percent", 0),
            })

    rank_to_level = {4: "CRITICAL", 3: "HIGH", 2: "MEDIUM", 1: "LOW", 0: "NONE"}
    top_risk_threads.sort(key=lambda x: x["risk_score"], reverse=True)

    return jsonify({
        "has_analysis": True,
        "analyzed_at": analyzed_at,
        "artifacts_analyzed": artifacts_analyzed,
        "overall_risk_level": rank_to_level.get(risk_rank, "NONE"),
        "crime_categories": list(crime_map.values()),
        "top_risk_threads": top_risk_threads[:5],
        "risk_level_summaries": risk_level_summaries,
        "data_coverage": data_coverage,
    })


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
