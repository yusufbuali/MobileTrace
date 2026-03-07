"""Base types for MobileTrace parsers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParsedCase:
    """Normalized output from any mobile forensic format."""
    format: str                          # ufdr | xry | oxygen | adb | itunes | graykey
    device_info: dict[str, Any] = field(default_factory=dict)
    contacts: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    call_logs: list[dict[str, Any]] = field(default_factory=list)
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
    ) -> dict[str, Any]:
        return {
            "name": name or "",
            "phone": phone or "",
            "email": email or "",
            "source_app": source_app,
            "raw_json": raw or {},
        }

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
