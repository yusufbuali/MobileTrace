"""Chat route — per-case forensics chatbot with FTS5 context retrieval."""
from __future__ import annotations

import json

from flask import Blueprint, current_app, jsonify, request

from app.ai_providers import create_provider
from app.database import get_db
from app.retriever import fts_retrieve

bp_chat = Blueprint("chat", __name__, url_prefix="/api")

_CHAT_SYSTEM_PROMPT = (
    "You are a digital forensics AI assistant helping an investigator analyse a mobile device case. "
    "Base every statement exclusively on the evidence provided. Never fabricate or assume. "
    "Always include exact timestamp, sender/recipient, and quote message body directly. "
    "Distinguish 'The data shows...' (observed) from 'This pattern may suggest...' (inferred). "
    "When asked about criminal activity, reference crime categories (DRUG_TRAFFICKING, CSAM_GROOMING, "
    "TERRORISM, HUMAN_TRAFFICKING, MONEY_LAUNDERING, FRAUD, CYBER_CRIME, ORGANIZED_CRIME, WEAPONS, "
    "DOMESTIC_VIOLENCE, STALKING, SEXUAL_OFFENSE) only when evidence supports it. "
    "If the context does not contain relevant evidence, say so clearly."
)

_HISTORY_LIMIT = 10  # recent turns to include in prompt


def _format_context(rows: list[dict]) -> str:
    if not rows:
        return "No matching evidence found in the database."
    lines = ["## Relevant Evidence\n"]
    for r in rows:
        if r.get("source") == "message":
            lines.append(
                f"[{r.get('timestamp', '')}] {r.get('platform', 'msg')} | "
                f"{r.get('direction', '')} | {r.get('sender', '')} → {r.get('recipient', '')} | "
                f"{r.get('body', '')}"
            )
        elif r.get("source") == "contact":
            lines.append(
                f"[contact] {r.get('name', '')} | {r.get('phone', '')} | {r.get('email', '')}"
            )
    return "\n".join(lines)


def _format_history(rows) -> str:
    if not rows:
        return ""
    lines = ["## Conversation History\n"]
    for r in rows:
        role = "Investigator" if r["role"] == "user" else "Assistant"
        lines.append(f"{role}: {r['content']}")
    return "\n".join(lines)


@bp_chat.post("/cases/<case_id>/chat")
def chat(case_id: str):
    """Accept a question, retrieve FTS5 context, call LLM, return response."""
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
        return jsonify({"error": "case not found"}), 404

    body = request.get_json() or {}
    query = body.get("message", "").strip()
    if not query:
        return jsonify({"error": "message required"}), 400

    # Retrieve relevant evidence
    context_rows = fts_retrieve(case_id, query, db)
    context_text = _format_context(context_rows)

    # Fetch recent conversation history
    history_rows = db.execute(
        "SELECT role, content FROM chat_history WHERE case_id=? ORDER BY id DESC LIMIT ?",
        (case_id, _HISTORY_LIMIT),
    ).fetchall()
    history_text = _format_history(list(reversed(history_rows)))

    # Build user prompt
    user_prompt = "\n\n".join(filter(None, [history_text, context_text, f"## Question\n\n{query}"]))

    # Call LLM
    config = current_app.config["MT_CONFIG"]
    provider = create_provider(config)
    response_text = provider.analyze(
        system_prompt=_CHAT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=4096,
    )

    # Persist both turns
    context_ids = [r["id"] for r in context_rows if "id" in r]
    db.execute(
        "INSERT INTO chat_history (case_id, role, content, context_ids) VALUES (?,?,?,?)",
        (case_id, "user", query, "[]"),
    )
    db.execute(
        "INSERT INTO chat_history (case_id, role, content, context_ids) VALUES (?,?,?,?)",
        (case_id, "assistant", response_text, json.dumps(context_ids)),
    )
    db.commit()

    citations = [
        {
            "platform": r.get("platform", ""),
            "thread_id": r.get("thread_id") or r.get("sender") or "",
            "timestamp": r.get("timestamp", ""),
            "direction": r.get("direction", ""),
            "body": (r.get("body") or r.get("text") or "")[:200],
            "source": r.get("source", "message"),
        }
        for r in context_rows
        if r.get("source") == "message"
    ]

    return jsonify({
        "response": response_text,
        "context_count": len(context_rows),
        "citations": citations,
    })


@bp_chat.get("/cases/<case_id>/chat/history")
def get_history(case_id: str):
    """Return full chat history for a case."""
    db = get_db()
    rows = db.execute(
        "SELECT id, role, content, context_ids, created_at FROM chat_history "
        "WHERE case_id=? ORDER BY id ASC",
        (case_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])
