"""MobileTrace structured analysis engine.

Collects artifacts from the SQLite DB, formats them as text, and calls the
configured AI provider in parallel. Stores results back to analysis_results.
"""
from __future__ import annotations

import json
import logging
import re as _re
import sqlite3 as _sqlite3
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .ai_providers import AIProvider, AIProviderError, OpenRouterProvider, create_provider

logger = logging.getLogger(__name__)


def _parse_json_result(s: str) -> dict | None:
    """Parse a JSON string, applying common LLM formatting fixes on failure."""
    s = s.strip()
    if not s:
        return None
    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = _re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", s, _re.IGNORECASE)
    if fence_match:
        s = fence_match.group(1).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    cleaned = _re.sub(r'":\s*"([^"\\]*)"\s*:\s*[\d.]+', r'": "\1"', s)
    cleaned = _re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        return None


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "system_prompt.md"

_ARTIFACT_PROMPT_MAP = {
    "sms":       "sms_analysis.md",
    "whatsapp":  "whatsapp_analysis.md",
    "telegram":  "telegram_analysis.md",
    "signal":    "signal_analysis.md",
    "call_logs": "call_log_analysis.md",
    "contacts":  "contacts_analysis.md",
}

_MSG_LIMIT_DEFAULT = 500
_CONTACT_LIMIT_DEFAULT = 300
_CALL_LIMIT_DEFAULT = 300


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Prompt file not found: %s", path)
        return ""


def _load_system_prompt() -> str:
    try:
        return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "You are a digital forensics AI assistant."


def _format_messages(rows) -> str:
    lines = ["timestamp | direction | sender | recipient | body"]
    for r in rows:
        lines.append(
            f"{r['timestamp']} | {r['direction']} | {r['sender']} | {r['recipient']} | {r['body']}"
        )
    return "\n".join(lines)


def _format_contacts(rows) -> str:
    lines = ["name | phone | email | source_app"]
    for r in rows:
        lines.append(f"{r['name']} | {r['phone']} | {r['email']} | {r['source_app']}")
    return "\n".join(lines)


def _format_calls(rows) -> str:
    lines = ["timestamp | direction | number | duration_s | platform"]
    for r in rows:
        lines.append(
            f"{r['timestamp']} | {r['direction']} | {r['number']} | {r['duration_s']} | {r['platform']}"
        )
    return "\n".join(lines)


