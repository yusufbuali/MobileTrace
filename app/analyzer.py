"""MobileTrace structured analysis engine.

Collects artifacts from the SQLite DB, formats them as text, and calls the
configured AI provider in parallel. Stores results back to analysis_results.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .ai_providers import AIProvider, AIProviderError, create_provider

logger = logging.getLogger(__name__)

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

_MSG_LIMIT = 500
_CONTACT_LIMIT = 300
_CALL_LIMIT = 300


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

    def analyze_case(
        self,
        case_id: str,
        db,
        callback: Callable[[str, dict], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Run structured analysis for all artifact types in a case.

        Returns a list of result dicts, each with keys:
        ``artifact_key``, ``result`` (LLM text), ``provider``, and optionally ``error``.
        """
        artifacts = self._collect_artifacts(case_id, db)
        results: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(self._analyze_artifact, key, data): key
                for key, data in artifacts.items()
            }
            for future in as_completed(futures):
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

                # Persist to DB (best-effort)
                try:
                    db.execute(
                        "INSERT OR REPLACE INTO analysis_results (case_id, artifact_key, result) VALUES (?,?,?)",
                        (case_id, artifact_key, result.get("result", result.get("error", ""))),
                    )
                    db.commit()
                except Exception as exc:
                    logger.warning("Could not persist analysis result for %s: %s", artifact_key, exc)

                results.append(result)
                if callback:
                    try:
                        callback(artifact_key, result)
                    except Exception:
                        pass

        return results

    def _collect_artifacts(self, case_id: str, db) -> dict[str, str]:
        """Return dict of artifact_key → formatted text ready for LLM."""
        artifacts: dict[str, str] = {}

        # Per-platform messages
        for platform in ("sms", "whatsapp", "telegram", "signal"):
            rows = db.execute(
                "SELECT sender, recipient, body, timestamp, direction FROM messages "
                "WHERE case_id=? AND platform=? ORDER BY timestamp ASC LIMIT ?",
                (case_id, platform, _MSG_LIMIT),
            ).fetchall()
            if rows:
                artifacts[platform] = _format_messages(rows)

        # Call logs
        rows = db.execute(
            "SELECT number, direction, duration_s, timestamp, platform FROM call_logs "
            "WHERE case_id=? ORDER BY timestamp ASC LIMIT ?",
            (case_id, _CALL_LIMIT),
        ).fetchall()
        if rows:
            artifacts["call_logs"] = _format_calls(rows)

        # Contacts
        rows = db.execute(
            "SELECT name, phone, email, source_app FROM contacts "
            "WHERE case_id=? ORDER BY name ASC LIMIT ?",
            (case_id, _CONTACT_LIMIT),
        ).fetchall()
        if rows:
            artifacts["contacts"] = _format_contacts(rows)

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
            return {
                "artifact_key": artifact_key,
                "result": text,
                "provider": self.provider.get_model_info().get("provider", "unknown"),
            }
        except AIProviderError as exc:
            return {
                "artifact_key": artifact_key,
                "result": "",
                "error": str(exc),
                "provider": self.provider.get_model_info().get("provider", "unknown"),
            }
