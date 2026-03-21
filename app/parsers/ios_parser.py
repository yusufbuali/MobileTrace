"""iOS full-filesystem parser for MobileTrace.

Handles:
  - iOS TAR dumps  (private/var/mobile/ structure)
  - iOS ZIP dumps  (/private/var/mobile/ structure)

Extracts SMS, contacts, call history, and WhatsApp (if present).
Apple Core Data epoch offset: 978307200 s (seconds since 2001-01-01).
"""
from __future__ import annotations

import logging
import sqlite3
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import BaseParser, ParsedCase

logger = logging.getLogger(__name__)

# Apple Core Data epoch = Unix epoch for 2001-01-01T00:00:00Z
_APPLE_EPOCH_OFFSET = 978307200

# Target DB paths (relative, no leading slash)
_TARGET_DBS = {
    "sms":      "private/var/mobile/Library/SMS/sms.db",
    "contacts": "private/var/mobile/Library/AddressBook/AddressBook.sqlitedb",
    "calls":    "private/var/mobile/Library/CallHistoryDB/CallHistory.storedata",
}

# Suffix-matched containers (UUID app container paths)
_SUFFIX_TARGETS: dict[str, str] = {
    "whatsapp": "Documents/ChatStorage.sqlite",
    "telegram": "Documents/Telegram/postbox/db/db",  # no file extension
}

# iOS filesystem markers used for format detection
_IOS_MARKERS = [
    "private/var/mobile/",
    "private/var/root/",
    "private/var/wireless/",
]


def _is_ios_path(name: str) -> bool:
    stripped = name.lstrip("/")
    return any(stripped.startswith(m) for m in _IOS_MARKERS)


def _apple_ts_to_iso(ts: float | int | None) -> str:
    """Convert Apple Core Data timestamp to ISO-8601 UTC string."""
    if ts is None:
        return ""
    try:
        ts = float(ts)
        if ts <= 0:
            return ""
        # Nanoseconds on iOS 17+ — divide down
        if ts > 1e12:
            ts = ts / 1_000_000_000
        elif ts > 1e9:
            ts = ts / 1_000
        unix_ts = ts + _APPLE_EPOCH_OFFSET
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()
    except Exception:
        return str(ts)


