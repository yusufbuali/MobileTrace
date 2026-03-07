"""WhatsApp message extractor — Android msgstore.db and iOS ChatStorage.sqlite."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _epoch_ms(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return str(ms)


def extract_whatsapp(db_path: Path, platform: str = "android") -> list[dict[str, Any]]:
    """Return normalized messages list from a WhatsApp DB."""
    if platform == "android":
        return _extract_android(db_path)
    return _extract_ios(db_path)


def _extract_android(db_path: Path) -> list[dict[str, Any]]:
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT key_remote_jid, key_from_me, data, timestamp FROM messages"
        ).fetchall()
        for r in rows:
            jid = r["key_remote_jid"] or ""
            from_me = bool(r["key_from_me"])
            msgs.append({
                "platform": "whatsapp",
                "direction": "outgoing" if from_me else "incoming",
                "sender": "device" if from_me else jid.split("@")[0],
                "recipient": jid.split("@")[0] if from_me else "device",
                "body": r["data"] or "",
                "timestamp": _epoch_ms(r["timestamp"]),
                "thread_id": jid,
                "raw_json": {},
            })
        conn.close()
    except Exception as exc:
        logger.warning("WhatsApp Android extract failed: %s", exc)
    return msgs


def _extract_ios(db_path: Path) -> list[dict[str, Any]]:
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ZFROMJID, ZTOJID, ZTEXT, ZMESSAGEDATE, ZISFROMME FROM ZWAMESSAGE"
        ).fetchall()
        for r in rows:
            from_me = bool(r["ZISFROMME"])
            msgs.append({
                "platform": "whatsapp",
                "direction": "outgoing" if from_me else "incoming",
                "sender": "device" if from_me else (r["ZFROMJID"] or "").split("@")[0],
                "recipient": (r["ZTOJID"] or "").split("@")[0] if from_me else "device",
                "body": r["ZTEXT"] or "",
                "timestamp": _epoch_ms(int(r["ZMESSAGEDATE"] * 1000) if r["ZMESSAGEDATE"] else None),
                "thread_id": r["ZFROMJID"] or r["ZTOJID"] or "",
                "raw_json": {},
            })
        conn.close()
    except Exception as exc:
        logger.warning("WhatsApp iOS extract failed: %s", exc)
    return msgs
