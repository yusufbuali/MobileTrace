# Design: Analysis Tab — AIFT-Quality Upgrade (Option B)

**Date:** 2026-03-08
**Goal:** Bring MobileTrace's Analysis tab up to AIFT's Results tab quality, using a two-phase approach within the single tab (streaming cards → results view after completion).

---

## Current State

```html
<!-- Analysis tab — entire current HTML -->
<div id="tab-analysis" class="tab-panel">
  <div id="analysis-progress" class="analysis-progress"></div>
  <div id="analysis-results" class="analysis-results"></div>
</div>
```

JS (`chat.js`): plain text progress, JS-rendered cards with 400px max-height scroll, custom `.collapsed` toggle.

---

## Target State (AIFT-parity)

### Phase 1 — Streaming (during analysis)
- **Animated radar progress header** (sticky, 52px radar icon with spinning conic sweep, rings, glowing core)
  - State: `running` (blue) → `complete` (green ✓) → `failed` (red ✗)
  - Shows: "Analyzing {artifact}…" label, "N / M artifacts" badge, progress bar with shimmer
- **Live cards** rendered into `#analysis-stream-list` as artifacts complete
  - `<article class="analysis-card">` — better border-left accent, no max-height limit
  - Artifact name as `<h4>`, provider + timestamp as `.analysis-card-meta`
  - Markdown content via existing `markdownToFragment()`

### Phase 2 — Results view (after completion)
When analysis completes, swap the streaming view for a polished results layout (within the same tab):
- **Executive Summary card** — derived from `risk_level_summary` fields across all artifacts
- **Per-Artifact Findings** — collapsible `<details>` elements, one per artifact
  - AIFT-style: caret rotates 90° on open, header turns accent-blue, accent glow background
  - Full-height content with `.markdown-output` rendering
- **Action buttons row**: "View Full Report" (→ `/api/cases/{id}/report`) + "Re-run Analysis"

---

## Architecture

### HTML changes (`templates/index.html`)
Replace the two plain divs with:
```
#tab-analysis
  #analysis-progress-header (hidden initially — radar + bar)
  #analysis-stream (shown during streaming)
    #analysis-stream-list (live cards appear here)
  #analysis-results-view (hidden during streaming, shown on complete)
    #analysis-exec-summary (executive summary card)
    #analysis-findings (details elements)
    .analysis-action-row (buttons)
```

### CSS changes (`static/style.css`)
Add:
- Radar icon CSS (`.aph-radar`, `.aph-radar-ring`, `.aph-radar-sweep`, `.aph-radar-core`)
- Progress header CSS (`#analysis-progress-header`, states, shimmer bar)
- Upgraded `.analysis-card` (no max-height, border-left accent)
- `<details>` summary styles (caret, open state accent glow)
- `#analysis-exec-summary`, `#analysis-findings`, `.analysis-action-row`

### JS changes (`static/js/chat.js`)
1. `runAnalysis()` / SSE handler — update radar header instead of plain text div
2. `loadAnalysisResults()` — after fetching, render results view (exec summary + details)
3. New `_buildResultsView(rows)` — builds exec summary + collapsible details
4. New `_updateRadarProgress(state, label, count, total, current)` — controls radar UI
5. On analysis complete: hide `#analysis-stream`, show `#analysis-results-view`

---

## Key Design Decisions

- **No new tab/route** — everything within `#tab-analysis`
- **Reuse `markdownToFragment()`** — already exists in `static/js/markdown.js`
- **Exec summary** — client-side: scan all `result_parsed.risk_level_summary` fields and join; fallback to first 200 chars of raw text
- **Details elements** — native `<details>/<summary>` with CSS, no JS toggle needed
- **Backward compat** — `loadAnalysisResults()` still works for pre-existing results (shows results view directly, skips streaming phase)

---

## Files Changed

| File | Change |
|---|---|
| `templates/index.html` | Replace analysis tab innards with new HTML structure |
| `static/style.css` | Add radar CSS, progress header, upgraded cards, details styles |
| `static/js/chat.js` | Upgrade SSE handler + loadAnalysisResults + new helpers |
