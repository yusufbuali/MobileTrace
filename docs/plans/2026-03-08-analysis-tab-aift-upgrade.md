# Analysis Tab — AIFT-Quality Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace MobileTrace's plain analysis progress text and 400px-capped card list with AIFT's animated radar progress header + two-phase UI (live stream cards → exec summary + collapsible per-artifact findings).

**Architecture:** Three files change — `templates/index.html` (HTML structure), `static/style.css` (radar + details CSS), `static/js/chat.js` (SSE handler + results renderer). No backend changes. No new dependencies. The existing `markdownToFragment()` import is reused.

**Tech Stack:** Vanilla JS ES modules, CSS custom properties, native `<details>`/`<summary>`, EventSource SSE.

---

## Task 1 — Replace HTML in `#tab-analysis`

**Files:**
- Modify: `templates/index.html`

### Step 1: Find the current analysis tab HTML

It is at approximately line 196–200:
```html
<!-- Analysis tab -->
<div id="tab-analysis" class="tab-panel">
  <div id="analysis-progress" class="analysis-progress"></div>
  <div id="analysis-results" class="analysis-results"></div>
</div>
```

### Step 2: Replace it with the full two-phase structure

Replace those 4 lines with:

```html
<!-- Analysis tab -->
<div id="tab-analysis" class="tab-panel">

  <!-- ── Radar progress header (shown during + after analysis) ── -->
  <div id="analysis-progress-header" class="aph-hidden">
    <div class="aph-radar-wrap" aria-hidden="true">
      <div class="aph-radar">
        <div class="aph-radar-ring aph-radar-ring--outer"></div>
        <div class="aph-radar-ring aph-radar-ring--inner"></div>
        <div class="aph-radar-sweep"></div>
        <div class="aph-radar-core"></div>
      </div>
    </div>
    <div class="aph-body">
      <div class="aph-top-row">
        <span id="aph-label" class="aph-label">Initializing…</span>
        <span id="aph-count" class="aph-count">0 / 0 artifacts</span>
      </div>
      <div class="aph-bar-track">
        <div id="aph-bar-fill" class="aph-bar-fill"></div>
      </div>
      <div class="aph-bottom-row">
        <span id="aph-current" class="aph-current"></span>
      </div>
    </div>
  </div>

  <!-- ── Phase 1: live stream cards (shown while analysis runs) ── -->
  <div id="analysis-stream">
    <div id="analysis-stream-list" class="analysis-stream-list"></div>
  </div>

  <!-- ── Phase 2: results view (shown after analysis completes) ── -->
  <div id="analysis-results-view" class="aph-hidden">

    <!-- Executive summary -->
    <div class="aift-exec-summary">
      <div class="aift-exec-title">Executive Summary</div>
      <div id="analysis-exec-content" class="markdown-output"></div>
    </div>

    <!-- Per-artifact collapsible findings -->
    <div class="aift-findings-header">Per-Artifact Findings</div>
    <div id="analysis-findings"></div>

    <!-- Action row -->
    <div class="aift-action-row">
      <button id="btn-view-report" class="btn-secondary">&#128196; View Full Report</button>
      <button id="btn-rerun-analysis" class="btn-secondary">&#8635; Re-run Analysis</button>
    </div>
  </div>

</div>
```

### Step 3: Verify the file saves correctly

Open `http://localhost:5001`, switch to the Analysis tab — it should look identical to before (all new divs are either hidden or empty). No JS errors in the browser console.

### Step 4: Commit

```bash
git add templates/index.html
git commit -m "feat(analysis): scaffold two-phase AIFT-style analysis tab HTML"
```

---

## Task 2 — Add CSS: radar, progress header, details, exec summary

**Files:**
- Modify: `static/style.css`

### Step 1: Find the current Analysis CSS block

It starts at approximately line 95:
```css
/* Analysis */
.analysis-progress { margin-bottom: 12px; font-size: 0.85rem; color: var(--text-muted); }
```

### Step 2: Replace the entire Analysis CSS block