class MobileAnalyzer:
    """Parallel LLM analysis engine for MobileTrace cases."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.provider: AIProvider = create_provider(config)
        self._system_prompt = _load_system_prompt()
        _acfg = config.get("analysis", {})
        self._msg_limit = int(_acfg.get("max_messages_per_platform", _MSG_LIMIT_DEFAULT))
        self._call_limit = int(_acfg.get("max_calls", _CALL_LIMIT_DEFAULT))
        self._contact_limit = int(_acfg.get("max_contacts", _CONTACT_LIMIT_DEFAULT))

    def analyze_case(
        self,
        case_id: str,
        db,
        callback: Callable[[str, dict], None] | None = None,
        artifact_filter: list[str] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[dict[str, Any]]:
        """Run structured analysis for selected artifact types in a case.

        If artifact_filter is provided, only those artifact keys are analyzed.
        If cancel_event is set, remaining artifacts are skipped.
        """
        all_artifacts = self._collect_artifacts(case_id, db)

        # Apply filter
        if artifact_filter is not None:
            artifacts = {k: v for k, v in all_artifacts.items() if k in artifact_filter}
        else:
            artifacts = all_artifacts

        results: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(self._analyze_artifact, key, data): key
                for key, data in artifacts.items()
            }
            for future in as_completed(futures):
                # Check cancel before processing result
                if cancel_event and cancel_event.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

                artifact_key = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "artifact_key": artifact_key,
                        "result": "",
                        "error": str(exc),
                        "provider": self.provider.get_model_info().get("provider", "unknown"),
                    }
                    logger.warning("Analysis failed for %s: %s", artifact_key, exc)

                # Persist to DB with exponential-backoff retry on SQLITE_BUSY
                for _attempt in range(5):
                    try:
                        db.execute(
                            "INSERT OR REPLACE INTO analysis_results "
                            "(case_id, artifact_key, result, provider, status, error_message) VALUES (?,?,?,?,?,?)",
                            (case_id, artifact_key,
                             result.get("result", ""),
                             result.get("provider", ""),
                             "error" if result.get("error") else "ok",
                             result.get("error")),
                        )
                        db.commit()
                        break
                    except _sqlite3.OperationalError as exc:
                        if "locked" in str(exc).lower() and _attempt < 4:
                            time.sleep(0.05 * (2 ** _attempt))
                        else:
                            logger.warning("Could not persist analysis result for %s: %s", artifact_key, exc)
                            break
                    except Exception as exc:
                        logger.warning("Could not persist analysis result for %s: %s", artifact_key, exc)
                        break

                results.append(result)
                if callback:
                    try:
                        callback(artifact_key, result)
                    except Exception:
                        pass

        return results

    def analyze_multi(
        self,
        run_id: str,
        case_id: str,
        models: list[str],
        artifact_filter: list[str] | None,
        cancel_event: threading.Event | None,
        progress_callback: Callable[[str, dict], None] | None,
        db,
    ) -> None:
        """Run multi-model analysis: all models × all artifacts in parallel.

        Results are stored per (run_id, provider). After all complete,
        compute_consensus() is called to produce a consensus row.
        """
        from .database import get_db as _get_db

        all_artifacts = self._collect_artifacts(case_id, db)
        if artifact_filter is not None:
            artifacts = {k: v for k, v in all_artifacts.items() if k in artifact_filter}
        else:
            artifacts = all_artifacts

        # Build task list: (model, artifact_key, data)
        tasks = [
            (model, artifact_key, data)
            for model in models
            for artifact_key, data in artifacts.items()
        ]

        api_key = self.config.get("ai", {}).get("openrouter", {}).get("api_key", "")

        def _worker(task):
            model, artifact_key, data = task
            if cancel_event and cancel_event.is_set():
                return None
            if progress_callback:
                try:
                    progress_callback("model_artifact_started", {
                        "model": model, "artifact_key": artifact_key,
                    })
                except Exception:
                    pass
            result = self._analyze_artifact_for_model(
                model=model,
                artifact_key=artifact_key,
                data=data,
                run_id=run_id,
                case_id=case_id,
                api_key=api_key,
            )
            if progress_callback:
                try:
                    progress_callback("model_artifact_done", {
                        "model": model,
                        "artifact_key": artifact_key,
                        "error": result.get("error"),
                    })
                except Exception:
                    pass
            return result

        max_workers = min(len(tasks), 6) if tasks else 1
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_worker, task): task for task in tasks}
            for future in as_completed(futures):
                if cancel_event and cancel_event.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    result = future.result()
                    if result is None:
                        continue
                    # Persist to DB with exponential-backoff retry on SQLITE_BUSY
                    worker_db = _get_db()
                    for _attempt in range(5):
                        try:
                            worker_db.execute(
                                "INSERT OR REPLACE INTO analysis_results "
                                "(case_id, artifact_key, result, provider, run_id, status, error_message) VALUES (?,?,?,?,?,?,?)",
                                (case_id, result["artifact_key"],
                                 result.get("result", ""),
                                 result.get("provider", ""),
                                 run_id,
                                 "error" if result.get("error") else "ok",
                                 result.get("error")),
                            )
                            worker_db.commit()
                            break
                        except _sqlite3.OperationalError as exc:
                            if "locked" in str(exc).lower() and _attempt < 4:
                                time.sleep(0.05 * (2 ** _attempt))
                            else:
                                logger.warning("Could not persist multi-model result: %s", exc)
                                break
                        except Exception as exc:
                            logger.warning("Could not persist multi-model result: %s", exc)
                            break
                except Exception as exc:
                    logger.warning("Multi-model worker error: %s", exc)

        if cancel_event and cancel_event.is_set():
            return

        if progress_callback:
            try:
                progress_callback("consensus_computing", {"run_id": run_id})
            except Exception:
                pass

        # Use a fresh DB connection for consensus
        consensus_db = _get_db()
        self.compute_consensus(run_id, case_id, consensus_db)

    def _analyze_artifact_for_model(
        self,
        model: str,
        artifact_key: str,
        data: str,
        run_id: str,
        case_id: str,
        api_key: str,
    ) -> dict[str, Any]:
        """Call one specific OpenRouter model for one artifact."""
        try:
            provider = OpenRouterProvider(api_key=api_key, model=model)
        except Exception as exc:
            return {"artifact_key": artifact_key, "result": "", "error": str(exc), "provider": model}

        prompt_file = _ARTIFACT_PROMPT_MAP.get(artifact_key)
        instructions = _load_prompt(prompt_file) if prompt_file else (
            f"Analyze the following {artifact_key} data for forensic significance."
        )
        user_prompt = f"{instructions}\n\n## Data\n\n{data}"

        try:
            text = provider.analyze(
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                max_tokens=8192,
            )
            return {"artifact_key": artifact_key, "result": text, "provider": model}
        except AIProviderError as exc:
            return {"artifact_key": artifact_key, "result": "", "error": str(exc), "provider": model}

    def compute_consensus(self, run_id: str, case_id: str, db) -> None:
        """Merge multi-model results into a single consensus row per artifact."""
        rows = db.execute(
            "SELECT artifact_key, result, provider FROM analysis_results "
            "WHERE run_id=? AND provider != 'consensus'",
            (run_id,),
        ).fetchall()

        # Group: artifact_key → {provider: parsed_json}
        artifacts: dict[str, dict[str, Any]] = defaultdict(dict)
        for row in rows:
            try:
                parsed = _parse_json_result(row["result"] or "")
            except Exception:
                parsed = None
            if parsed:
                artifacts[row["artifact_key"]][row["provider"]] = parsed

        _RISK_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

        def _highest_risk(levels: list[str]) -> str:
            filtered = [l.upper() for l in levels if l.upper() in _RISK_ORDER]
            if not filtered:
                return "MEDIUM"
            return min(filtered, key=lambda l: _RISK_ORDER.index(l))

        for artifact_key, model_results in artifacts.items():
            consensus: dict[str, Any] = {}

            # ── conversation_risk_assessment ──────────────────────────────
            thread_map: dict[str, list[dict]] = defaultdict(list)
            for model, parsed in model_results.items():
                cra = parsed.get("conversation_risk_assessment") or []
                for t in cra:
                    tid = (t.get("thread_id") or t.get("phone_number")
                           or t.get("contact") or t.get("number") or "—")
                    thread_map[tid].append({**t, "_model": model})

            cra_consensus = []
            for tid, entries in thread_map.items():
                models_flagging = list({e["_model"] for e in entries})
                risk_scores = [int(e.get("risk_score") or 0) for e in entries]
                avg_score = round(sum(risk_scores) / len(risk_scores)) if risk_scores else 0
                highest = _highest_risk([e.get("risk_level") or "" for e in entries])

                seen_ki: set[str] = set()
                all_ki: list[str] = []
                for e in entries:
                    for ki in (e.get("key_indicators") or []):
                        if ki not in seen_ki:
                            all_ki.append(ki)
                            seen_ki.add(ki)

                cra_consensus.append({
                    "thread_id": tid,
                    "risk_level": highest,
                    "risk_score": avg_score,
                    "messages": max((e.get("messages") or 0) for e in entries),
                    "sent": max((e.get("sent") or 0) for e in entries),
                    "received": max((e.get("received") or 0) for e in entries),
                    "key_indicators": all_ki,
                    "corroborated_by": models_flagging,
                    "confidence": "HIGH" if len(models_flagging) >= 2 else "MEDIUM",
                })

            cra_consensus.sort(key=lambda t: (
                _RISK_ORDER.index(t["risk_level"]) if t["risk_level"] in _RISK_ORDER else 99,
                -len(t["corroborated_by"]),
            ))
            consensus["conversation_risk_assessment"] = cra_consensus

            # ── risk_level_summary ────────────────────────────────────────
            rls_list: list[str] = []
            for parsed in model_results.values():
                rls = str(parsed.get("risk_level_summary") or parsed.get("risk_level") or "")
                m = _re.search(r'\b(CRITICAL|HIGH|MEDIUM|LOW)\b', rls, _re.IGNORECASE)
                if m:
                    rls_list.append(m.group(1).upper())
            if rls_list:
                consensus["risk_level_summary"] = _highest_risk(rls_list)

            # ── key_findings ──────────────────────────────────────────────
            finding_map: dict[str, list[dict]] = defaultdict(list)
            for model, parsed in model_results.items():
                kf = parsed.get("key_findings") or {}
                if isinstance(kf, list):
                    top = kf
                else:
                    top = kf.get("top_significant_conversations") or []
                for f in top:
                    tid = (f.get("thread_id") or f.get("thread_number")
                           or f.get("contact") or "")
                    finding_map[tid].append({**f, "_model": model})

            top_findings = []
            for tid, entries in finding_map.items():
                entry = entries[0]
                top_findings.append({
                    "thread_id": tid,
                    "summary": (entry.get("summary") or entry.get("significance")
                                or entry.get("key_details") or ""),
                    "key_messages": entry.get("key_messages") or [],
                    "corroborated_by": list({e["_model"] for e in entries}),
                })
            top_findings.sort(key=lambda f: -len(f["corroborated_by"]))
            consensus["key_findings"] = {"top_significant_conversations": top_findings}

            # ── crime_indicators (if any model returned them) ─────────────
            crime_map: dict[str, list[dict]] = defaultdict(list)
            for model, parsed in model_results.items():
                for c in (parsed.get("crime_indicators") or []):
                    cat = c.get("category") or ""
                    crime_map[cat].append({**c, "_model": model})
            if crime_map:
                crime_list = []
                for cat, entries in crime_map.items():
                    models_flagging = list({e["_model"] for e in entries})
                    entry = entries[0]
                    crime_list.append({
                        **{k: v for k, v in entry.items() if not k.startswith("_")},
                        "corroborated_by": models_flagging,
                        "confidence": "HIGH" if len(models_flagging) >= 2 else "MEDIUM",
                    })
                crime_list.sort(key=lambda c: -len(c["corroborated_by"]))
                consensus["crime_indicators"] = crime_list

            # Store consensus row
            try:
                db.execute(
                    "INSERT OR REPLACE INTO analysis_results "
                    "(case_id, artifact_key, result, provider, run_id) VALUES (?,?,?,'consensus',?)",
                    (case_id, artifact_key, json.dumps(consensus), run_id),
                )
                db.commit()
            except Exception as exc:
                logger.warning("Could not store consensus for %s: %s", artifact_key, exc)

    def _collect_artifacts(self, case_id: str, db) -> dict[str, str]:
        """Return dict of artifact_key → formatted text ready for LLM."""
        artifacts: dict[str, str] = {}

        # Per-platform messages
        for platform in ("sms", "whatsapp", "telegram", "signal"):
            rows = db.execute(
                "SELECT sender, recipient, body, timestamp, direction FROM messages "
                "WHERE case_id=? AND platform=? ORDER BY timestamp ASC LIMIT ?",
                (case_id, platform, self._msg_limit),
            ).fetchall()
            if rows:
                total = db.execute(
                    "SELECT COUNT(*) FROM messages WHERE case_id=? AND platform=?",
                    (case_id, platform),
                ).fetchone()[0]
                pct = (len(rows) / total * 100) if total else 100.0
                coverage = (
                    f"## Data Coverage\n"
                    f"Records provided: {len(rows)} of {total} total ({pct:.1f}%)\n\n"
                )
                artifacts[platform] = coverage + _format_messages(rows)

        # Call logs
        rows = db.execute(
            "SELECT number, direction, duration_s, timestamp, platform FROM call_logs "
            "WHERE case_id=? ORDER BY timestamp ASC LIMIT ?",
            (case_id, self._call_limit),
        ).fetchall()
        if rows:
            total = db.execute(
                "SELECT COUNT(*) FROM call_logs WHERE case_id=?",
                (case_id,),
            ).fetchone()[0]
            pct = (len(rows) / total * 100) if total else 100.0
            coverage = (
                f"## Data Coverage\n"
                f"Records provided: {len(rows)} of {total} total ({pct:.1f}%)\n\n"
            )
            artifacts["call_logs"] = coverage + _format_calls(rows)

        # Contacts
        rows = db.execute(
            "SELECT name, phone, email, source_app FROM contacts "
            "WHERE case_id=? ORDER BY name ASC LIMIT ?",
            (case_id, self._contact_limit),
        ).fetchall()
        if rows:
            total = db.execute(
                "SELECT COUNT(*) FROM contacts WHERE case_id=?",
                (case_id,),
            ).fetchone()[0]
            pct = (len(rows) / total * 100) if total else 100.0
            coverage = (
                f"## Data Coverage\n"
                f"Records provided: {len(rows)} of {total} total ({pct:.1f}%)\n\n"
            )
            artifacts["contacts"] = coverage + _format_contacts(rows)

        return artifacts

    def _analyze_artifact(self, artifact_key: str, data: str) -> dict[str, Any]:
        """Call LLM for one artifact. Returns a result dict."""
        prompt_file = _ARTIFACT_PROMPT_MAP.get(artifact_key)
        if prompt_file:
            instructions = _load_prompt(prompt_file)
        else:
            instructions = f"Analyze the following {artifact_key} data for forensic significance."

        user_prompt = f"{instructions}\n\n## Data\n\n{data}"

        try:
            text = self.provider.analyze(
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                max_tokens=8192,
            )
            info = self.provider.get_model_info()
            provider_str = info.get("provider", "unknown")
            model_str = info.get("model", "")
            return {
                "artifact_key": artifact_key,
                "result": text,
                "provider": f"{provider_str} · {model_str}" if model_str else provider_str,
            }
        except AIProviderError as exc:
            return {
                "artifact_key": artifact_key,
                "result": "",
                "error": str(exc),
                "provider": self.provider.get_model_info().get("provider", "unknown"),
            }
