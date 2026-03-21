"""Case CRUD routes for MobileTrace."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from app.database import get_db
from app.parsers.dispatcher import dispatch, detect_format

bp_cases = Blueprint("cases", __name__, url_prefix="/api")


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


@bp_cases.get("/")
def index():
    return render_template("index.html")


@bp_cases.post("/cases")
def create_case():
    body = request.get_json() or {}
    title = body.get("title", "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    case_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        """INSERT INTO cases (id, title, case_number, officer, status)
           VALUES (?, ?, ?, ?, 'open')""",
        (case_id, title, body.get("case_number"), body.get("officer")),
    )
    db.commit()
    row = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    return jsonify(_row_to_dict(row)), 201


_RISK_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
_RISK_RANK_TO_LEVEL = {v: k for k, v in _RISK_RANK.items()}
import re as _re


def _parse_risk_level(result_text: str) -> str | None:
    """Extract the highest risk level mentioned in a JSON analysis result."""
    if not result_text:
        return None
    try:
        parsed = json.loads(result_text)
    except Exception:
        # Try to extract from raw text
        m = _re.search(r'\b(CRITICAL|HIGH|MEDIUM|LOW)\b', result_text)
        return m.group(1) if m else None
    if not isinstance(parsed, dict):
        return None
    # Check risk_level_summary / risk_level fields
    for field in ("risk_level_summary", "risk_level", "risk_classification", "overall_assessment"):
        val = str(parsed.get(field) or "")
        m = _re.search(r'\b(CRITICAL|HIGH|MEDIUM|LOW)\b', val, _re.I)
        if m:
            return m.group(1).upper()
    # Check conversation_risk_assessment items
    cra = parsed.get("conversation_risk_assessment") or []
    best = 0
    for item in (cra if isinstance(cra, list) else []):
        lvl = (item.get("risk_level") or "").upper()
        best = max(best, _RISK_RANK.get(lvl, 0))
    return _RISK_RANK_TO_LEVEL.get(best) if best else None


@bp_cases.get("/cases")
def list_cases():
    status = request.args.get("status")
    db = get_db()
    if status:
        rows = db.execute(
            "SELECT * FROM cases WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM cases ORDER BY created_at DESC"
        ).fetchall()
    cases = [_row_to_dict(r) for r in rows]
    if cases:
        case_ids = [c["id"] for c in cases]
        placeholders = ",".join("?" * len(case_ids))
        analysis_rows = db.execute(
            f"SELECT case_id, result FROM analysis_results WHERE case_id IN ({placeholders})",
            case_ids,
        ).fetchall()
        # Build max risk per case
        risk_map: dict[str, int] = {}
        for ar in analysis_rows:
            lvl = _parse_risk_level(ar["result"] or "")
            rank = _RISK_RANK.get(lvl, 0) if lvl else 0
            risk_map[ar["case_id"]] = max(risk_map.get(ar["case_id"], 0), rank)
        for c in cases:
            rank = risk_map.get(c["id"], 0)
            c["risk_level"] = _RISK_RANK_TO_LEVEL.get(rank) if rank else None
    return jsonify(cases)


@bp_cases.get("/cases/<case_id>")
def get_case(case_id: str):
    row = get_db().execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(_row_to_dict(row))


@bp_cases.patch("/cases/<case_id>")
def update_case(case_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    body = request.get_json() or {}
    allowed = {"title", "status", "officer", "case_number", "device_info"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return jsonify({"error": "no valid fields"}), 400
    updates["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    db.execute(
        f"UPDATE cases SET {set_clause} WHERE id=?",
        (*updates.values(), case_id),
    )
    db.commit()
    updated = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    return jsonify(_row_to_dict(updated))


@bp_cases.delete("/cases/<case_id>")
def delete_case(case_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM cases WHERE id=?", (case_id,))
    db.commit()
    return jsonify({"deleted": case_id})


def _allowed_evidence_path(resolved: Path, cfg) -> bool:
    """Check if a resolved path is under an allowed evidence directory."""
    cases_dir = Path(cfg["server"]["cases_dir"])
    allowed = [
        Path("/opt/mobiletrace/evidence").resolve(),
        Path("/opt/aift/evidence").resolve(),
        (cases_dir.parent / "evidence").resolve(),
    ]
    return any(str(resolved).startswith(str(a)) for a in allowed)


@bp_cases.post("/cases/<case_id>/evidence/scan")
def scan_folder(case_id: str):
    """Scan a directory for importable forensic files and databases."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    body = request.get_json() or {}
    folder = body.get("folder_path", "").strip()
    if not folder:
        return jsonify({"error": "folder_path is required"}), 400

    folder_path = Path(folder)
    if not folder_path.is_dir():
        return jsonify({"error": f"not a directory: {folder}"}), 400

    cfg = current_app.config["MT_CONFIG"]
    if not _allowed_evidence_path(folder_path.resolve(), cfg):
        return jsonify({"error": "path not in allowed evidence directories"}), 403

    from app.parsers.folder_parser import FolderParser
    result = FolderParser.scan_folder(folder_path)
    return jsonify(result)