Replace from `/* Analysis */` down through line 228 (`.akg-val` rule), keeping all of the JSON sub-element rules that exist below (`.analysis-risk-banner`, `.analysis-thread-card`, etc.) — **only replace lines 95–106**, the original `.analysis-progress` / `.analysis-card` / `.analysis-card-header` / `.analysis-card-body` block. The rules from 203 onward (`.analysis-risk-banner` etc.) stay.

Replace lines 95–106 with:

```css
/* ── Analysis: utility ────────────────────────────────────────── */
.aph-hidden { display: none !important; }

/* ── Analysis: radar progress header ──────────────────────────── */
#analysis-progress-header {
  display: flex;
  align-items: center;
  gap: 1.1rem;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--info);
  border-radius: var(--radius);
  padding: 0.9rem 1.1rem;
  margin-bottom: 16px;
  position: sticky;
  top: 0;
  z-index: 10;
  box-shadow: 0 4px 18px rgba(0,0,0,0.3);
  transition: border-color 0.4s, box-shadow 0.4s;
}
#analysis-progress-header[data-state="complete"] {
  border-left-color: #22c55e;
  box-shadow: 0 4px 18px rgba(34,197,94,0.12);
}
#analysis-progress-header[data-state="failed"] {
  border-left-color: var(--danger);
  box-shadow: 0 4px 18px rgba(248,81,73,0.12);
}

/* radar icon */
.aph-radar-wrap { flex-shrink: 0; }
.aph-radar { position: relative; width: 48px; height: 48px; }
.aph-radar-ring {
  position: absolute; border-radius: 50%;
  border: 1.5px solid var(--info);
}
.aph-radar-ring--outer { inset: 0; opacity: 0.25; }
.aph-radar-ring--inner { inset: 25%; opacity: 0.5; }
.aph-radar-sweep {
  position: absolute; inset: 0; border-radius: 50%;
  background: conic-gradient(from 0deg, transparent 65%, rgba(88,166,255,0.55) 100%);
  animation: aph-radar-spin 2s linear infinite;
}
@keyframes aph-radar-spin { to { transform: rotate(360deg); } }
.aph-radar-core {
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--info);
  box-shadow: 0 0 7px var(--info), 0 0 14px rgba(88,166,255,0.35);
}
/* complete state */
#analysis-progress-header[data-state="complete"] .aph-radar-sweep {
  animation: none; background: none;
}
#analysis-progress-header[data-state="complete"] .aph-radar-core {
  background: #22c55e;
  box-shadow: 0 0 7px #22c55e, 0 0 18px rgba(34,197,94,0.35);
  width: 20px; height: 20px;
}
#analysis-progress-header[data-state="complete"] .aph-radar-core::before {
  content: '\2713';
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%,-50%);
  color: #fff; font-size: 0.72rem; font-weight: 700;
}
/* failed state */
#analysis-progress-header[data-state="failed"] .aph-radar-sweep { animation: none; background: none; }
#analysis-progress-header[data-state="failed"] .aph-radar-core {
  background: var(--danger);
  box-shadow: 0 0 7px var(--danger);
  width: 18px; height: 18px;
}
#analysis-progress-header[data-state="failed"] .aph-radar-core::before {
  content: '\00d7';
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%,-50%);
  color: #fff; font-size: 0.85rem; font-weight: 700;
}

/* body layout */
.aph-body { flex: 1; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.aph-top-row { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; }
.aph-label {
  font-size: 0.95rem; font-weight: 600; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
#analysis-progress-header[data-state="complete"] .aph-label { color: #22c55e; }
#analysis-progress-header[data-state="failed"]   .aph-label { color: var(--danger); }
.aph-count {
  font-size: 0.75rem; color: var(--info);
  background: rgba(88,166,255,0.1);
  padding: 0.1rem 0.5rem; border-radius: 999px; white-space: nowrap; flex-shrink: 0;
}
#analysis-progress-header[data-state="complete"] .aph-count {
  background: rgba(34,197,94,0.1); color: #22c55e;
}
.aph-bar-track {
  width: 100%; height: 4px; background: var(--border);
  border-radius: 999px; overflow: hidden; position: relative;
}
.aph-bar-fill {
  height: 100%; width: 0%; background: var(--info);
  border-radius: 999px;
  transition: width 0.5s cubic-bezier(0.4,0,0.2,1);
  position: relative; overflow: hidden;
}
.aph-bar-fill::after {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.22) 50%, transparent 100%);
  animation: aph-shimmer 1.6s ease-in-out infinite;
}
@keyframes aph-shimmer {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(200%); }
}
#analysis-progress-header[data-state="complete"] .aph-bar-fill { background: #22c55e; }
#analysis-progress-header[data-state="complete"] .aph-bar-fill::after { animation: none; }
#analysis-progress-header[data-state="failed"] .aph-bar-fill { background: var(--danger); }
#analysis-progress-header[data-state="failed"] .aph-bar-fill::after { animation: none; }
.aph-bottom-row { min-height: 1rem; }
.aph-current { font-size: 0.7rem; color: var(--text-muted); }

/* ── Analysis: live stream cards ──────────────────────────────── */
.analysis-stream-list { display: flex; flex-direction: column; gap: 10px; }
.analysis-stream-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-left: 2px solid var(--info);
  border-radius: var(--radius);
  padding: 12px 14px;
}
.asc-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.asc-title { font-size: 0.9rem; font-weight: 600; flex: 1; }
.asc-meta { font-size: 0.72rem; color: var(--text-muted); }

/* ── Analysis: details/summary (results view) ─────────────────── */
.aift-findings-header {
  font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--text-muted);
  margin: 14px 0 8px;
}
#analysis-findings details {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 6px;
}
#analysis-findings details > summary {
  cursor: pointer; list-style: none;
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px;
  font-size: 0.82rem; font-weight: 600;
  color: var(--text-muted);
  user-select: none;
  transition: color 0.15s, background 0.15s;
}
#analysis-findings details > summary::-webkit-details-marker { display: none; }
#analysis-findings details > summary::before {
  content: '▸';
  font-size: 0.62rem;
  color: var(--text-muted);
  transition: transform 0.2s, color 0.15s;
  flex-shrink: 0;
}
#analysis-findings details[open] > summary::before {
  transform: rotate(90deg);
  color: var(--info);
}
#analysis-findings details[open] > summary {
  color: var(--info);
  background: rgba(88,166,255,0.05);
  border-bottom: 1px solid var(--border);
}
#analysis-findings details > div {
  padding: 14px;
  font-size: 0.82rem;
}

/* ── Analysis: executive summary card ────────────────────────── */
.aift-exec-summary {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--info);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 14px;
}
.aift-exec-title {
  font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--info);
  margin-bottom: 10px;
}

/* ── Analysis: action row ─────────────────────────────────────── */
.aift-action-row {
  display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap;
}
```

