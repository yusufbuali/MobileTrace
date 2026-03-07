"""FTS5 retrieval layer for the MobileTrace chatbot.

Searches messages and contacts using SQLite FTS5 virtual tables,
scoped to a single case. Results are returned as plain dicts
ready to be injected into an LLM prompt as context.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


def fts_retrieve(
    case_id: str,
    query: str,
    db: sqlite3.Connection,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search messages and contacts via FTS5 for the given case.

    Returns a list of result dicts, each with a ``source`` field
    set to either ``"message"`` or ``"contact"``.
    """
    results: list[dict[str, Any]] = []

    if not query or not query.strip():
        return results

    # Sanitize query for FTS5 — wrap in quotes to treat as phrase, strip special chars
    safe_query = _sanitize_fts_query(query)
    if not safe_query:
        return results

    # Messages FTS5
    try:
        rows = db.execute(
            """
            SELECT m.id, m.platform, m.sender, m.recipient, m.body, m.timestamp, m.direction
            FROM messages_fts
            JOIN messages m ON messages_fts.rowid = m.id
            WHERE messages_fts MATCH ? AND m.case_id = ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, case_id, limit),
        ).fetchall()
        for r in rows:
            results.append(dict(r) | {"source": "message"})
    except Exception as exc:
        logger.warning("FTS5 messages search failed: %s", exc)

    # Contacts FTS5 (use smaller quota)
    contact_limit = max(1, limit // 4)
    try:
        rows = db.execute(
            """
            SELECT c.id, c.name, c.phone, c.email, c.source_app
            FROM contacts_fts
            JOIN contacts c ON contacts_fts.rowid = c.id
            WHERE contacts_fts MATCH ? AND c.case_id = ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, case_id, contact_limit),
        ).fetchall()
        for r in rows:
            results.append(dict(r) | {"source": "contact"})
    except Exception as exc:
        logger.warning("FTS5 contacts search failed: %s", exc)

    return results


def _sanitize_fts_query(query: str) -> str:
    """Produce a safe FTS5 query string.

    Wraps each whitespace-separated token in double quotes so that
    special FTS5 operators (AND, OR, NOT, *, NEAR) in user input are
    treated as literals.
    """
    tokens = query.strip().split()
    if not tokens:
        return ""
    # Quote each token to neutralize FTS5 operators
    quoted = " ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)
    return quoted
