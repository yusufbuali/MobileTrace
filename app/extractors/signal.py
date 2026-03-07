"""Signal extractor.

Android: signal.db (org.thoughtcrime.securesms/databases)
  Older builds: table 'sms' — address, date_sent (Unix ms), body, type
  Newer builds (v5.0+): table 'message' — to_recipient_id, date_sent, body, type
  type field: 1 = INBOX (incoming), 2 = SENT (outgoing), others = system/failed.
  NOTE: signal.db is SQLCipher-encrypted on-device. Forensic tools (Cellebrite,
  XRY) decrypt and write a plaintext copy; this extractor reads that plaintext copy.

iOS: signal.sqlite (Library/Application Support/Signal)
  Also SQLCipher-encrypted on-device; forensic tools export decrypted copy.
  Uses grdb schema — no standardised query; skipped here (data comes via UFDR XML).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Signal sms.type base values
_TYPE_INCOMING = 1
_TYPE_OUTGOING = 2


def _unix_ms(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return str(ms)


def extract_signal(db_path: Path, platform: str = "android") -> list[dict[str, Any]]:
    """Return normalized messages from Signal DB (must be decrypted by forensic tool)."""
    if platform == "ios":
        logger.warning(
            "iOS Signal uses grdb SQLCipher; extraction depends on forensic tool export. "
            "No raw-DB extractor available — use UFDR/XRY XML output instead."
        )
        return []
    return _extract_android(db_path)


def _extract_android(db_path: Path) -> list[dict[str, Any]]:
    """Try 'sms' table (older Signal); fall back to 'message' table (Signal v5+)."""
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Older Signal: sms table with date_sent column (confirmed by AIFT leapp_integration.py)
        try:
            rows = conn.execute(
                "SELECT address, date_sent AS date, body, type FROM sms ORDER BY date_sent ASC"
            ).fetchall()
            msgs = _rows_to_msgs(rows, addr_col="address")
        except sqlite3.OperationalError:
            # Newer Signal (v5+): message table
            try:
                rows = conn.execute(
                    "SELECT to_recipient_id AS address, date_sent AS date, body, type "
                    "FROM message ORDER BY date_sent ASC"
                ).fetchall()
                msgs = _rows_to_msgs(rows, addr_col="address")
            except sqlite3.OperationalError as exc2:
                logger.warning("Signal DB: neither sms nor message table found: %s", exc2)
        conn.close()
    except Exception as exc:
        logger.warning("Signal extract failed: %s", exc)
    return msgs


def _rows_to_msgs(rows, addr_col: str) -> list[dict[str, Any]]:
    msgs = []
    for r in rows:
        # type & 0x1f gives base type: 1=inbox, 2=sent
        raw_type = r["type"] or 0
        base_type = raw_type & 0x1f if raw_type > 3 else raw_type
        direction = "outgoing" if base_type == _TYPE_OUTGOING else "incoming"
        addr = r[addr_col] or ""
        msgs.append({
            "platform": "signal",
            "direction": direction,
            "sender": "device" if direction == "outgoing" else addr,
            "recipient": addr if direction == "outgoing" else "device",
            "body": r["body"] or "",
            "timestamp": _unix_ms(r["date"]),
            "thread_id": "",
            "raw_json": {},
        })
    return msgs
