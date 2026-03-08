"""Oxygen Forensics Detective parser for MobileTrace.

Oxygen .ofb files are SQLite databases. This parser reads them directly.
Key tables: DeviceInfo, messages (SMS), calls, contacts, chats (IM).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import BaseParser, ParsedCase

logger = logging.getLogger(__name__)

_CALL_TYPE = {1: "incoming", 2: "outgoing", 3: "missed"}
_MSG_TYPE = {1: "incoming", 2: "outgoing"}


def _epoch_ms_to_iso(ms: int | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.utcfromtimestamp(ms / 1000).isoformat()
    except Exception:
        return str(ms)


class OxygenParser(BaseParser):

    def can_handle(self, source_path: Path) -> bool:
        if source_path.suffix.lower() != ".ofb":
            return False
        try:
            with open(source_path, "rb") as f:
                return f.read(16) == b"SQLite format 3\x00"
        except Exception:
            return False

    def parse(self, source_path: Path, dest_dir: Path, **kwargs) -> ParsedCase:
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(source_path)
            conn.row_factory = sqlite3.Row
        except Exception as exc:
            return ParsedCase(format="oxygen", warnings=[f"Cannot open OFB: {exc}"])

        warnings: list[str] = []
        result = ParsedCase(format="oxygen")
        try:
            result.device_info = self._read_device_info(conn)
            result.contacts = self._read_contacts(conn, warnings)
            result.messages = self._read_sms(conn, warnings)
            result.messages += self._read_chats(conn, warnings)
            result.call_logs = self._read_calls(conn, warnings)
            result.raw_db_paths = [source_path]
        finally:
            conn.close()
        result.warnings = warnings
        return result

    def _read_device_info(self, conn: sqlite3.Connection) -> dict[str, Any]:
        meta = {"model": "Unknown", "imei": "Unknown", "os_version": "Unknown", "platform": "unknown"}
        try:
            rows = conn.execute("SELECT field, value FROM DeviceInfo").fetchall()
            info = {r["field"]: r["value"] for r in rows}
            meta["model"] = info.get("DeviceName") or info.get("Model") or "Unknown"
            meta["imei"] = info.get("IMEI") or info.get("Imei") or "Unknown"
            meta["os_version"] = info.get("OS") or info.get("AndroidVersion") or "Unknown"
            os_l = meta["os_version"].lower()
            if "android" in os_l:
                meta["platform"] = "android"
            elif "ios" in os_l or "iphone" in os_l:
                meta["platform"] = "ios"
        except Exception as exc:
            logger.warning("Oxygen DeviceInfo read failed: %s", exc)
        return meta

    def _read_contacts(self, conn, warnings: list) -> list[dict]:
        contacts = []
        try:
            rows = conn.execute(
                "SELECT display_name, phone_number, email FROM contacts"
            ).fetchall()
            for r in rows:
                contacts.append(self._norm_contact(
                    name=r["display_name"] or "",
                    phone=r["phone_number"] or "",
                    email=r["email"] or "",
                    source_app="device_contacts",
                ))
        except Exception as exc:
            warnings.append(f"contacts read failed: {exc}")
        return contacts

    def _read_sms(self, conn, warnings: list) -> list[dict]:
        msgs = []
        try:
            rows = conn.execute(
                "SELECT address, body, date, type FROM messages"
            ).fetchall()
            for r in rows:
                direction = _MSG_TYPE.get(r["type"], "unknown")
                msgs.append(self._norm_message(
                    platform="sms",
                    body=r["body"] or "",
                    sender=r["address"] if direction == "incoming" else "device",
                    recipient=r["address"] if direction == "outgoing" else "device",
                    direction=direction,
                    timestamp=_epoch_ms_to_iso(r["date"]),
                ))
        except Exception as exc:
            warnings.append(f"SMS read failed: {exc}")
        return msgs

    def _read_chats(self, conn, warnings: list) -> list[dict]:
        """Read IM messages from Oxygen 'chats' table (WhatsApp, Telegram, etc.)."""
        msgs = []
        try:
            rows = conn.execute(
                "SELECT chat_type, sender, recipient, body, date, direction FROM chats"
            ).fetchall()
            for r in rows:
                msgs.append(self._norm_message(
                    platform=r["chat_type"] or "chat",
                    body=r["body"] or "",
                    sender=r["sender"] or "",
                    recipient=r["recipient"] or "",
                    direction=r["direction"] or "unknown",
                    timestamp=_epoch_ms_to_iso(r["date"]),
                ))
        except Exception as exc:
            logger.debug("Oxygen chats read: %s", exc)
        return msgs

    def _read_calls(self, conn, warnings: list) -> list[dict]:
        calls = []
        try:
            rows = conn.execute(
                "SELECT number, duration, date, call_type FROM calls"
            ).fetchall()
            for r in rows:
                calls.append(self._norm_call(
                    number=r["number"] or "",
                    direction=_CALL_TYPE.get(r["call_type"], "unknown"),
                    duration_s=r["duration"] or 0,
                    timestamp=_epoch_ms_to_iso(r["date"]),
                ))
        except Exception as exc:
            warnings.append(f"calls read failed: {exc}")
        return calls
