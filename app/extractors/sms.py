"""SMS/MMS extractor.

Android: mmssms.db (com.android.providers.telephony)
  Table: sms — address, body, date (Unix ms), type (1=inbox, 2=sent)

iOS: sms.db (HomeDomain/Library/SMS)
  Table: message JOIN handle — handle.id = phone number
  date field: Apple Core Data epoch (seconds since 2001-01-01).
  iOS 11+: nanoseconds — detect by value > 1e10 and divide by 1e9.
  Direction: is_from_me = 1 → outgoing.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Seconds between Unix epoch (1970-01-01) and Apple Core Data epoch (2001-01-01)
_APPLE_EPOCH_OFFSET = 978307200

_TYPE_INCOMING = 1
_TYPE_OUTGOING = 2


def _unix_ms(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return str(ms)


def _apple_epoch(ts: int | float | None) -> str:
    """Convert Apple Core Data epoch (s or ns) to ISO string."""
    if not ts:
        return ""
    try:
        if ts > 1e10:          # nanoseconds (iOS 11+)
            ts = ts / 1e9
        return datetime.fromtimestamp(ts + _APPLE_EPOCH_OFFSET, tz=timezone.utc).isoformat()
    except Exception:
        return str(ts)


def extract_sms(db_path: Path, platform: str = "android") -> list[dict[str, Any]]:
    """Return normalized SMS messages from mmssms.db (Android) or sms.db (iOS)."""
    if platform == "ios":
        return _extract_ios(db_path)
    return _extract_android(db_path)


def _extract_android(db_path: Path) -> list[dict[str, Any]]:
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT address, body, date, type FROM sms ORDER BY date ASC"
        ).fetchall()
        for r in rows:
            direction = "outgoing" if r["type"] == _TYPE_OUTGOING else "incoming"
            addr = r["address"] or ""
            msgs.append({
                "platform": "sms",
                "direction": direction,
                "sender": "device" if direction == "outgoing" else addr,
                "recipient": addr if direction == "outgoing" else "device",
                "body": r["body"] or "",
                "timestamp": _unix_ms(r["date"]),
                "thread_id": "",
                "raw_json": {},
            })
        conn.close()
    except Exception as exc:
        logger.warning("Android SMS extract failed: %s", exc)
    return msgs


def _extract_ios(db_path: Path) -> list[dict[str, Any]]:
    """iOS sms.db — message table joined with handle for phone numbers."""
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT h.id AS address, m.text AS body,
                   m.date AS ts, m.is_from_me
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            ORDER BY m.date ASC
        """).fetchall()
        for r in rows:
            direction = "outgoing" if r["is_from_me"] else "incoming"
            addr = r["address"] or ""
            msgs.append({
                "platform": "sms",
                "direction": direction,
                "sender": "device" if direction == "outgoing" else addr,
                "recipient": addr if direction == "outgoing" else "device",
                "body": r["body"] or "",
                "timestamp": _apple_epoch(r["ts"]),
                "thread_id": "",
                "raw_json": {},
            })
        conn.close()
    except Exception as exc:
        logger.warning("iOS SMS extract failed: %s", exc)
    return msgs