### Step 3: Check visually

Reload the app. The Analysis tab should still look the same (new elements hidden). No console errors.

### Step 4: Commit

```bash
git add static/style.css
git commit -m "feat(analysis): add AIFT-style radar, details, exec summary CSS"
```

---

## Task 3 — JS: radar progress helper + upgrade `triggerAnalysis()`

**Files:**
- Modify: `static/js/chat.js`

### Step 1: Add `_setRadar()` helper

Insert this function **before** the `triggerAnalysis` export (around line 119):

```javascript
// ── Radar progress header ─────────────────────────────────────────────────────

function _setRadar({ state = "running", label = "", count = 0, total = 0, current = "" } = {}) {
  const header = dom("analysis-progress-header");
  if (!header) return;
  header.classList.remove("aph-hidden");
  header.dataset.state = state;
  const labelEl  = dom("aph-label");
  const countEl  = dom("aph-count");
  const fillEl   = dom("aph-bar-fill");
  const currentEl = dom("aph-current");
  if (labelEl)   labelEl.textContent  = label  || (state === "complete" ? "Analysis complete" : state === "failed" ? "Analysis failed" : "Initializing…");
  if (countEl)   countEl.textContent  = `${count} / ${total} artifacts`;
  if (fillEl)    fillEl.style.width   = total > 0 ? `${Math.round((count / total) * 100)}%` : "0%";
  if (currentEl) currentEl.textContent = current ? `Currently: ${current}` : "";
}
```

### Step 2: Rewrite `triggerAnalysis()`

Replace the entire `triggerAnalysis` export (lines 119–167) with:

