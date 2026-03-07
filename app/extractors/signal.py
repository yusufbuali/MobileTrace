"""Signal extractor — reads signal.db (Android) or signal.sqlite (iOS)."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Signal SMS type values (same as Android SMS type field)
_TYPE_INCOMING = 1
_TYPE_OUTGOING = 2


def _epoch_ms(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.utcfromtimestamp(ms / 1000).isoformat()
    except Exception:
        return str(ms)


def extract_signal(db_path: Path) -> list[dict[str, Any]]:
    """Return normalized messages from signal.db / signal.sqlite."""
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT address, body, date, type, thread_id FROM sms"
        ).fetchall()
        for r in rows:
            direction = "outgoing" if r["type"] == _TYPE_OUTGOING else "incoming"
            addr = r["address"] or ""
            msgs.append({
                "platform": "signal",
                "direction": direction,
                "sender": "device" if direction == "outgoing" else addr,
                "recipient": addr if direction == "outgoing" else "device",
                "body": r["body"] or "",
                "timestamp": _epoch_ms(r["date"]),
                "thread_id": str(r["thread_id"] or ""),
                "raw_json": {},
            })
        conn.close()
    except Exception as exc:
        logger.warning("Signal extract failed: %s", exc)
    return msgs
