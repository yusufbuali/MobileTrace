"""Call log extractor.

Android: contacts2.db (com.android.providers.contacts)
  Table: calls — number, duration (s), date (Unix ms), type (1=in,2=out,3=missed,4=vm)

iOS: call_history.db (Library/CallHistoryDB)
  Table: ZCALLRECORD — Core Data schema
  ZDATE: Apple Core Data epoch (seconds since 2001-01-01).
  ZORIGINATED: 1 = device placed the call (outgoing); 0 = incoming.
  ZANSWERED:   1 = call was answered; 0 = missed/rejected.
  ZCALLTYPE:   1=phone, 8=FaceTime video, 16=FaceTime audio.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_APPLE_EPOCH_OFFSET = 978307200  # seconds

_ANDROID_CALL_TYPE = {1: "incoming", 2: "outgoing", 3: "missed", 4: "voicemail"}
_IOS_CALL_TYPE = {1: "phone", 8: "facetime_video", 16: "facetime_audio"}


def _unix_ms(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return str(ms)


def _apple_epoch(ts: int | float | None) -> str:
    if not ts:
        return ""
    try:
        if ts > 1e10:
            ts = ts / 1e9
        return datetime.fromtimestamp(ts + _APPLE_EPOCH_OFFSET, tz=timezone.utc).isoformat()
    except Exception:
        return str(ts)


def extract_call_logs(db_path: Path, platform: str = "android") -> list[dict[str, Any]]:
    """Return normalized call log entries."""
    if platform == "ios":
        return _extract_ios(db_path)
    return _extract_android(db_path)


def _extract_android(db_path: Path) -> list[dict[str, Any]]:
    calls = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT number, duration, date, type FROM calls ORDER BY date ASC"
        ).fetchall()
        for r in rows:
            calls.append({
                "platform": "phone",
                "number": r["number"] or "",
                "direction": _ANDROID_CALL_TYPE.get(r["type"], "unknown"),
                "duration_s": r["duration"] or 0,
                "timestamp": _unix_ms(r["date"]),
            })
        conn.close()
    except Exception as exc:
        logger.warning("Android call log extract failed: %s", exc)
    return calls


def _extract_ios(db_path: Path) -> list[dict[str, Any]]:
    """iOS call_history.db — ZCALLRECORD (Core Data)."""
    calls = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ZADDRESS, ZDURATION, ZDATE, ZORIGINATED, ZANSWERED, ZCALLTYPE "
            "FROM ZCALLRECORD ORDER BY ZDATE ASC"
        ).fetchall()
        for r in rows:
            originated = bool(r["ZORIGINATED"])
            answered = bool(r["ZANSWERED"])
            if originated:
                direction = "outgoing"
            elif answered:
                direction = "incoming"
            else:
                direction = "missed"
            call_type = _IOS_CALL_TYPE.get(r["ZCALLTYPE"], "phone")
            calls.append({
                "platform": call_type,
                "number": r["ZADDRESS"] or "",
                "direction": direction,
                "duration_s": int(r["ZDURATION"] or 0),
                "timestamp": _apple_epoch(r["ZDATE"]),
            })
        conn.close()
    except Exception as exc:
        logger.warning("iOS call log extract failed: %s", exc)
    return calls
