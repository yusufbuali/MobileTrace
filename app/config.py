"""Configuration loading for MobileTrace."""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "ai": {
        "provider": "claude",
        "claude": {
            "api_key": "",
            "model": "claude-sonnet-4-6",
        },
        "openai": {
            "api_key": "",
            "model": "gpt-4o",
        },
        "openrouter": {
            "api_key": "",
            "model": "anthropic/claude-sonnet-4",
            "base_url": "https://openrouter.ai/api/v1",
        },
        "local": {
            "base_url": "http://localhost:11434/v1",
            "model": "llama3.1:8b",
            "api_key": "not-needed",
        },
    },
    "server": {
        "port": 5001,
        "host": "0.0.0.0",
        "max_upload_mb": 2048,
        "database_path": "data/mobiletrace.db",
        "cases_dir": "data/cases",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    cfg = deepcopy(DEFAULT_CONFIG)
    # Env overrides
    if os.environ.get("MOBILETRACE_DB_PATH"):
        cfg["server"]["database_path"] = os.environ["MOBILETRACE_DB_PATH"]
    if os.environ.get("MOBILETRACE_CASES_DIR"):
        cfg["server"]["cases_dir"] = os.environ["MOBILETRACE_CASES_DIR"]
    # File overrides
    p = Path(config_path)
    if p.exists():
        with open(p) as f:
            file_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, file_cfg)
    return cfg
