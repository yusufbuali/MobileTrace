"""Analysis routes — trigger LLM analysis + SSE progress stream + results retrieval."""
from __future__ import annotations

import json
import queue
import threading
from typing import Generator

from flask import Blueprint, Response, current_app, jsonify, stream_with_context

from app.analyzer import MobileAnalyzer
from app.database import get_db

bp_analysis = Blueprint("analysis", __name__, url_prefix="/api")

# In-memory queues for SSE: case_id → queue of SSE event strings
_progress_queues: dict[str, "queue.Queue[str | None]"] = {}
_queues_lock = threading.Lock()


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
    """Start background LLM analysis for all artifacts in a case."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    config = current_app.config["MT_CONFIG"]

    def _run():
        analyzer = MobileAnalyzer(config)

        def _callback(artifact_key: str, result: dict) -> None:
            _push_event(case_id, "artifact_done", {
                "artifact_key": artifact_key,
                "provider": result.get("provider", ""),
                "error": result.get("error"),
            })

        try:
            analyzer.analyze_case(case_id, get_db(), callback=_callback)
            _push_event(case_id, "complete", {"case_id": case_id})
        except Exception as exc:
            _push_event(case_id, "error", {"message": str(exc)})
        finally:
            _close_stream(case_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"case_id": case_id, "status": "started"}), 202


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
    db = get_db()
    rows = db.execute(
        "SELECT artifact_key, result, provider, created_at FROM analysis_results "
        "WHERE case_id=? ORDER BY created_at ASC",
        (case_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])
