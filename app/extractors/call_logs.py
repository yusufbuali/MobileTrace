"""Call log extractor — reads contacts2.db (Android) or call_history.db (iOS)."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Android call type values
_CALL_TYPE = {1: "incoming", 2: "outgoing", 3: "missed", 4: "voicemail"}


def _epoch_ms(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.utcfromtimestamp(ms / 1000).isoformat()
    except Exception:
        return str(ms)


def extract_call_logs(db_path: Path) -> list[dict[str, Any]]:
    """Return normalized call log entries from contacts2.db or call_history.db."""
    calls = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT number, duration, date, type FROM calls"
        ).fetchall()
        for r in rows:
            calls.append({
                "platform": "phone",
                "number": r["number"] or "",
                "direction": _CALL_TYPE.get(r["type"], "unknown"),
                "duration_s": r["duration"] or 0,
                "timestamp": _epoch_ms(r["date"]),
            })
        conn.close()
    except Exception as exc:
        logger.warning("Call log extract failed: %s", exc)
    return calls
