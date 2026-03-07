"""Telegram extractor.

Android: cache4.db (org.telegram.messenger/files)
  Table messages: mid, uid, date (Unix seconds), message, out (1=sent, 0=received)
  Table users:    uid, first_name, last_name, username
  NOTE: Modern Telegram (v4+, 2018+) encrypts cache4.db with a device-specific key.
  This extractor works when: (a) the forensic tool has decrypted the DB, or
  (b) the device is rooted and the key was extracted. Encrypted DBs cause
  sqlite3.DatabaseError ('file is not a database') which is caught and logged.

iOS: TGDatabase / TGMessage (Telegram-iOS/Telegram X)
  Table TGMessage: mid, cid (chat id), date (Unix seconds), message, outgoing
  Also encrypted on modern builds; same caveats as Android.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _epoch_s(ts: int | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return str(ts)


def extract_telegram(db_path: Path, platform: str = "android") -> list[dict[str, Any]]:
    """Return normalized messages from Telegram DB (requires decrypted copy)."""
    if platform == "ios":
        return _extract_ios(db_path)
    return _extract_android(db_path)


def _extract_android(db_path: Path) -> list[dict[str, Any]]:
    """Android cache4.db — messages + users tables."""
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except sqlite3.DatabaseError as exc:
        logger.warning(
            "Telegram cache4.db could not be opened (%s). "
            "This usually means the DB is SQLCipher-encrypted. "
            "Re-extract using a tool that decrypts Telegram (e.g. Cellebrite PA).", exc
        )
        return []

    try:
        # Build uid → display name from users table
        user_map: dict[int, str] = {}
        try:
            for row in conn.execute(
                "SELECT uid, first_name, last_name, username FROM users"
            ).fetchall():
                parts = [row["first_name"] or "", row["last_name"] or ""]
                name = " ".join(p for p in parts if p).strip() or row["username"] or str(row["uid"])
                user_map[row["uid"]] = name
        except sqlite3.OperationalError:
            pass  # users table absent in some versions

        # Fetch messages — try with dialogs join first, fall back to messages only
        try:
            rows = conn.execute(
                "SELECT messages.mid, messages.uid, messages.date, "
                "messages.message, messages.out AS direction, "
                "dialogs.did AS dialog_id "
                "FROM messages LEFT JOIN dialogs ON messages.uid = dialogs.did "
                "ORDER BY messages.date ASC"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT mid, uid, date, message, out AS direction, uid AS dialog_id "
                "FROM messages ORDER BY date ASC"
            ).fetchall()

        for r in rows:
            from_me = bool(r["direction"])
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
    except sqlite3.DatabaseError as exc:
        logger.warning("Telegram Android DB encrypted or corrupt: %s", exc)
    finally:
        conn.close()
    return msgs


def _extract_ios(db_path: Path) -> list[dict[str, Any]]:
    """iOS Telegram — TGMessage table."""
    msgs = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT mid, cid, date, message, outgoing FROM TGMessage ORDER BY date ASC"
        ).fetchall()
        for r in rows:
            from_me = bool(r["outgoing"])
            msgs.append({
                "platform": "telegram",
                "direction": "outgoing" if from_me else "incoming",
                "sender": "device" if from_me else "",
                "recipient": "" if not from_me else "device",
                "body": r["message"] or "",
                "timestamp": _epoch_s(r["date"]),
                "thread_id": str(r["cid"] or ""),
                "raw_json": {},
            })
        conn.close()
    except sqlite3.DatabaseError as exc:
        logger.warning(
            "iOS Telegram DB could not be read (%s). "
            "Likely SQLCipher-encrypted — use forensic tool XML export instead.", exc
        )
    return msgs
