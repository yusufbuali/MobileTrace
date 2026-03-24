"""Folder auto-discovery parser for MobileTrace.

Walks a directory tree to find:
  1. Archive files (.ufdr, .tar, .zip, .xrep, .ofb) importable by existing parsers
  2. Known forensic database files (Android/iOS) for direct parsing

Used by the "Folder Scan" evidence import mode.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .base import BaseParser, ParsedCase
from .android_parser import AndroidParser, _TARGETS as _ANDROID_TARGETS
from .ios_parser import iOSParser, _TARGET_DBS as _IOS_TARGET_DBS, _SUFFIX_TARGETS as _IOS_SUFFIX_TARGETS

logger = logging.getLogger(__name__)

_ARCHIVE_EXTS = {".ufdr", ".tar", ".zip", ".xrep", ".ofb"}

_ANDROID_LABELS = {
    "sms": "SMS / MMS",
    "calllog": "Call Log",
    "contacts": "Contacts",
    "wa_msg": "WhatsApp Messages",
    "wa_ct": "WhatsApp Contacts",
    "telegram": "Telegram",
    "signal": "Signal (encrypted)",
}

_IOS_LABELS = {
    "sms": "iMessage / SMS",
    "contacts": "Address Book",
    "calls": "Call History",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
}


class FolderParser(BaseParser):
    """Scan and parse forensic databases directly from an extracted folder."""

    def can_handle(self, source_path: Path) -> bool:
        return source_path.is_dir()

    @staticmethod
    def scan_folder(folder: Path) -> dict:
        """Walk folder tree and return discovered files grouped by type.

        Returns dict with 'archives' and 'platforms' keys.
        """
        archives: list[dict] = []
        android_dbs: dict[str, dict] = {}
        ios_dbs: dict[str, dict] = {}

        # Build filename lookup for Android targets
        android_by_name: dict[str, list[tuple[str, str]]] = {}
        for key, rel_path in _ANDROID_TARGETS.items():
            fname = Path(rel_path).name
            android_by_name.setdefault(fname, []).append((key, rel_path))

        # Build filename lookup for iOS targets
        ios_by_name: dict[str, list[tuple[str, str]]] = {}
        for key, rel_path in _IOS_TARGET_DBS.items():
            fname = Path(rel_path).name
            ios_by_name.setdefault(fname, []).append((key, rel_path))

        for root, _dirs, files in os.walk(folder, followlinks=False):
            for fname in files:
                fpath = Path(root) / fname
                try:
                    fpath.resolve().relative_to(folder.resolve())
                except ValueError:
                    continue
                ext = fpath.suffix.lower()

                # ── Archive files ──
                if ext in _ARCHIVE_EXTS:
                    try:
                        size = fpath.stat().st_size
                    except OSError:
                        size = 0
                    archives.append({
                        "path": str(fpath),
                        "name": fname,
                        "size": size,
                        "format": ext.lstrip("."),
                    })
                    continue

                # ── Relative path for DB matching ──
                try:
                    rel = fpath.relative_to(folder).as_posix()
                except ValueError:
                    continue

                # ── Android databases ──
                if fname in android_by_name:
                    for key, pattern in android_by_name[fname]:
                        if key not in android_dbs and pattern in rel:
                            try:
                                size = fpath.stat().st_size
                            except OSError:
                                size = 0
                            android_dbs[key] = {
                                "key": key,
                                "label": _ANDROID_LABELS.get(key, key),
                                "path": str(fpath),
                                "size": size,
                            }

                # ── iOS databases (exact path match) ──
                if fname in ios_by_name:
                    for key, pattern in ios_by_name[fname]:
                        if key not in ios_dbs and pattern in rel:
                            try:
                                size = fpath.stat().st_size
                            except OSError:
                                size = 0
                            ios_dbs[key] = {
                                "key": key,
                                "label": _IOS_LABELS.get(key, key),
                                "path": str(fpath),
                                "size": size,
                            }

                # ── iOS suffix targets (WhatsApp / Telegram in app containers) ──
                for key, suffix in _IOS_SUFFIX_TARGETS.items():
                    if key not in ios_dbs and rel.endswith(suffix):
                        try:
                            size = fpath.stat().st_size
                        except OSError:
                            size = 0
                        ios_dbs[key] = {
                            "key": key,
                            "label": _IOS_LABELS.get(key, key),
                            "path": str(fpath),
                            "size": size,
                        }

        result: dict = {"archives": archives, "platforms": {}}
        if android_dbs:
            result["platforms"]["android"] = {"databases": list(android_dbs.values())}
        if ios_dbs:
            result["platforms"]["ios"] = {"databases": list(ios_dbs.values())}
        return result

    # ── Parse ─────────────────────────────────────────────────────────────────

    def parse(self, source_path: Path, dest_dir: Path, platform: str = "", **kwargs) -> ParsedCase:
        """Parse databases found in directory for the given platform."""
        if platform == "ios":
            return self._parse_ios(source_path, **kwargs)
        return self._parse_android(source_path, **kwargs)

    def _find_android_dbs(self, folder: Path) -> dict[str, Path]:
        db_paths: dict[str, Path] = {}
        for key, rel_path in _ANDROID_TARGETS.items():
            fname = Path(rel_path).name
            for f in folder.rglob(fname):
                try:
                    f.resolve().relative_to(folder.resolve())
                    rel = f.relative_to(folder).as_posix()
                except ValueError:
                    continue
                if rel_path in rel:
                    db_paths[key] = f
                    break
        return db_paths

    def _find_ios_dbs(self, folder: Path) -> dict[str, Path]:
        db_paths: dict[str, Path] = {}
        for key, rel_path in _IOS_TARGET_DBS.items():
            fname = Path(rel_path).name
            for f in folder.rglob(fname):
                try:
                    f.resolve().relative_to(folder.resolve())
                    rel = f.relative_to(folder).as_posix()
                except ValueError:
                    continue
                if rel_path in rel:
                    db_paths[key] = f
                    break
        # Suffix targets (WhatsApp, Telegram in UUID app containers)
        for key, suffix in _IOS_SUFFIX_TARGETS.items():
            if key not in db_paths:
                suffix_fname = Path(suffix).name
                for f in folder.rglob(suffix_fname):
                    try:
                        f.resolve().relative_to(folder.resolve())
                        rel = f.relative_to(folder).as_posix()
                    except ValueError:
                        continue
                    if rel.endswith(suffix):
                        db_paths[key] = f
                        break
        return db_paths

    def _parse_android(self, folder: Path, signal_key: str = "", **kwargs) -> ParsedCase:
        db_paths = self._find_android_dbs(folder)
        ap = AndroidParser()
        result = ParsedCase(format="folder_android")
        warnings: list[str] = []
        result.device_info = {"platform": "android"}
        tz = ap._read_timezone(db_paths.get("settings"))
        if tz:
            result.device_info["timezone"] = tz
        result.contacts = ap._read_contacts(db_paths.get("contacts"), warnings)
        result.contacts += ap._read_wa_contacts(db_paths.get("wa_ct"), warnings)
        result.messages = ap._read_sms(db_paths.get("sms"), warnings)
        result.messages += ap._read_whatsapp(db_paths.get("wa_msg"), warnings)
        result.messages += ap._read_telegram(db_paths.get("telegram"), warnings)
        result.messages += ap._read_signal(db_paths.get("signal"), warnings, signal_key=signal_key)
        result.call_logs = ap._read_calls(db_paths.get("calllog"), warnings)
        result.warnings = warnings
        result.raw_db_paths = list(db_paths.values())
        return result

    def _parse_ios(self, folder: Path, **kwargs) -> ParsedCase:
        db_paths = self._find_ios_dbs(folder)
        ip = iOSParser()
        result = ParsedCase(format="folder_ios")
        warnings: list[str] = []
        result.device_info = ip._read_device_info(db_paths)
        result.contacts = ip._read_contacts(db_paths.get("contacts"), warnings)
        result.messages = ip._read_sms(db_paths.get("sms"), warnings)
        result.messages += ip._read_whatsapp(db_paths.get("whatsapp"), warnings)
        result.messages += ip._read_telegram_ios(db_paths.get("telegram"), warnings)
        result.call_logs = ip._read_calls(db_paths.get("calls"), warnings)
        result.warnings = warnings
        result.raw_db_paths = list(db_paths.values())
        return result
