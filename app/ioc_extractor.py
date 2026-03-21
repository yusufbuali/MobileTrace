"""IOC Extractor — deterministic regex scan over MobileTrace message/contact data.

Returns a structured dict ready for JSON serialisation.
No Flask, no DB — accepts plain Python lists for easy unit testing.
"""
from __future__ import annotations

import re
from typing import Any


# ── Regex patterns ────────────────────────────────────────────────────────────

_RE_PHONE = re.compile(
    r"(?<!\w)(\+?[0-9][\d\s\-().]{7,15}[0-9])(?!\w)"
)
_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
_RE_URL = re.compile(
    r"https?://[^\s\"'<>]+"
)
_RE_BTC = re.compile(
    r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b"
)
_RE_ETH = re.compile(
    r"\b0x[a-fA-F0-9]{40}\b"
)
_RE_IP = re.compile(
    r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"
)
_RE_COORDS = re.compile(
    r"-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}"
)


_MAX_SOURCES = 5


# ── Normalisation helpers ────────────────────────────────────────────────────

def _normalise_phone(raw: str) -> str:
    """Strip whitespace, dashes, dots, parentheses from a phone match."""
    return re.sub(r"[\s\-().]+", "", raw)


def _is_private_ip(ip: str) -> bool:
    """Return True for RFC-1918, loopback, link-local, and invalid (out-of-range) addresses."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return False
    if not all(0 <= o <= 255 for o in octets):
        return True  # reject out-of-range as non-routable
    o1, o2 = octets[0], octets[1]
    return (
        o1 == 10
        or (o1 == 172 and 16 <= o2 <= 31)
        or (o1 == 192 and o2 == 168)
        or o1 == 127
        or (o1 == 169 and o2 == 254)
    )


# ── Core extractor ────────────────────────────────────────────────────────────

def _scan_text(
    text: str,
    source: dict[str, str],
    hits: dict[tuple, dict],
) -> None:
    """Scan *text* for all IOC types; accumulate results into *hits*."""
    if not text:
        return

    # Phone
    for m in _RE_PHONE.finditer(text):
        raw = m.group(1)
        norm = _normalise_phone(raw)
        if len(norm.lstrip("+")) < 7:
            continue
        key = ("phone", norm)
        _add_hit(hits, key, "phone", norm, source, text)

    # Email
    for m in _RE_EMAIL.finditer(text):
        val = m.group(0).lower()
        key = ("email", val)
        _add_hit(hits, key, "email", val, source, text)

    # URL
    for m in _RE_URL.finditer(text):
        val = m.group(0).rstrip(".,;)")
        key = ("url", val)
        _add_hit(hits, key, "url", val, source, text)

    # Both BTC and ETH addresses are classified as type "crypto" (see design doc)
    # BTC
    for m in _RE_BTC.finditer(text):
        val = m.group(0)
        key = ("crypto", val)
        _add_hit(hits, key, "crypto", val, source, text)

    # ETH
    for m in _RE_ETH.finditer(text):
        val = m.group(0).lower()
        key = ("crypto", val)
        _add_hit(hits, key, "crypto", val, source, text)

    # IP
    for m in _RE_IP.finditer(text):
        val = m.group(0)
        if not _is_private_ip(val):
            key = ("ip", val)
            _add_hit(hits, key, "ip", val, source, text)

    # Coords
    for m in _RE_COORDS.finditer(text):
        val = m.group(0)
        key = ("coords", val)
        _add_hit(hits, key, "coords", val, source, text)


def _add_hit(
    hits: dict,
    key: tuple,
    ioc_type: str,
    value: str,
    source: dict,
    text: str,
) -> None:
    if key not in hits:
        hits[key] = {
            "type": ioc_type,
            "value": value,
            "occurrences": 0,
            "first_seen": source.get("timestamp", ""),
            "last_seen": source.get("timestamp", ""),
            "sources": [],
        }
    entry = hits[key]
    entry["occurrences"] += 1
    ts = source.get("timestamp", "")
    if ts and (not entry["first_seen"] or ts < entry["first_seen"]):
        entry["first_seen"] = ts
    if ts and ts > entry["last_seen"]:
        entry["last_seen"] = ts
    if len(entry["sources"]) < _MAX_SOURCES:
        snippet = text[:120].replace("\n", " ")
        entry["sources"].append({
            "platform": source.get("platform", ""),
            "thread_id": source.get("thread_id", ""),
            "message_id": source.get("id", ""),
            "timestamp": ts,
            "snippet": snippet,
        })


# ── Public API ────────────────────────────────────────────────────────────────

def extract_iocs(
    messages: list[dict[str, Any]],
    contacts: list[dict[str, Any]],
    ioc_type_filter: str = "",
) -> dict[str, Any]:
    """Extract and deduplicate IOCs from message bodies and contact records.

    Args:
        messages: list of dicts with keys id, body, platform, thread_id, timestamp
        contacts: list of dicts with keys phone, email
        ioc_type_filter: if set, return only IOCs of this type

    Returns:
        { "iocs": [...], "summary": { "total": N, "by_type": {...} } }
    """
    hits: dict[tuple, dict] = {}

    for msg in messages:
        source = {
            "id": msg.get("id", ""),
            "platform": msg.get("platform", ""),
            "thread_id": msg.get("thread_id", ""),
            "timestamp": msg.get("timestamp", ""),
        }
        _scan_text(msg.get("body") or "", source, hits)

    for contact in contacts:
        source = {"id": "", "platform": "contacts", "thread_id": "", "timestamp": ""}
        _scan_text(contact.get("phone") or "", source, hits)
        _scan_text(contact.get("email") or "", source, hits)

    all_iocs = list(hits.values())

    by_type: dict[str, int] = {}
    for ioc in all_iocs:
        by_type[ioc["type"]] = by_type.get(ioc["type"], 0) + 1

    iocs = [i for i in all_iocs if i["type"] == ioc_type_filter] if ioc_type_filter else all_iocs

    return {
        "iocs": iocs,
        "summary": {"total": len(iocs), "by_type": by_type},
    }