class iOSParser(BaseParser):
    """Parse iOS full-filesystem TAR or ZIP dumps."""

    # ── Format detection ──────────────────────────────────────────────────────

    def can_handle(self, source_path: Path) -> bool:
        ext = source_path.suffix.lower()
        if ext == ".tar":
            return self._tar_has_ios_markers(source_path)
        if ext == ".zip":
            return self._zip_has_ios_markers(source_path)
        return False

    def _tar_has_ios_markers(self, path: Path, max_check: int = 5000) -> bool:
        try:
            with tarfile.open(path, "r:*") as tf:
                for i, m in enumerate(tf):
                    if i >= max_check:
                        break
                    if _is_ios_path(m.name):
                        return True
        except Exception:
            pass
        return False

    def _zip_has_ios_markers(self, path: Path) -> bool:
        try:
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist()[:5000]:
                    if _is_ios_path(name):
                        return True
        except Exception:
            pass
        return False

    # ── Main parse ────────────────────────────────────────────────────────────

    def parse(self, source_path: Path, dest_dir: Path, **kwargs) -> ParsedCase:
        dest_dir.mkdir(parents=True, exist_ok=True)
        ext = source_path.suffix.lower()
        try:
            if ext == ".zip":
                db_paths = self._extract_from_zip(source_path, dest_dir)
            else:
                db_paths = self._extract_from_tar(source_path, dest_dir)
        except Exception as exc:
            return ParsedCase(format="ios_fs", warnings=[f"Extraction failed: {exc}"])

        result = ParsedCase(format="ios_fs")
        result.raw_db_paths = list(db_paths.values())
        warnings: list[str] = []

        result.device_info = self._read_device_info(db_paths)
        result.contacts = self._read_contacts(db_paths.get("contacts"), warnings)
        result.messages = self._read_sms(db_paths.get("sms"), warnings)
        result.messages += self._read_whatsapp(db_paths.get("whatsapp"), warnings)
        result.messages += self._read_telegram_ios(db_paths.get("telegram"), warnings)
        result.call_logs = self._read_calls(db_paths.get("calls"), warnings)

        # C3: recover contacts from messaging metadata if AddressBook is empty
        if not result.contacts:
            recovered = self._recover_contacts_ios(
                wa_db_path=db_paths.get("whatsapp"),
                tg_db_path=db_paths.get("telegram"),
                parsed_messages=result.messages,
                warnings=warnings,
            )
            result.contacts.extend(recovered)
            if recovered:
                warnings.append(
                    f"AddressBook empty — recovered {len(recovered)} contacts from messaging data"
                )

        result.warnings = warnings
        return result

    # ── Extraction helpers ────────────────────────────────────────────────────

    def _build_wanted_map(self, names: list[str]) -> dict[str, str]:
        """Return {archive_path: db_key} for the DBs we want."""
        norm = {n.lstrip("/"): n for n in names}
        wanted: dict[str, str] = {}

        for key, rel_path in _TARGET_DBS.items():
            if rel_path in norm:
                wanted[norm[rel_path]] = key

        for stripped, orig in norm.items():
            for key, suffix in _SUFFIX_TARGETS.items():
                if stripped.endswith(suffix) and key not in wanted:
                    wanted[orig] = key
                    break

        return wanted

    def _extract_from_zip(self, path: Path, dest: Path) -> dict[str, Path]:
        extracted: dict[str, Path] = {}
        with zipfile.ZipFile(path) as zf:
            wanted = self._build_wanted_map(zf.namelist())
            for arc_name, key in wanted.items():
                out_path = dest / f"ios_{key}.db"
                try:
                    with zf.open(arc_name) as src, open(out_path, "wb") as dst:
                        dst.write(src.read())
                    extracted[key] = out_path
                    logger.info("Extracted %s -> %s", arc_name, out_path.name)
                except Exception as exc:
                    logger.warning("Failed to extract %s: %s", arc_name, exc)
        return extracted

    def _extract_from_tar(self, path: Path, dest: Path) -> dict[str, Path]:
        extracted: dict[str, Path] = {}
        with tarfile.open(path, "r:*") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
            wanted = self._build_wanted_map(names)
            for arc_name, key in wanted.items():
                out_path = dest / f"ios_{key}.db"
                try:
                    member = tf.getmember(arc_name)
                    f = tf.extractfile(member)
                    if f:
                        out_path.write_bytes(f.read())
                        extracted[key] = out_path
                        logger.info("Extracted %s -> %s", arc_name, out_path.name)
                except Exception as exc:
                    logger.warning("Failed to extract %s: %s", arc_name, exc)
        return extracted

    # ── DB readers ────────────────────────────────────────────────────────────

    def _open_db(self, path: Path | None) -> sqlite3.Connection | None:
        if not path or not path.exists():
            return None
        try:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as exc:
            logger.warning("Cannot open %s: %s", path, exc)
            return None

    def _read_device_info(self, db_paths: dict) -> dict[str, Any]:
        info: dict[str, Any] = {"platform": "ios"}
        conn = self._open_db(db_paths.get("sms"))
        if conn:
            try:
                row = conn.execute(
                    "SELECT id FROM handle WHERE id LIKE '+%' LIMIT 1"
                ).fetchone()
                if row:
                    info["sample_contact"] = row["id"]
            except Exception:
                pass
            finally:
                conn.close()
        return info

    def _read_contacts(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            if path:
                warnings.append("Contacts DB not found or unreadable")
            return []
        contacts = []
        try:
            rows = conn.execute("""
                SELECT ABPerson.ROWID,
                       ABPerson.First, ABPerson.Last,
                       ABMultiValue.value,
                       ABMultiValueLabel.value AS label_type
                FROM ABPerson
                LEFT JOIN ABMultiValue ON ABPerson.ROWID = ABMultiValue.record_id
                LEFT JOIN ABMultiValueLabel ON ABMultiValue.label = ABMultiValueLabel.ROWID
                ORDER BY ABPerson.ROWID
            """).fetchall()

            people: dict[int, dict] = {}
            for r in rows:
                pid = r["ROWID"]
                first = (r["First"] or "").strip()
                last = (r["Last"] or "").strip()
                name = f"{first} {last}".strip() or f"Contact {pid}"
                if pid not in people:
                    people[pid] = {"name": name, "phone": "", "email": "", "raw": []}
                val = (r["value"] or "").strip()
                ltype = (r["label_type"] or "").lower()
                if val:
                    if "@" in val:
                        if not people[pid]["email"]:
                            people[pid]["email"] = val
                    elif any(c.isdigit() for c in val):
                        if not people[pid]["phone"]:
                            people[pid]["phone"] = val
                    people[pid]["raw"].append({"label": ltype, "value": val})

            for person in people.values():
                contacts.append(self._norm_contact(
                    name=person["name"],
                    phone=person["phone"],
                    email=person["email"],
                    source_app="ios_addressbook",
                    raw={"values": person["raw"]},
                ))
        except Exception as exc:
            warnings.append(f"Contacts parse error: {exc}")
        finally:
            conn.close()
        return contacts

    def _read_sms(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            if path:
                warnings.append("SMS DB not found or unreadable")
            return []
        msgs = []
        try:
            # Build message_id -> chat_identifier (group thread ID)
            msg_chat: dict[int, str] = {}
            try:
                for r in conn.execute(
                    "SELECT cmj.message_id, c.chat_identifier"
                    " FROM chat_message_join cmj JOIN chat c ON cmj.chat_id = c.ROWID"
                ).fetchall():
                    msg_chat[r["message_id"]] = r["chat_identifier"]
            except Exception:
                pass

            # Build message_id -> attachments list
            msg_att: dict[int, list] = {}
            try:
                for r in conn.execute(
                    "SELECT maj.message_id, a.mime_type, a.transfer_name"
                    " FROM message_attachment_join maj"
                    " JOIN attachment a ON maj.attachment_id = a.ROWID"
                ).fetchall():
                    msg_att.setdefault(r["message_id"], []).append({
                        "mime_type": r["mime_type"] or "",
                        "filename": r["transfer_name"] or "",
                    })
            except Exception:
                pass

            # cache_roomnames exists in iOS 12+; fall back gracefully for older schemas
            try:
                rows = conn.execute("""
                    SELECT m.ROWID, h.id AS address, m.date AS ts,
                           m.text AS body, m.is_from_me AS from_me,
                           m.cache_roomnames AS room
                    FROM message m
                    LEFT JOIN handle h ON m.handle_id = h.ROWID
                    ORDER BY m.date ASC
                """).fetchall()
                has_room = True
            except Exception:
                rows = conn.execute("""
                    SELECT m.ROWID, h.id AS address, m.date AS ts,
                           m.text AS body, m.is_from_me AS from_me
                    FROM message m
                    LEFT JOIN handle h ON m.handle_id = h.ROWID
                    ORDER BY m.date ASC
                """).fetchall()
                has_room = False
            for r in rows:
                from_me = bool(r["from_me"])
                addr = r["address"] or "unknown"
                mid = r["ROWID"]
                room = r["room"] if has_room else None
                thread_id = msg_chat.get(mid) or room or addr
                attachments = msg_att.get(mid, [])
                raw = {"attachments": attachments} if attachments else {}
                body = r["body"] or (f"[{len(attachments)} attachment(s)]" if attachments else "")
                msgs.append(self._norm_message(
                    platform="sms",
                    body=body,
                    sender="device" if from_me else addr,
                    recipient=addr if from_me else "device",
                    direction="outgoing" if from_me else "incoming",
                    timestamp=_apple_ts_to_iso(r["ts"]),
                    thread_id=thread_id,
                    raw=raw,
                ))
        except Exception as exc:
            warnings.append(f"SMS parse error: {exc}")
        finally:
            conn.close()
        return msgs

    def _read_telegram_ios(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            return []  # optional — no warning if absent
        msgs = []
        try:
            peer_names: dict[int, str] = {}
            try:
                for r in conn.execute(
                    "SELECT id, phone, first_name, last_name FROM peers"
                ).fetchall():
                    name = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()
                    peer_names[r["id"]] = name or r["phone"] or str(r["id"])
            except Exception:
                pass
            rows = conn.execute(
                "SELECT mid, peer_id, timestamp, message, outgoing"
                " FROM messages WHERE message IS NOT NULL AND message != ''"
                " ORDER BY timestamp ASC"
            ).fetchall()
            for r in rows:
                from_me = bool(r["outgoing"])
                peer = peer_names.get(r["peer_id"], str(r["peer_id"]))
                msgs.append(self._norm_message(
                    platform="telegram",
                    body=r["message"] or "",
                    sender="device" if from_me else peer,
                    recipient=peer if from_me else "device",
                    direction="outgoing" if from_me else "incoming",
                    timestamp=_apple_ts_to_iso(r["timestamp"]),
                    thread_id=str(r["peer_id"]),
                ))
        except Exception as exc:
            warnings.append(f"Telegram iOS parse error: {exc}")
        finally:
            conn.close()
        return msgs

    def _read_calls(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            if path:
                warnings.append("CallHistory DB not found or unreadable")
            return []
        calls = []
        try:
            rows = conn.execute("""
                SELECT Z_PK, ZADDRESS, ZDURATION, ZDATE, ZORIGINATED, ZANSWERED
                FROM ZCALLRECORD ORDER BY ZDATE ASC
            """).fetchall()
            for r in rows:
                originated = bool(r["ZORIGINATED"])
                answered = bool(r["ZANSWERED"])
                if not answered and not originated:
                    direction = "missed"
                elif originated:
                    direction = "outgoing"
                else:
                    direction = "incoming"
                calls.append(self._norm_call(
                    number=r["ZADDRESS"] or "",
                    direction=direction,
                    duration_s=int(r["ZDURATION"] or 0),
                    timestamp=_apple_ts_to_iso(r["ZDATE"]),
                    platform="phone",
                ))
        except Exception as exc:
            warnings.append(f"Call history parse error: {exc}")
        finally:
            conn.close()
        return calls

    def _recover_contacts_ios(
        self,
        wa_db_path,
        tg_db_path,
        parsed_messages: list,
        warnings: list,
    ) -> list:
        """Reconstruct contacts from messaging metadata when AddressBook is empty."""
        import sqlite3 as _sq3
        recovered: dict[str, dict] = {}  # normalized_phone → contact dict

        def _add(name, phone, source_app):
            norm = self._norm_phone(phone)
            key = norm or name  # fall back to name if phone is empty
            if key and key not in recovered:
                recovered[key] = self._norm_contact(
                    name=name, phone=norm, email="",
                    source_app=source_app, source="recovered"
                )

        # 1. WhatsApp wa_contacts
        if wa_db_path and Path(wa_db_path).exists():
            try:
                conn = _sq3.connect(str(wa_db_path))
                conn.row_factory = _sq3.Row
                for row in conn.execute(
                    "SELECT display_name, number FROM wa_contacts"
                    " WHERE display_name IS NOT NULL AND display_name != ''"
                ).fetchall():
                    _add(row["display_name"], row["number"] or "", "whatsapp_contacts")
                conn.close()
            except Exception as e:
                warnings.append(f"Contact recovery (WhatsApp iOS): {e}")

        # 2. Telegram peers table
        if tg_db_path and Path(tg_db_path).exists():
            try:
                conn = _sq3.connect(str(tg_db_path))
                conn.row_factory = _sq3.Row
                for row in conn.execute(
                    "SELECT phone, first_name, last_name FROM peers"
                    " WHERE phone IS NOT NULL AND phone != ''"
                ).fetchall():
                    name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
                    _add(name or row["phone"], row["phone"], "telegram_peers")
                conn.close()
            except Exception as e:
                warnings.append(f"Contact recovery (Telegram iOS): {e}")

        # 3. SMS sender names from already-parsed messages
        for msg in parsed_messages:
            if msg.get("platform") != "sms":
                continue
            raw = msg.get("raw_json") or {}
            name = raw.get("contact_name") or ""
            phone = raw.get("address") or msg.get("sender") or ""
            if name and phone:
                _add(name, phone, "sms_metadata")

        return list(recovered.values())

    def _read_whatsapp(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            return []  # optional — no warning if absent
        msgs = []
        try:
            rows = conn.execute("""
                SELECT ZWACHATSESSION.ZCONTACTJID AS chat_jid,
                       ZWAMESSAGE.ZFROMJID        AS sender_jid,
                       ZWAMESSAGE.ZTEXT           AS body,
                       ZWAMESSAGE.ZMESSAGEDATE    AS ts,
                       ZWAMESSAGE.ZISFROMME       AS from_me
                FROM ZWAMESSAGE
                JOIN ZWACHATSESSION
                    ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK
                WHERE ZWAMESSAGE.ZTEXT IS NOT NULL AND ZWAMESSAGE.ZTEXT != ''
                ORDER BY ZWAMESSAGE.ZMESSAGEDATE ASC
            """).fetchall()
            for r in rows:
                from_me = bool(r["from_me"])
                peer = (r["sender_jid"] or r["chat_jid"] or "unknown").split("@")[0]
                msgs.append(self._norm_message(
                    platform="whatsapp",
                    body=r["body"] or "",
                    sender="device" if from_me else peer,
                    recipient=peer if from_me else "device",
                    direction="outgoing" if from_me else "incoming",
                    timestamp=_apple_ts_to_iso(r["ts"]),
                    thread_id=r["chat_jid"] or peer,
                ))
        except Exception as exc:
            warnings.append(f"WhatsApp parse error: {exc}")
        finally:
            conn.close()
        return msgs
