"""Settings routes — GET/POST /api/settings and GET /api/settings/test."""
from __future__ import annotations

import time
import urllib.request
import json as _json
from copy import deepcopy
from pathlib import Path

import yaml
from flask import Blueprint, current_app, jsonify, request

from app.config import _deep_merge
from app.ai_providers import create_provider, AIProviderError

bp_settings = Blueprint("settings", __name__, url_prefix="/api")


def _mask_config(cfg: dict) -> dict:
    """Return a deep copy of cfg with API keys masked."""
    out = deepcopy(cfg)
    for provider_cfg in out.get("ai", {}).values():
        if isinstance(provider_cfg, dict) and "api_key" in provider_cfg:
            key = provider_cfg["api_key"]
            if len(key) > 4:
                provider_cfg["api_key"] = "●" * 8 + key[-4:]
            elif key:
                provider_cfg["api_key"] = "●" * len(key)
    return out


@bp_settings.get("/settings")
def get_settings():
    """Return current config with API keys masked."""
    cfg = current_app.config["MT_CONFIG"]
    return jsonify(_mask_config(cfg))


@bp_settings.post("/settings")
def update_settings():
    """Deep-merge request body into config, persist to config.yaml, reload."""
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    cfg = current_app.config["MT_CONFIG"]
    new_cfg = _deep_merge(cfg, body)

    # Write config.yaml (next to the app entrypoint / WORKDIR)
    config_path = current_app.config.get("MT_CONFIG_PATH", "config.yaml")
    p = Path(config_path)
    with open(p, "w") as f:
        yaml.safe_dump(new_cfg, f, default_flow_style=False, allow_unicode=True)

    # Reload into live config (no restart needed)
    current_app.config["MT_CONFIG"] = new_cfg
    return jsonify({"status": "saved"})


@bp_settings.get("/settings/test")
def test_provider():
    """Send a minimal prompt to validate the current AI provider."""
    cfg = current_app.config["MT_CONFIG"]
    provider_name = cfg["ai"].get("provider", "claude")
    try:
        provider = create_provider(cfg)
        t0 = time.monotonic()
        result = provider.analyze("You are a test assistant.", "Reply with exactly: ok", max_tokens=16)
        latency_ms = int((time.monotonic() - t0) * 1000)
        return jsonify({
            "status": "ok",
            "provider": provider_name,
            "model": cfg["ai"].get(provider_name, {}).get("model", ""),
            "response": result[:50],
            "latency_ms": latency_ms,
        })
    except AIProviderError as exc:
        return jsonify({"status": "error", "provider": provider_name, "error": str(exc)}), 200
    except Exception as exc:
        return jsonify({"status": "error", "provider": provider_name, "error": str(exc)}), 200


@bp_settings.get("/settings/openrouter-credits")
def openrouter_credits():
    """Fetch credit/usage info from OpenRouter for the configured API key."""
    cfg = current_app.config["MT_CONFIG"]
    api_key = cfg["ai"].get("openrouter", {}).get("api_key", "")
    if not api_key:
        return jsonify({"error": "OpenRouter API key not configured"}), 400

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read()).get("data", {})

        usage = data.get("usage", 0)
        limit = data.get("limit")
        is_free_tier = data.get("is_free_tier", False)
        label = data.get("label", "")

        result = {
            "usage": usage,
            "limit": limit,
            "is_free_tier": is_free_tier,
            "label": label,
        }

        if limit is None:
            result["remaining"] = None
            result["limit_type"] = "unlimited"
        else:
            result["remaining"] = round(limit - usage, 4)

        return jsonify(result)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        return jsonify({"error": f"OpenRouter auth error ({exc.code}): {body}"}), 502
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@bp_settings.get("/settings/openrouter-models")
def openrouter_models():
    """Fetch available models from OpenRouter, with pricing and context window."""
    cfg = current_app.config["MT_CONFIG"]
    api_key = cfg["ai"].get("openrouter", {}).get("api_key", "")
    if not api_key:
        return jsonify({"error": "OpenRouter API key not configured"}), 400

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}", "HTTP-Referer": "http://localhost:5001"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())

        models = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            # Skip internal OpenRouter routing entries (no real model behind them)
            if model_id.startswith("openrouter/"):
                continue
            name = m.get("name") or model_id
            ctx = m.get("context_length", 0)
            pricing = m.get("pricing", {})
            # OpenRouter pricing: USD per token → convert to per 1M tokens
            try:
                prompt_per_m = round(float(pricing.get("prompt", 0)) * 1_000_000, 4)
                completion_per_m = round(float(pricing.get("completion", 0)) * 1_000_000, 4)
            except (TypeError, ValueError):
                prompt_per_m = completion_per_m = 0
            # Skip entries with nonsensical negative pricing
            if prompt_per_m < 0 or completion_per_m < 0:
                continue
            models.append({
                "id": model_id,
                "name": name,
                "context_length": ctx,
                "prompt_per_m": prompt_per_m,
                "completion_per_m": completion_per_m,
            })

        # Sort: free models first, then by prompt cost ascending
        models.sort(key=lambda x: (x["prompt_per_m"] > 0, x["prompt_per_m"]))
        return jsonify(models)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502
