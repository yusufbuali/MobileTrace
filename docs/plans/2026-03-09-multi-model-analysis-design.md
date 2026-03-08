# Multi-Model Analysis with Consensus — Design

**Date:** 2026-03-09
**Status:** Implemented

---

## Overview

Multi-Model Analysis lets investigators run 2–5 OpenRouter models in parallel on the same evidence and automatically compute a deterministic consensus. Findings corroborated by ≥ 2 models get `HIGH` confidence; lone-model findings get `MEDIUM`. The existing single-model flow is untouched.

---

## Architecture

### Database

**New table: `analysis_runs`**
```sql
CREATE TABLE analysis_runs (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    models TEXT NOT NULL,        -- JSON array
    status TEXT DEFAULT 'running', -- running|complete|error|cancelled
    artifact_filter TEXT,        -- JSON array or NULL (= all)
    created_at TEXT DEFAULT (datetime('now'))
);
```

**Migration: `analysis_results`**
The existing inline `UNIQUE(case_id, artifact_key)` constraint is dropped (via table recreation) and replaced with an expression index that accommodates multi-model rows:
```sql
CREATE UNIQUE INDEX idx_analysis_results_multi
    ON analysis_results(case_id, artifact_key, COALESCE(run_id,''), COALESCE(provider,''));
```
- Single-model rows (`run_id IS NULL`): unique on `(case_id, artifact_key, '', provider)` — replaces on re-run
- Multi-model rows: unique on `(case_id, artifact_key, run_id, model)` — one per model per artifact per run
- Consensus rows: unique on `(case_id, artifact_key, run_id, 'consensus')` — one per artifact per run

### Backend Engine (`app/analyzer.py`)

**`MobileAnalyzer.analyze_multi(run_id, case_id, models, artifact_filter, cancel_event, progress_callback, db)`**
- Collects artifacts once via `_collect_artifacts()`
- Builds task list: `[(model, artifact_key, data)]` for all model × artifact combinations
- Runs with `ThreadPoolExecutor(max_workers=min(tasks, 6))`
- Each worker calls `_analyze_artifact_for_model()` → instantiates `OpenRouterProvider` with specific model
- Emits SSE events: `model_artifact_started`, `model_artifact_done`
- After all futures resolve → calls `compute_consensus()`
- Emits `consensus_computing`, then route emits `complete`

**`MobileAnalyzer.compute_consensus(run_id, case_id, db)`**
Deterministic, rule-based, no extra API calls.

| Field | Consensus Logic |
|-------|----------------|
| `conversation_risk_assessment` | Group by `thread_id`; `confidence=HIGH` if ≥2 models flag, else `MEDIUM`; `risk_score`=average; `risk_level`=highest across models; `key_indicators`=union |
| `risk_level_summary` | Highest risk level across all model results |
| `key_findings.top_significant_conversations` | Union by `thread_id`; sort by corroboration count desc |
| `crime_indicators` | Group by `category`; `confidence=HIGH` if ≥2 models, `MEDIUM` if 1 |

Results stored as `provider='consensus', run_id=run_id`.

### API Routes (`app/routes/analysis.py`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/cases/<id>/analyze/multi` | Start run, returns `{ run_id }` |
| `GET` | `/api/cases/<id>/analysis/multi` | List all runs for case |
| `GET` | `/api/cases/<id>/analysis/multi/<run_id>` | Get results (consensus + model breakdown) |
| `GET` | `/api/cases/<id>/analysis/multi/<run_id>/stream` | SSE progress for the run |

SSE event types: `connected`, `model_artifact_started`, `model_artifact_done`, `consensus_computing`, `complete`, `error`.

### Frontend (`static/js/chat.js`, `templates/index.html`)

**Modal (`#multi-model-modal`)**
- Fetches model list from `/api/settings/openrouter-models`
- Searchable, checkboxes, selection counter, 2–5 validation
- Past runs dropdown populated from `/api/cases/<id>/analysis/multi`

**Progress Grid**
While running: `model × artifact` table with cell states: `pending` → `running` → `done`/`error`

**Results Display**
- Consensus rendered through existing `_normalizeAnalysis()` + `_renderJsonAnalysis()` pipeline
- "CONSENSUS" badge in insights bar and summary headers
- Per-model breakdown: collapsible `<details>` accordion below each artifact's consensus view

---

## Key Design Decisions

1. **OpenRouter-only** for multi-model: all models accessed via `OpenRouterProvider` with per-worker model override. No changes to other providers.
2. **Deterministic consensus**: rule-based algorithm, fully transparent, zero extra API calls.
3. **Isolated SSE per run**: per-`run_id` queues (not per-`case_id`) to avoid cross-contamination with single-model streams.
4. **Max 6 workers**: 5 models × 6 artifacts = 30 tasks, capped at 6 concurrent to respect rate limits.
5. **Backward compatibility**: existing `UNIQUE` constraint behavior for single-model rows preserved via `COALESCE(run_id,'')` in the composite index.