@bp_cases.post("/cases/<case_id>/evidence/import-folder")
def import_folder(case_id: str):
    """Import selected archives and/or platform databases from a scanned folder."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    cfg = current_app.config["MT_CONFIG"]
    cases_dir = Path(cfg["server"]["cases_dir"])
    case_dir = cases_dir / case_id

    body = request.get_json() or {}
    folder_path = body.get("folder_path", "").strip()
    archives = body.get("archives", [])
    platforms = body.get("platforms", [])
    signal_key = body.get("signal_key", "").strip()

    if not folder_path:
        return jsonify({"error": "folder_path is required"}), 400
    resolved = Path(folder_path).resolve()
    if not _allowed_evidence_path(resolved, cfg):
        return jsonify({"error": "path not in allowed evidence directories"}), 403

    imported = []
    errors = []

    # ── Import selected archive files via existing pipeline ──
    for arc_path in archives:
        arc = Path(arc_path)
        if not arc.exists():
            errors.append({"path": arc_path, "error": "file not found"})
            continue
        try:
            fmt = detect_format(arc) or "unknown"
            ev_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO evidence_files (id, case_id, format, source_path, parse_status) VALUES (?,?,?,?,?)",
                (ev_id, case_id, fmt, str(arc), "parsing"),
            )
            db.commit()
            extract_dir = case_dir / "extracted"
            parsed = dispatch(arc, extract_dir, signal_key=signal_key)
            _store_parsed(db, case_id, parsed)
            db.execute(
                "UPDATE evidence_files SET parse_status='done', parsed_at=datetime('now') WHERE id=?",
                (ev_id,),
            )
            if parsed.device_info:
                db.execute(
                    "UPDATE cases SET device_info=?, updated_at=datetime('now') WHERE id=?",
                    (json.dumps(parsed.device_info), case_id),
                )
            db.commit()
            imported.append({
                "type": "archive", "path": arc_path, "format": fmt,
                "stats": {"contacts": len(parsed.contacts), "messages": len(parsed.messages), "calls": len(parsed.call_logs)},
            })
        except Exception as exc:
            db.execute(
                "UPDATE evidence_files SET parse_status='error', parse_error=? WHERE id=?",
                (str(exc), ev_id),
            )
            db.commit()
            errors.append({"path": arc_path, "error": str(exc)})

    # ── Import platform databases from folder ──
    from app.parsers.folder_parser import FolderParser
    fp = FolderParser()
    for platform in platforms:
        try:
            ev_id = str(uuid.uuid4())
            fmt = f"folder_{platform}"
            db.execute(
                "INSERT INTO evidence_files (id, case_id, format, source_path, parse_status) VALUES (?,?,?,?,?)",
                (ev_id, case_id, fmt, folder_path, "parsing"),
            )
            db.commit()
            parsed = fp.parse(Path(folder_path), case_dir / "extracted", platform=platform, signal_key=signal_key)
            _store_parsed(db, case_id, parsed)
            db.execute(
                "UPDATE evidence_files SET parse_status='done', parsed_at=datetime('now') WHERE id=?",
                (ev_id,),
            )
            if parsed.device_info:
                db.execute(
                    "UPDATE cases SET device_info=?, updated_at=datetime('now') WHERE id=?",
                    (json.dumps(parsed.device_info), case_id),
                )
            db.commit()
            imported.append({
                "type": "folder", "platform": platform,
                "stats": {"contacts": len(parsed.contacts), "messages": len(parsed.messages), "calls": len(parsed.call_logs)},
                "warnings": parsed.warnings,
            })
        except Exception as exc:
            db.execute(
                "UPDATE evidence_files SET parse_status='error', parse_error=? WHERE id=?",
                (str(exc), ev_id),
            )
            db.commit()
            errors.append({"platform": platform, "error": str(exc)})

    return jsonify({"imported": imported, "errors": errors}), 201


@bp_cases.post("/cases/<case_id>/evidence")
def upload_evidence(case_id: str):
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    cfg = current_app.config["MT_CONFIG"]
    cases_dir = Path(cfg["server"]["cases_dir"])
    case_dir = cases_dir / case_id

    # ── Local path mode (JSON body with source_path) ──────────────────────────
    if request.is_json:
        body = request.get_json() or {}
        src = body.get("source_path", "").strip()
        if not src:
            return jsonify({"error": "source_path is required"}), 400
        source_path = Path(src)
        if not source_path.exists():
            return jsonify({"error": f"file not found: {src}"}), 400
        # Resolve path must be under an allowed prefix for safety
        if not _allowed_evidence_path(source_path.resolve(), cfg):
            return jsonify({"error": "path not in allowed evidence directories"}), 403
        signal_key = body.get("signal_key", "").strip()
        return _ingest_path(db, case_id, case_dir, source_path, signal_key=signal_key)

    # ── File upload mode ──────────────────────────────────────────────────────
    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400

    f = request.files["file"]
    evidence_dir = case_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(f.filename).name
    dest_path = evidence_dir / safe_name
    f.save(dest_path)
    signal_key = request.form.get("signal_key", "").strip()
    return _ingest_path(db, case_id, case_dir, dest_path, signal_key=signal_key)


def _ingest_path(db, case_id: str, case_dir: Path, source_path: Path, signal_key: str = ""):
    """Parse a file already on disk and store the result."""
    fmt = detect_format(source_path) or "unknown"
    ev_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO evidence_files (id, case_id, format, source_path, parse_status) VALUES (?,?,?,?,?)",
        (ev_id, case_id, fmt, str(source_path), "parsing"),
    )
    db.commit()

    try:
        extract_dir = case_dir / "extracted"
        parsed = dispatch(source_path, extract_dir, signal_key=signal_key)
        _store_parsed(db, case_id, parsed)
        db.execute(
            "UPDATE evidence_files SET parse_status='done', parsed_at=datetime('now') WHERE id=?",
            (ev_id,),
        )
        db.execute(
            "UPDATE cases SET device_info=?, updated_at=datetime('now') WHERE id=?",
            (json.dumps(parsed.device_info), case_id),
        )
        db.commit()
        return jsonify({
            "evidence_id": ev_id,
            "format": fmt,
            "device_info": parsed.device_info,
            "stats": {
                "contacts": len(parsed.contacts),
                "messages": len(parsed.messages),
                "calls": len(parsed.call_logs),
            },
            "warnings": parsed.warnings,
        }), 201
    except Exception as exc:
        db.execute(
            "UPDATE evidence_files SET parse_status='error', parse_error=? WHERE id=?",
            (str(exc), ev_id),
        )
        db.commit()
        return jsonify({"error": str(exc)}), 422


@bp_cases.delete("/cases/<case_id>/evidence/<evidence_id>")
def delete_evidence(case_id: str, evidence_id: str):
    db = get_db()
    row = db.execute(
        "SELECT id FROM evidence_files WHERE id=? AND case_id=?",
        (evidence_id, case_id),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM evidence_files WHERE id=?", (evidence_id,))
    db.commit()
    return jsonify({"deleted": evidence_id})


@bp_cases.get("/cases/<case_id>/threads")
def get_threads(case_id: str):
    row = get_db().execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db = get_db()
    rows = db.execute(
        """
        SELECT
            platform,
            COALESCE(thread_id,
                CASE WHEN direction='incoming' THEN sender ELSE recipient END
            ) AS thread,
            COUNT(*) AS message_count,
            MAX(timestamp) AS last_ts,
            MIN(timestamp) AS first_ts
        FROM messages
        WHERE case_id = ?
        GROUP BY platform, thread
        ORDER BY last_ts DESC
        """,
        (case_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp_cases.get("/cases/<case_id>/messages")
def get_messages(case_id: str):
    row = get_db().execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    db = get_db()
    platform = request.args.get("platform")
    thread = request.args.get("thread")
    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 200)), 500)
    offset = int(request.args.get("offset", 0))

    if q:
        from app.retriever import _sanitize_fts_query
        safe_q = _sanitize_fts_query(q)
        if not safe_q:
            return jsonify([])
        try:
            rows = db.execute(
                """
                SELECT m.id, m.platform, m.direction, m.sender, m.recipient,
                       m.body, m.timestamp, m.thread_id
                FROM messages_fts
                JOIN messages m ON messages_fts.rowid = m.id
                WHERE messages_fts MATCH ? AND m.case_id = ?
                ORDER BY rank
                LIMIT ? OFFSET ?
                """,
                (safe_q, case_id, limit, offset),
            ).fetchall()
        except Exception:
            rows = []
        return jsonify([dict(r) for r in rows])

    # Direct query with optional filters
    clauses = ["m.case_id = ?"]
    params: list = [case_id]
    if platform:
        clauses.append("m.platform = ?")
        params.append(platform)
    if thread:
        clauses.append(
            "(m.thread_id = ? OR "
            "(m.thread_id IS NULL AND "
            "CASE WHEN m.direction='incoming' THEN m.sender ELSE m.recipient END = ?))"
        )
        params.extend([thread, thread])
    params.extend([limit, offset])
    rows = db.execute(
        f"""
        SELECT m.*,
               mf.id         AS media_id,
               mf.mime_type  AS mime_type,
               mf.filename   AS media_filename,
               mf.size_bytes AS media_size
        FROM messages m
        LEFT JOIN (
            SELECT * FROM media_files mf2
            WHERE mf2.id = (
                SELECT id FROM media_files
                WHERE message_id = mf2.message_id
                ORDER BY extracted_at ASC LIMIT 1
            )
        ) mf ON mf.message_id = m.id
        WHERE {' AND '.join(clauses)}
        ORDER BY m.timestamp ASC LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp_cases.get("/cases/<case_id>/contacts")
