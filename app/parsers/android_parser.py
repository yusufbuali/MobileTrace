"""Android data-partition parser for MobileTrace.

Handles:
  - Magnet Acquire ZIP  (.zip containing a TAR with data/data/ structure)
  - Raw Android TAR    (.tar with data/data/ structure)

Parseable artifacts:
  - SMS/MMS         : com.android.providers.telephony / mmssms.db
  - Call log        : com.android.providers.contacts / calllog.db
  - Contacts        : com.android.providers.contacts / contacts2.db
  - WhatsApp msgs   : com.whatsapp / msgstore.db  (old + new schema)
  - WhatsApp ctcts  : com.whatsapp / wa.db
  - Telegram        : org.telegram.messenger / cache4.db  (text via regex)

Signal is SQLCipher-encrypted — skipped with a warning.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import BaseParser, ParsedCase

logger = logging.getLogger(__name__)

# Android call-type mapping
_CALL_TYPE = {1: "incoming", 2: "outgoing", 3: "missed",
              4: "voicemail", 5: "rejected", 6: "blocked"}

# Target DB paths (relative, inside the TAR)
_TARGETS: dict[str, str] = {
    "sms":      "data/data/com.android.providers.telephony/databases/mmssms.db",
    "calllog":  "data/data/com.android.providers.contacts/databases/calllog.db",
    "contacts": "data/data/com.android.providers.contacts/databases/contacts2.db",
    "wa_msg":   "data/data/com.whatsapp/databases/msgstore.db",
    "wa_ct":    "data/data/com.whatsapp/databases/wa.db",
    "telegram": "data/data/org.telegram.messenger/files/cache4.db",
    "signal":   "data/data/org.thoughtcrime.securesms/databases/signal.db",
}

# Android data-partition markers
_ANDROID_MARKERS = ["data/data/", "data/user/"]


def _ms_to_iso(ms: int | None) -> str:
    """Unix milliseconds → ISO-8601 UTC string."""
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return str(ms)


def _s_to_iso(s: int | None) -> str:
    """Unix seconds → ISO-8601 UTC string."""
    if not s:
        return ""
    try:
        return datetime.fromtimestamp(s, tz=timezone.utc).isoformat()
    except Exception:
        return str(s)


def _extract_strings(blob: bytes, min_len: int = 4) -> list[str]:
    """Pull printable ASCII strings from a binary blob."""
    return [m.decode("ascii", errors="ignore")
            for m in re.findall(rb"[\x20-\x7e]{%d,}" % min_len, blob)]


class AndroidParser(BaseParser):
    """Parse Android data-partition TAR or Magnet Acquire ZIP+TAR."""

    # ── Format detection ──────────────────────────────────────────────────────

    def can_handle(self, source_path: Path) -> bool:
        ext = source_path.suffix.lower()
        if ext == ".tar":
            return self._tar_has_android_markers(source_path)
        if ext == ".zip":
            return self._zip_has_android_tar(source_path)
        return False

    def _tar_has_android_markers(self, path: Path, max_check: int = 5000) -> bool:
        try:
            with tarfile.open(path, "r:*") as tf:
                for i, m in enumerate(tf):
                    if i >= max_check:
                        break
                    if any(m.name.startswith(mk) for mk in _ANDROID_MARKERS):
                        return True
        except Exception:
            pass
        return False

    def _zip_has_android_tar(self, path: Path) -> bool:
        """Check if ZIP contains a TAR whose first entries have data/data/ paths."""
        try:
            with zipfile.ZipFile(path) as z:
                tars = [n for n in z.namelist()
                        if n.endswith(".tar") or n.endswith(".tar.gz")]
                if not tars:
                    return False
                with z.open(tars[0]) as stream:
                    with tarfile.open(fileobj=stream, mode="r|") as tf:
                        for i, m in enumerate(tf):
                            if i >= 5000:
                                break
                            if any(m.name.startswith(mk) for mk in _ANDROID_MARKERS):
                                return True
        except Exception:
            pass
        return False

    # ── Main parse ────────────────────────────────────────────────────────────

    def parse(self, source_path: Path, dest_dir: Path, signal_key: str = "") -> ParsedCase:
        dest_dir.mkdir(parents=True, exist_ok=True)
        ext = source_path.suffix.lower()
        try:
            if ext == ".zip":
                db_paths = self._extract_from_magnet_zip(source_path, dest_dir)
            else:
                db_paths = self._extract_from_tar(source_path, dest_dir)
        except Exception as exc:
            return ParsedCase(format="android_tar", warnings=[f"Extraction failed: {exc}"])

        result = ParsedCase(format="android_tar")
        result.raw_db_paths = list(db_paths.values())
        warnings: list[str] = []

        result.device_info = {"platform": "android"}
        result.contacts = self._read_contacts(db_paths.get("contacts"), warnings)
        result.contacts += self._read_wa_contacts(db_paths.get("wa_ct"), warnings)
        result.messages = self._read_sms(db_paths.get("sms"), warnings)
        result.messages += self._read_whatsapp(db_paths.get("wa_msg"), warnings)
        result.messages += self._read_telegram(db_paths.get("telegram"), warnings)
        result.messages += self._read_signal(db_paths.get("signal"), warnings, signal_key=signal_key)
        result.call_logs = self._read_calls(db_paths.get("calllog"), warnings)

        # C3: recover contacts from messaging metadata if contacts DBs are empty
        if not result.contacts:
            recovered = self._recover_contacts_android(
                wa_db_path=db_paths.get("wa_ct"),
                tg_db_path=db_paths.get("telegram"),
                parsed_messages=result.messages,
                warnings=warnings,
            )
            result.contacts.extend(recovered)
            if recovered:
                warnings.append(
                    f"contacts2.db empty — recovered {len(recovered)} contacts from messaging data"
                )

        result.warnings = warnings
        return result

    # ── Extraction ────────────────────────────────────────────────────────────

    def _extract_from_magnet_zip(self, path: Path, dest: Path) -> dict[str, Path]:
        """Extract from Magnet Acquire ZIP (ZIP → TAR → DBs)."""
        with zipfile.ZipFile(path) as z:
            tars = [n for n in z.namelist()
                    if n.endswith(".tar") or n.endswith(".tar.gz")]
            if not tars:
                raise ValueError("No TAR found inside ZIP")
            with z.open(tars[0]) as stream:
                return self._extract_from_stream(stream, dest)

    def _extract_from_tar(self, path: Path, dest: Path) -> dict[str, Path]:
        with open(path, "rb") as f:
            return self._extract_from_stream(f, dest, gz=path.suffix == ".gz")

    def _extract_from_stream(
        self, stream, dest: Path, gz: bool = False
    ) -> dict[str, Path]:
        mode = "r:gz" if gz else "r|"
        wanted = {v: k for k, v in _TARGETS.items()}
        extracted: dict[str, Path] = {}

        with tarfile.open(fileobj=stream, mode=mode) as tf:
            for m in tf:
                if m.name in wanted:
                    key = wanted[m.name]
                    out_path = dest / f"android_{key}.db"
                    f = tf.extractfile(m)
                    if f:
                        out_path.write_bytes(f.read())
                        extracted[key] = out_path
                        logger.info("Extracted %s → %s", m.name, out_path.name)
                if len(extracted) == len(_TARGETS):
                    break

        return extracted

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _open_db(self, path: Path | None) -> sqlite3.Connection | None:
        if not path or not path.exists():
            return None
        try:
            # Check for SQLCipher (non-SQLite magic)
            magic = open(path, "rb").read(16)
            if magic[:6] != b"SQLite":
                logger.warning("%s is not a plain SQLite database (possibly encrypted)", path.name)
                return None
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as exc:
            logger.warning("Cannot open %s: %s", path, exc)
            return None

    # ── Parsers ───────────────────────────────────────────────────────────────

    def _read_sms(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            if path:
                warnings.append("SMS DB not found or unreadable")
            return []
        msgs = []
        try:
            rows = conn.execute(
                "SELECT address, body, date, type FROM sms ORDER BY date ASC"
            ).fetchall()
            for r in rows:
                direction = "outgoing" if r["type"] == 2 else "incoming"
                addr = r["address"] or "unknown"
                msgs.append(self._norm_message(
                    platform="sms",
                    body=r["body"] or "",
                    sender="device" if direction == "outgoing" else addr,
                    recipient=addr if direction == "outgoing" else "device",
                    direction=direction,
                    timestamp=_ms_to_iso(r["date"]),
                    thread_id=addr,
                ))
        except Exception as exc:
            warnings.append(f"SMS parse error: {exc}")
        finally:
            conn.close()
        return msgs

    def _read_calls(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            if path:
                warnings.append("Call log DB not found or unreadable")
            return []
        calls = []
        try:
            rows = conn.execute(
                "SELECT number, date, duration, type FROM calls ORDER BY date ASC"
            ).fetchall()
            for r in rows:
                calls.append(self._norm_call(
                    number=r["number"] or "",
                    direction=_CALL_TYPE.get(r["type"], "unknown"),
                    duration_s=int(r["duration"] or 0),
                    timestamp=_ms_to_iso(r["date"]),
                    platform="phone",
                ))
        except Exception as exc:
            warnings.append(f"Call log parse error: {exc}")
        finally:
            conn.close()
        return calls

    def _read_contacts(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            if path:
                warnings.append("Contacts DB not found or unreadable")
            return []
        contacts = []
        try:
            rows = conn.execute("""
                SELECT rc.display_name, d.data1, m.mimetype
                FROM raw_contacts rc
                JOIN data d ON rc._id = d.raw_contact_id
                JOIN mimetypes m ON d.mimetype_id = m._id
                WHERE m.mimetype IN (
                    'vnd.android.cursor.item/phone_v2',
                    'vnd.android.cursor.item/email_v2',
                    'vnd.android.cursor.item/name'
                )
                ORDER BY rc._id
            """).fetchall()

            people: dict[str, dict] = {}
            for r in rows:
                name = r["display_name"] or "Unknown"
                if name not in people:
                    people[name] = {"name": name, "phone": "", "email": ""}
                val = r["data1"] or ""
                mt = r["mimetype"]
                if "phone" in mt and not people[name]["phone"]:
                    people[name]["phone"] = val
                elif "email" in mt and not people[name]["email"]:
                    people[name]["email"] = val

            for p in people.values():
                if p["name"] == "Unknown" and not p["phone"] and not p["email"]:
                    continue
                contacts.append(self._norm_contact(
                    name=p["name"],
                    phone=p["phone"],
                    email=p["email"],
                    source_app="android_contacts",
                ))
        except Exception as exc:
            warnings.append(f"Contacts parse error: {exc}")
        finally:
            conn.close()
        return contacts

    def _read_wa_contacts(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            return []
        contacts = []
        try:
            rows = conn.execute(
                "SELECT jid, display_name, number FROM wa_contacts "
                "WHERE display_name IS NOT NULL AND display_name != '' "
                "ORDER BY _id"
            ).fetchall()
            for r in rows:
                contacts.append(self._norm_contact(
                    name=r["display_name"] or r["number"] or r["jid"],
                    phone=r["number"] or r["jid"].split("@")[0],
                    email="",
                    source_app="whatsapp_contacts",
                ))
        except Exception as exc:
            warnings.append(f"WhatsApp contacts parse error: {exc}")
        finally:
            conn.close()
        return contacts

    def _read_whatsapp(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            if path:
                warnings.append("WhatsApp messages DB not found or unreadable")
            return []
        msgs = []
        try:
            # Try old schema first (messages table with data column)
            rows = conn.execute("""
                SELECT key_remote_jid, data, timestamp, key_from_me
                FROM messages
                WHERE data IS NOT NULL AND data != ''
                ORDER BY timestamp ASC
            """).fetchall()

            if not rows:
                # New schema: message table with text_data
                rows = conn.execute("""
                    SELECT m.text_data AS data, m.timestamp, m.from_me AS key_from_me,
                           j.raw_string AS key_remote_jid
                    FROM message m
                    LEFT JOIN jid j ON m.chat_row_id = j._id
                    WHERE m.text_data IS NOT NULL AND m.text_data != ''
                    ORDER BY m.timestamp ASC
                """).fetchall()

            for r in rows:
                from_me = bool(r["key_from_me"])
                peer = (r["key_remote_jid"] or "unknown").split("@")[0]
                msgs.append(self._norm_message(
                    platform="whatsapp",
                    body=r["data"] or "",
                    sender="device" if from_me else peer,
                    recipient=peer if from_me else "device",
                    direction="outgoing" if from_me else "incoming",
                    timestamp=_ms_to_iso(r["timestamp"]),
                    thread_id=r["key_remote_jid"] or peer,
                ))
        except Exception as exc:
            warnings.append(f"WhatsApp messages parse error: {exc}")
        finally:
            conn.close()
        return msgs

    def _read_telegram(self, path: Path | None, warnings: list) -> list[dict]:
        conn = self._open_db(path)
        if not conn:
            if path:
                warnings.append("Telegram DB not found or unreadable")
            return []
        msgs = []
        try:
            # Load uid → name from user_contacts_v7
            uid_names: dict[int, str] = {}
            try:
                for r in conn.execute(
                    "SELECT uid, fname, sname FROM user_contacts_v7"
                ).fetchall():
                    name = f"{r['fname'] or ''} {r['sname'] or ''}".strip()
                    uid_names[r["uid"]] = name or str(r["uid"])
            except Exception:
                pass

            rows = conn.execute(
                "SELECT uid, mid, date, data, out FROM messages_v2 "
                "WHERE data IS NOT NULL ORDER BY date ASC"
            ).fetchall()

            for r in rows:
                blob = r["data"]
                if not isinstance(blob, bytes):
                    continue
                # Extract readable text strings from TLV binary
                strings = _extract_strings(blob, min_len=6)
                # Filter out noise: keep strings that look like messages
                text_parts = [
                    s for s in strings
                    if len(s) >= 6
                    and not s.startswith("http")
                    and not all(c in "0123456789abcdefABCDEF-_. " for c in s)
                ]
                if not text_parts:
                    continue
                body = text_parts[0]  # best-guess first meaningful string

                from_me = bool(r["out"])
                peer_uid = r["uid"]
                peer = uid_names.get(peer_uid, str(peer_uid))

                msgs.append(self._norm_message(
                    platform="telegram",
                    body=body,
                    sender="device" if from_me else peer,
                    recipient=peer if from_me else "device",
                    direction="outgoing" if from_me else "incoming",
                    timestamp=_s_to_iso(r["date"]),
                    thread_id=str(peer_uid),
                ))
        except Exception as exc:
            warnings.append(f"Telegram parse error: {exc}")
        finally:
            conn.close()
        return msgs

    def _recover_contacts_android(
        self,
        wa_db_path,
        tg_db_path,
        parsed_messages: list,
        warnings: list,
    ) -> list:
        """Reconstruct contacts from messaging metadata when contacts2.db is empty."""
        recovered = self._recover_from_wa_sms(wa_db_path, parsed_messages, warnings, "Android")

        # Telegram user_contacts_v7 (Android schema)
        conn = self._open_db(tg_db_path)
        if conn:
            try:
                for row in conn.execute(
                    "SELECT uid, fname, sname FROM user_contacts_v7"
                ).fetchall():
                    name = f"{row['fname'] or ''} {row['sname'] or ''}".strip()
                    key = name or str(row["uid"])
                    if key and key not in recovered:
                        recovered[key] = self._norm_contact(
                            name=name or str(row["uid"]), phone="", email="",
                            source_app="telegram_contacts", source="recovered",
                        )
            except Exception as e:
                warnings.append(f"Contact recovery (Telegram Android): {e}")
            finally:
                conn.close()

        return list(recovered.values())

    def _read_signal(self, path: Path | None, warnings: list, signal_key: str = "") -> list[dict]:
        if not path or not path.exists():
            return []
        if not signal_key:
            warnings.append(
                "Signal database found but no decryption key provided. "
                "Supply the 64-char hex SQLCipher key via the Evidence upload form."
            )
            return []
        try:
            from pysqlcipher3 import dbapi2 as sqlcipher
        except ImportError:
            warnings.append("pysqlcipher3 not installed — cannot decrypt Signal database.")
            return []
        msgs = []
        conn = None
        try:
            conn = sqlcipher.connect(str(path))
            conn.row_factory = sqlcipher.Row
            key_hex = signal_key.strip().lower()
            conn.execute(f"PRAGMA key = \"x'{key_hex}'\";")
            conn.execute("PRAGMA cipher_page_size = 4096;")
            conn.execute("SELECT count(*) FROM sqlite_master;")  # validate key works
            rows = conn.execute(
                "SELECT body, date_sent, date_received, address, type"
                " FROM sms ORDER BY date_sent ASC"
            ).fetchall()
            for r in rows:
                direction = "outgoing" if r["type"] == 2 else "incoming"
                addr = r["address"] or "unknown"
                msgs.append(self._norm_message(
                    platform="signal",
                    body=r["body"] or "",
                    sender="device" if direction == "outgoing" else addr,
                    recipient=addr if direction == "outgoing" else "device",
                    direction=direction,
                    timestamp=_ms_to_iso(r["date_sent"] or r["date_received"]),
                    thread_id=addr,
                ))
        except Exception as exc:
            warnings.append(f"Signal decrypt failed: {exc}")
        finally:
            if conn:
                conn.close()
        return msgs
