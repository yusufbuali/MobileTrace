"""Telegram extractor — reads cache4.db (Android Telegram app database)."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _epoch_s(ts: int | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.utcfromtimestamp(ts).isoformat()
    except Exception:
        return str(ts)


def extract_telegram(db_path: Path) -> list[dict[str, Any]]:
    """Return normalized messages from Telegram cache4.db."""
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Build uid → name lookup from users table
        user_map: dict[int, str] = {}
        try:
            for row in conn.execute("SELECT uid, name, phone FROM users").fetchall():
                user_map[row["uid"]] = row["name"] or row["phone"] or str(row["uid"])
        except Exception:
            pass

        rows = conn.execute(
            "SELECT mid, uid, out, message, date, dialog_id FROM messages"
        ).fetchall()
        for r in rows:
            from_me = bool(r["out"])
            uid = r["uid"] or 0
            peer_name = user_map.get(uid, str(uid))
            msgs.append({
                "platform": "telegram",
                "direction": "outgoing" if from_me else "incoming",
                "sender": "device" if from_me else peer_name,
                "recipient": peer_name if from_me else "device",
                "body": r["message"] or "",
                "timestamp": _epoch_s(r["date"]),
                "thread_id": str(r["dialog_id"] or ""),
                "raw_json": {},
            })
        conn.close()
    except Exception as exc:
        logger.warning("Telegram extract failed: %s", exc)
    return msgs
