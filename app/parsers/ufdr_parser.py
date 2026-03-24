"""UFDR (Cellebrite) parser for MobileTrace.

Delegates to AIFT's mobile_ingest module (mounted at /aift_mobile).
Falls back to standalone ZIP+XML parsing if AIFT module unavailable.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .base import BaseParser, ParsedCase

logger = logging.getLogger(__name__)

# Platform detection tokens
_IOS_TOKENS = frozenset({"ios", "iphone os", "ipados", "iphone", "ipad", "apple"})
_ANDROID_TOKENS = frozenset({"android", "one ui", "miui", "emui", "coloros", "oxygenos"})


class UfdrParser(BaseParser):

    def can_handle(self, source_path: Path) -> bool:
        return source_path.suffix.lower() == ".ufdr"

    def parse(self, source_path: Path, dest_dir: Path, **kwargs) -> ParsedCase:
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            return self._parse_via_aift(source_path, dest_dir)
        except ImportError:
            logger.warning("AIFT mobile_ingest not available — using standalone UFDR parser")
            return self._parse_standalone(source_path, dest_dir)

    def _parse_via_aift(self, source_path: Path, dest_dir: Path) -> ParsedCase:
        """Delegate to AIFT's battle-tested _extract_ufdr, then augment with manual metadata."""
        import mobile_ingest as mi  # mounted at /aift_mobile
        result = mi.extract_evidence(source_path, dest_dir)
        
        device_info = result.device_info or {}
        # Side-scan for timezone if missing from AIFT result
        if "timezone" not in device_info:
            manual_meta = self._extract_metadata(source_path)
            if "timezone" in manual_meta:
                device_info["timezone"] = manual_meta["timezone"]

        return ParsedCase(
            format="ufdr",
            device_info=device_info,
            raw_db_paths=list(result.extraction_path.rglob("*.db")) if result.extraction_path else [],
            warnings=[result.error] if result.error else [],
        )

    def _parse_standalone(self, source_path: Path, dest_dir: Path) -> ParsedCase:
        """Minimal standalone UFDR parser — reads metadata XML only."""
        device_info = self._extract_metadata(source_path)
        db_paths: list[Path] = []
        _EXTRACT_EXT = {".db", ".sqlite", ".plist", ".xml"}
        try:
            with zipfile.ZipFile(source_path, "r") as zf:
                for name in zf.namelist():
                    if Path(name).suffix.lower() in _EXTRACT_EXT:
                        target = dest_dir / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(name))
                        if Path(name).suffix.lower() in {".db", ".sqlite"}:
                            db_paths.append(target)
        except Exception as exc:
            return ParsedCase(format="ufdr", device_info=device_info,
                              warnings=[f"Extraction failed: {exc}"])
        return ParsedCase(format="ufdr", device_info=device_info, raw_db_paths=db_paths)

    def _extract_metadata(self, source_path: Path) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "model": "Unknown", "imei": "Unknown",
            "os_version": "Unknown", "platform": "unknown",
        }
        try:
            with zipfile.ZipFile(source_path) as zf:
                names = set(zf.namelist())
                if "Metadata.xml" in names:
                    root = ET.fromstring(zf.read("Metadata.xml"))
                    proj = root.find(".//project") or root
                    meta["model"] = (proj.findtext("model") or "Unknown").strip()
                    meta["imei"] = (proj.findtext("imei") or "Unknown").strip()
                    meta["os_version"] = (proj.findtext("platform") or "Unknown").strip()
                    # Cellebrite timezone — try common field names
                    tz = (
                        proj.findtext("timezone")
                        or proj.findtext("timeZone")
                        or proj.findtext("deviceTimeZone")
                        or proj.findtext("TimeZone")
                        or proj.findtext("tzoffset")
                        or proj.findtext("utcOffset")
                    )
                    if tz and tz.strip():
                        meta["timezone"] = tz.strip()
                elif "ufed_report.xml" in names:
                    root = ET.fromstring(zf.read("ufed_report.xml"))
                    gi = root.find(".//GeneralInfo")
                    if gi is not None:
                        meta["model"] = (gi.findtext("DeviceModel") or "Unknown").strip()
                        meta["imei"] = (gi.findtext("IMEI") or "Unknown").strip()
                        meta["os_version"] = (gi.findtext("OS") or "Unknown").strip()
                        tz = (
                            gi.findtext("TimeZone")
                            or gi.findtext("DeviceTimeZone")
                            or gi.findtext("UtcOffset")
                        )
                        if tz and tz.strip():
                            meta["timezone"] = tz.strip()
                os_l = meta["os_version"].lower()
                if any(t in os_l for t in _ANDROID_TOKENS):
                    meta["platform"] = "android"
                elif any(t in os_l for t in _IOS_TOKENS):
                    meta["platform"] = "ios"
        except Exception as exc:
            logger.warning("UFDR metadata extraction failed: %s", exc)
        return meta