def get_contacts(case_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone():
        abort(404)
    rows = db.execute(
        "SELECT id, name, phone, email, source_app, source FROM contacts WHERE case_id=?",
        (case_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


def _store_parsed(db, case_id: str, parsed) -> None:
    """Insert ParsedCase artifacts into DB tables."""
    for c in parsed.contacts:
        db.execute(
            "INSERT OR IGNORE INTO contacts"
            " (case_id, name, phone, email, source_app, raw_json, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (case_id, c["name"], c["phone"], c["email"],
             c["source_app"], json.dumps(c.get("raw_json") or {}), c.get("source")),
        )
    for m in parsed.messages:
        db.execute(
            "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id, raw_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (case_id, m["platform"], m["direction"], m["sender"], m["recipient"],
             m["body"], m["timestamp"], m["thread_id"], json.dumps(m["raw_json"])),
        )
    for cl in parsed.call_logs:
        db.execute(
            "INSERT INTO call_logs (case_id, number, direction, duration_s, timestamp, platform) VALUES (?,?,?,?,?,?)",
            (case_id, cl["number"], cl["direction"], cl["duration_s"], cl["timestamp"], cl["platform"]),
        )

    # Media files (A4) — copy extracted media to cases dir and record in DB
    cfg = current_app.config["MT_CONFIG"]
    cases_dir = Path(cfg["server"]["cases_dir"])
    media_dir = cases_dir / case_id / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    for mf in getattr(parsed, "media_files", []):
        if mf.get("size_bytes", 0) > 50 * 1024 * 1024:
            continue  # skip files > 50 MB
        tmp_path_val = mf.get("tmp_path")
        if not tmp_path_val:
            continue
        tmp = Path(tmp_path_val)
        if not tmp.exists():
            continue
        ext = tmp.suffix.lower()
        media_id = str(uuid.uuid4())
        dest = media_dir / f"{media_id}{ext}"
        shutil.copy2(tmp, dest)
        rel_path = f"{case_id}/media/{media_id}{ext}"
        db.execute(
            "INSERT INTO media_files"
            " (id, case_id, message_id, filename, mime_type, size_bytes, filepath)"
            " VALUES (?,?,?,?,?,?,?)",
            (media_id, case_id, mf.get("message_id"),
             mf["filename"], mf["mime_type"], mf.get("size_bytes"), rel_path),
        )

    db.commit()
