"""Base types for MobileTrace parsers."""
from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedCase:
    """Normalized output from any mobile forensic format."""
    format: str                          # ufdr | xry | oxygen | adb | itunes | graykey
    device_info: dict[str, Any] = field(default_factory=dict)
    contacts: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    call_logs: list[dict[str, Any]] = field(default_factory=list)
    media_files: list[dict[str, Any]] = field(default_factory=list)
    # Each dict: { message_id: int|None, filename: str, mime_type: str,
    #              size_bytes: int, tmp_path: str }
    raw_db_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BaseParser(ABC):
    """Abstract base for all format parsers."""

    @abstractmethod
    def can_handle(self, source_path: Path) -> bool:
        """Return True if this parser handles the given file/dir."""

    @abstractmethod
    def parse(self, source_path: Path, dest_dir: Path) -> ParsedCase:
        """Parse source_path into a ParsedCase. dest_dir is for extracted files."""

    @staticmethod
    def _norm_message(
        platform: str,
        body: str,
        sender: str = "",
        recipient: str = "",
        direction: str = "unknown",
        timestamp: str = "",
        thread_id: str = "",
        raw: dict | None = None,
    ) -> dict[str, Any]:
        return {
            "platform": platform,
            "direction": direction,
            "sender": sender or "",
            "recipient": recipient or "",
            "body": body or "",
            "timestamp": timestamp or "",
            "thread_id": thread_id or "",
            "raw_json": raw or {},
        }

    @staticmethod
    def _norm_contact(
        name: str = "",
        phone: str = "",
        email: str = "",
        source_app: str = "device_contacts",
        raw: dict | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        return {
            "name": name or "",
            "phone": phone or "",
            "email": email or "",
            "source_app": source_app,
            "raw_json": raw or {},
            "source": source,   # None = normal, 'recovered' = reconstructed
        }

    @staticmethod
    def _norm_phone(phone: str | None) -> str:
        """Normalize a phone number to a stable dedup key (digits + leading +)."""
        if not phone:
            return ""
        phone = str(phone).strip()
        # Keep leading + for international numbers
        prefix = "+" if phone.startswith("+") else ""
        digits = "".join(c for c in phone if c.isdigit())
        return prefix + digits

    def _open_db(self, path) -> sqlite3.Connection | None:
        """Open a SQLite DB with Row factory; return None on failure or missing path."""
        p = Path(path) if path else None
        if not p or not p.exists():
            return None
        try:
            conn = sqlite3.connect(str(p))
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as exc:
            logger.warning("Cannot open %s: %s", path, exc)
            return None

    def _recover_from_wa_sms(
        self,
        wa_db_path,
        parsed_messages: list,
        warnings: list,
        source_label: str,
    ) -> dict[str, dict]:
        """Return {key: contact_dict} recovered from WhatsApp + SMS metadata."""
        recovered: dict[str, dict] = {}

        def _add(name: str, phone: str, source_app: str) -> None:
            norm = self._norm_phone(phone)
            key = norm or name
            if key and key not in recovered:
                recovered[key] = self._norm_contact(
                    name=name, phone=norm, email="",
                    source_app=source_app, source="recovered",
                )

        conn = self._open_db(wa_db_path)
        if conn:
            try:
                for row in conn.execute(
                    "SELECT display_name, number FROM wa_contacts"
                    " WHERE display_name IS NOT NULL AND display_name != ''"
                ).fetchall():
                    _add(row["display_name"], row["number"] or "", "whatsapp_contacts")
            except Exception as e:
                warnings.append(f"Contact recovery (WhatsApp {source_label}): {e}")
            finally:
                conn.close()

        for msg in parsed_messages:
            if msg.get("platform") != "sms":
                continue
            raw = msg.get("raw_json") or {}
            name = raw.get("contact_name") or ""
            phone = raw.get("address") or msg.get("sender") or ""
            if name and phone:
                _add(name, phone, "sms_metadata")

        return recovered

    @staticmethod
    def _norm_call(
        number: str,
        direction: str = "unknown",
        duration_s: int = 0,
        timestamp: str = "",
        platform: str = "phone",
    ) -> dict[str, Any]:
        return {
            "number": number or "",
            "direction": direction,
            "duration_s": duration_s,
            "timestamp": timestamp or "",
            "platform": platform,
        }
