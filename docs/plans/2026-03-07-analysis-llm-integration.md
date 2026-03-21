# Plan: MobileTrace AI Analysis Integration

**Date:** 2026-03-07
**Status:** Ready to implement
**Scope:** Wire the existing `MobileAnalyzer` to work end-to-end with real LLM providers, add a settings UI, and make the Analysis tab functional.

---

## Background

The analysis infrastructure is already built (Phases 4–5):
- `app/analyzer.py` — `MobileAnalyzer` with parallel artifact analysis
- `app/ai_providers.py` — `ClaudeProvider`, `OpenAIProvider`, `LocalProvider`, `KimiProvider`, `OpenRouterProvider`
- `app/routes/analysis.py` — `POST /analyze`, `GET /analysis`, `GET /analysis/stream` (SSE)
- `app/config.py` — `DEFAULT_CONFIG` with all provider fields
- `static/js/chat.js` — `triggerAnalysis()` and `loadAnalysisResults()` already implemented

**What's missing:** No `config.yaml` exists, so `MT_CONFIG["ai"]["claude"]["api_key"]` is empty. The "Run Analysis" button triggers the route but `create_provider()` fails silently or returns empty results because no API key is set.

---

## Phase 1 — Settings API + config.yaml persistence (1 task)

### Task 1: Settings route + config file

Add `GET/POST /api/settings` to MobileTrace (similar to AIFT).

**File:** `app/routes/settings.py` (new)

```python
@bp_settings.get("/settings")
def get_settings():
    # Return current config, masking api_key values
    cfg = deepcopy(current_app.config["MT_CONFIG"])
    for provider in cfg["ai"]:
        if isinstance(cfg["ai"][provider], dict) and "api_key" in cfg["ai"][provider]:
            key = cfg["ai"][provider]["api_key"]
            cfg["ai"][provider]["api_key"] = ("●" * 8 + key[-4:]) if len(key) > 4 else ("●" * len(key))
    return jsonify(cfg)

@bp_settings.post("/settings")
def update_settings():
    # Deep-merge body into config, write config.yaml, reload
    ...
```

**File:** `app/__init__.py` — register `bp_settings`

**Verification:** `GET /api/settings` returns masked config; `POST /api/settings` writes `config.yaml` and reloads.

---

## Phase 2 — Settings UI tab (1 task)

### Task 2: Settings panel in the sidebar or as a separate page

**Option A (simpler):** Add a gear icon in the sidebar that opens a modal with a simple form:
- Provider selector (dropdown: claude / openai / openrouter / local)
- API key input (password field)
- Model input
- Save button → `POST /api/settings`

**File:** `templates/index.html` — add settings modal
**File:** `static/js/settings.js` (new) — fetch/save settings
**File:** `static/style.css` — modal styles

**Verification:** Can type API key, click Save, and GET /api/settings shows it masked.

---

## Phase 3 — Fix Analysis tab flow (1 task)

### Task 3: Analysis tab shows real results + "Run Analysis" works end-to-end

**Current behaviour:** Clicking "Run Analysis" calls `POST /api/cases/<id>/analyze` which starts a background thread. The SSE stream receives `artifact_done` events. `loadAnalysisResults()` fetches `GET /api/cases/<id>/analysis` and renders cards.

**Problem:** The analysis tab doesn't auto-load existing results when opening a case. The JS `loadAnalysisResults()` is only called when switching to the analysis tab, which is correct, but if analysis hasn't run yet, the tab shows nothing and there's no status message.

**Fix in `static/js/chat.js`:**
- `loadAnalysisResults()`: if results array is empty, show "No analysis yet — click Run Analysis above"
- After `triggerAnalysis()` completes the SSE stream, auto-call `loadAnalysisResults()`

**Fix in `static/js/cases.js`:**
- When opening a case that already has analysis results (count > 0), show a badge on the Analysis tab

**Verification:** Open case with existing results → Analysis tab shows cards. Run Analysis with no API key → shows helpful error. Run with valid key → cards appear progressively via SSE.

---

## Phase 4 — Provider health check endpoint (1 task)

### Task 4: `GET /api/settings/test` — validate the current AI provider

```
GET /api/settings/test
→ {"status": "ok", "provider": "claude", "model": "claude-sonnet-4-6", "latency_ms": 342}
→ {"status": "error", "provider": "claude", "error": "Invalid API key"}
```

Sends a minimal test prompt ("Reply with: ok") to confirm the provider responds.

**Verification:** Call with valid/invalid key and confirm correct response.

---

## Implementation order

1. Task 1 (settings route) — backend only, no UI
2. Task 3 (analysis tab fix) — frontend only, no backend
3. Task 2 (settings UI) — small modal
4. Task 4 (health check) — small endpoint

Tasks 1 and 3 can be done in parallel.

---

## API keys — where to get them

| Provider | How to configure |
|---|---|
| **Claude (Anthropic)** | `POST /api/settings` with `{"ai": {"provider": "claude", "claude": {"api_key": "sk-ant-..."}}}` |
| **OpenAI** | Same pattern with `openai.api_key` |
| **OpenRouter** | Same with `openrouter.api_key` — supports many models |
| **Local (Ollama)** | Set `local.base_url` to your Ollama URL, no key needed |

---

## What the Analysis tab will show (after implementation)

For the Android 12 Pixel 3 case (86 messages, 8 contacts, 30 calls), the analyzer will run these artifacts:

| Artifact key | Data source | Prompt |
|---|---|---|
| `sms` | 32 SMS messages | `sms_analysis.md` |
| `whatsapp` | 24 WhatsApp messages | `whatsapp_analysis.md` |
| `telegram` | 30 Telegram messages | `telegram_analysis.md` |
| `call_logs` | 30 calls | `call_log_analysis.md` |
| `contacts` | 8 contacts | `contacts_analysis.md` |

Each runs in parallel (max 3 concurrent). Results appear as collapsible cards in the Analysis tab with risk assessment tables.

---

## Disk space note

MobileTrace's extracted DB files are tiny (< 5 MB total for all cases). The large files on disk are the original forensic images you placed in the evidence folder — those are not touched by the app:
- `AIFT-DEPLOYMENT-2/evidence/` = **70 GB** (your forensic images)
- `MobileTrace/data/` = **5.2 MB** (extracted DBs + SQLite database)

The parser streams directly from the original file and only copies the 3–7 specific DB files (< 2 MB each) to the case's `extracted/` folder.