```javascript
export async function triggerAnalysis(caseId) {
  // Reset UI: show radar, clear stream list, hide results view
  _setRadar({ state: "running", label: "Starting analysis…", count: 0, total: 0 });
  const streamList = dom("analysis-stream-list");
  const resultsView = dom("analysis-results-view");
  if (streamList) streamList.innerHTML = "";
  if (resultsView) resultsView.classList.add("aph-hidden");
  const streamEl = dom("analysis-stream");
  if (streamEl) streamEl.style.display = "";

  try {
    await apiFetch(`/api/cases/${caseId}/analyze`, { method: "POST" });
  } catch (err) {
    _setRadar({ state: "failed", label: `Failed to start: ${err.message}`, count: 0, total: 0 });
    return;
  }

  const es = new EventSource(`/api/cases/${caseId}/analysis/stream`);
  const done = [];

  es.addEventListener("artifact_done", (e) => {
    const d = JSON.parse(e.data);
    done.push(d.artifact_key);
    _setRadar({
      state: "running",
      label: `Analyzing ${d.artifact_key}…`,
      count: done.length,
      total: done.length,   // total unknown until complete — update on complete
      current: d.artifact_key,
    });
    // Add a live stream card
    if (streamList) {
      const card = document.createElement("div");
      card.className = "analysis-stream-card";
      const conf = _extractConfidence(d.result || "");
      card.innerHTML = `
        <div class="asc-header">
          <span class="asc-title">${d.artifact_key}</span>
          ${conf ? `<span class="confidence-inline ${_confidenceClass(conf)}">${conf}</span>` : ""}
        </div>
        <div class="markdown-output"></div>
      `;
      const mdEl = card.querySelector(".markdown-output");
      if (mdEl) mdEl.appendChild(markdownToFragment(d.result || "(no result)"));
      streamList.appendChild(card);
    }
  });

  es.addEventListener("complete", () => {
    _setRadar({ state: "complete", label: "Analysis complete", count: done.length, total: done.length, current: "" });
    es.close();
    if (streamEl) streamEl.style.display = "none";
    loadAnalysisResults(caseId);
  });

  es.addEventListener("error", (e) => {
    let msg = "Analysis failed.";
    if (e.data) {
      try { msg = JSON.parse(e.data).message || msg; } catch (_) {}
    }
    _setRadar({ state: "failed", label: msg, count: done.length, total: done.length });
    es.close();
  });
}
```

### Step 3: Verify manually

Trigger an analysis in the UI. You should see:
- Radar header appears with spinning sweep animation
- Blue shimmer progress bar
- Each artifact adds a stream card with markdown content
- On completion, radar turns green with ✓, stream cards hide, results view appears

### Step 4: Commit

```bash
git add static/js/chat.js
git commit -m "feat(analysis): AIFT radar progress header + live stream cards in triggerAnalysis"
```

---

## Task 4 — JS: AIFT-style results view in `loadAnalysisResults()`

**Files:**
- Modify: `static/js/chat.js`

### Step 1: Rewrite `loadAnalysisResults()`

Replace the entire existing `loadAnalysisResults` export (lines 169–232) with:

