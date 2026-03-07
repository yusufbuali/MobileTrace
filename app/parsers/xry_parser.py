"""XRY (MSAB) parser for MobileTrace.

Handles: XRY folder with .xrep XML, XRY ZIP containing .xrep.
Delegates to AIFT's mobile_ingest when available.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .base import BaseParser, ParsedCase

logger = logging.getLogger(__name__)


class XryParser(BaseParser):

    def can_handle(self, source_path: Path) -> bool:
        if source_path.is_dir():
            return bool(list(source_path.glob("*.xrep")) or list(source_path.rglob("*.xrep")))
        if source_path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(source_path) as zf:
                    return any(n.lower().endswith(".xrep") for n in zf.namelist())
            except Exception:
                return False
        return False

    def parse(self, source_path: Path, dest_dir: Path) -> ParsedCase:
        dest_dir.mkdir(parents=True, exist_ok=True)
        work_dir = source_path
        if source_path.is_file() and source_path.suffix.lower() == ".zip":
            work_dir = dest_dir / "xry_extracted"
            work_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(source_path) as zf:
                zf.extractall(work_dir)
        xrep_files = list(work_dir.glob("*.xrep")) or list(work_dir.rglob("*.xrep"))
        device_info = self._parse_xrep(xrep_files[0]) if xrep_files else {}
        db_paths = list(work_dir.rglob("*.db")) + list(work_dir.rglob("*.sqlite"))
        return ParsedCase(format="xry", device_info=device_info, raw_db_paths=db_paths)

    def _parse_xrep(self, xrep_path: Path) -> dict[str, Any]:
        meta = {"model": "Unknown", "imei": "Unknown", "os_version": "Unknown", "platform": "unknown"}
        try:
            root = ET.parse(xrep_path).getroot()
            for tag in ("DeviceInfo", "Device", "PhoneInfo"):
                node = root.find(f".//{tag}")
                if node is not None:
                    meta["model"] = (
                        node.findtext("DeviceName") or
                        node.findtext("Model") or
                        node.findtext("Name") or "Unknown"
                    ).strip()
                    meta["imei"] = (node.findtext("IMEI") or node.findtext("Imei") or "Unknown").strip()
                    meta["os_version"] = (
                        node.findtext("OS") or node.findtext("OSVersion") or "Unknown"
                    ).strip()
                    break
            os_l = meta["os_version"].lower()
            if "android" in os_l:
                meta["platform"] = "android"
            elif "ios" in os_l or "iphone" in os_l:
                meta["platform"] = "ios"
        except Exception as exc:
            logger.warning("XRY XREP parse error: %s", exc)
        return meta