```javascript
export async function loadAnalysisResults(caseId) {
  const resultsView = dom("analysis-results-view");
  const execContent = dom("analysis-exec-content");
  const findingsEl  = dom("analysis-findings");
  if (!resultsView || !execContent || !findingsEl) return;

  let rows;
  try {
    rows = await apiFetch(`/api/cases/${caseId}/analysis`);
  } catch (_) {
    return;
  }
  if (!rows || !rows.length) return;

  // ── Executive Summary ──────────────────────────────────────────
  execContent.innerHTML = "";
  const summaryParts = rows.map(r => {
    const p = r.result_parsed || null;
    const rsum = p && (p.risk_level_summary || p.executive_summary || p.summary);
    if (rsum) return `**${_titleCase(r.artifact_key)}:** ${rsum}`;
    if (!p && r.result) return `**${_titleCase(r.artifact_key)}:** ${String(r.result).slice(0, 200).trim()}`;
    return null;
  }).filter(Boolean);
  execContent.appendChild(
    markdownToFragment(summaryParts.length ? summaryParts.join("\n\n") : "_No summary available._")
  );

  // ── Per-Artifact Details ───────────────────────────────────────
  findingsEl.innerHTML = "";
  rows.forEach((r, i) => {
    const p = r.result_parsed || null;
    const conf = p ? _jsonRiskLevel(p) : _extractConfidence(r.result || "");

    const details = document.createElement("details");
    if (i === 0) details.open = true;

    const summary = document.createElement("summary");
    summary.innerHTML = `
      <span style="flex:1">${_titleCase(r.artifact_key)}</span>
      ${conf ? `<span class="confidence-inline ${_confidenceClass(conf)}">${conf}</span>` : ""}
      <span class="asc-meta" style="margin-left:6px">${r.provider || ""}</span>
    `;
    details.appendChild(summary);

    const body = document.createElement("div");
    if (p) {
      _renderJsonAnalysis(p, body);
    } else {
      body.classList.add("markdown-output");
      body.appendChild(markdownToFragment(r.result || "(no result)"));
    }
    details.appendChild(body);
    findingsEl.appendChild(details);
  });

  // ── Action buttons ─────────────────────────────────────────────
  const reportBtn = dom("btn-view-report");
  if (reportBtn) {
    reportBtn.onclick = () => window.open(`/api/cases/${caseId}/report`, "_blank");
  }
  const rerunBtn = dom("btn-rerun-analysis");
  if (rerunBtn) {
    rerunBtn.onclick = () => {
      resultsView.classList.add("aph-hidden");
      const header = dom("analysis-progress-header");
      if (header) header.classList.add("aph-hidden");
      triggerAnalysis(caseId);
    };
  }

  // Show the results view
  resultsView.classList.remove("aph-hidden");

  // Show radar in complete state if it's currently hidden (page reload case)
  const header = dom("analysis-progress-header");
  if (header && header.classList.contains("aph-hidden")) {
    _setRadar({ state: "complete", label: "Analysis complete", count: rows.length, total: rows.length });
  }
}

function _titleCase(str) {
  return String(str || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}
```

### Step 2: Verify

1. Reload a case that already has analysis results — the Results view should appear immediately with exec summary + collapsible details
2. First details element should be open by default
3. Clicking a closed details element should expand with caret rotation + blue heading
4. "View Full Report" should open the report in a new tab
5. "Re-run Analysis" should reset and start a new analysis

### Step 3: Commit

```bash
git add static/js/chat.js
git commit -m "feat(analysis): AIFT-style results view — exec summary + collapsible per-artifact details"
```

---

## Task 5 — Run tests and verify

### Step 1: Run full test suite

```bash
docker run --rm \
  -v "$(pwd -W):/opt/mobiletrace" \
  -e MOBILETRACE_DB_PATH=/tmp/test.db \
  mobiletrace-mobiletrace:latest \
  python -m pytest tests/ -v
```

Expected: all 144 tests pass (no backend changes were made).

### Step 2: Browser smoke test checklist

- [ ] Analysis tab shows correctly on page load (no JS errors)
- [ ] Radar header hidden until analysis triggered
- [ ] Clicking "Run Analysis" shows radar with spinning sweep
- [ ] Each artifact completion adds a live stream card with markdown
- [ ] On complete: radar turns green ✓, stream cards hidden, results view visible
- [ ] Executive summary renders markdown (bold, bullets)
- [ ] First artifact `<details>` is open; others collapsed
- [ ] Expanding a details shows caret rotate + blue heading
- [ ] Confidence pills (HIGH/CRITICAL/etc.) appear in summaries
- [ ] "View Full Report" opens `/api/cases/{id}/report` in new tab
- [ ] "Re-run Analysis" resets and works again
- [ ] Page reload of a case with existing results shows results view directly

### Step 3: Final commit (if any fixups)

```bash
git add -p
git commit -m "fix(analysis): smoke test fixups"
```

---

## Files Changed Summary

| File | Tasks |
|---|---|
| `templates/index.html` | Task 1 — two-phase HTML structure |
| `static/style.css` | Task 2 — radar, details, exec summary, action row CSS |
| `static/js/chat.js` | Tasks 3 & 4 — `_setRadar()`, `triggerAnalysis()`, `loadAnalysisResults()` |
