# Analysis Preview Panel & Cancel — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a pre-analysis preview panel with artifact selection and a cancel mechanism to the analysis workflow.

**Architecture:** New `/analysis/preview` endpoint returns per-artifact counts. Existing `/analyze` endpoint accepts an `artifacts` filter array. Cancel uses a per-case `threading.Event` checked between artifacts. Frontend renders a preview panel as the default analysis tab state, with checkboxes for artifact selection.

**Tech Stack:** Python/Flask backend, vanilla JS frontend, CSS custom properties.

**Future (Option C):** Multi-step wizard with stepper UI — planned but not in scope here.

---

## Task 1 — Backend: Preview Endpoint

**Files:**
- Modify: `app/routes/analysis.py`

### Step 1: Add the preview endpoint

After the existing `trigger_analysis` function (line 75), add:

```python
@bp_analysis.get("/cases/<case_id>/analysis/preview")
def analysis_preview(case_id: str):
    """Return per-artifact data counts so the UI can show what will be analyzed."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    # Evidence files
    evidence = [
        dict(r) for r in db.execute(
            "SELECT id, format, source_path, parse_status FROM evidence_files WHERE case_id=?",
            (case_id,),
        ).fetchall()
    ]

    # Per-platform message counts
    msg_counts = {}
    for platform in ("sms", "whatsapp", "telegram", "signal"):
        cnt = db.execute(
            "SELECT COUNT(*) as c FROM messages WHERE case_id=? AND platform=?",
            (case_id, platform),
        ).fetchone()["c"]
        msg_counts[platform] = cnt

    # Call log count
    call_count = db.execute(
        "SELECT COUNT(*) as c FROM call_logs WHERE case_id=?", (case_id,)
    ).fetchone()["c"]

    # Contact count
    contact_count = db.execute(
        "SELECT COUNT(*) as c FROM contacts WHERE case_id=?", (case_id,)
    ).fetchone()["c"]

    artifacts = []
    for platform in ("sms", "whatsapp", "telegram", "signal"):
        artifacts.append({
            "key": platform,
            "label": platform.upper() if platform == "sms" else platform.title(),
            "type": "messages",
            "count": msg_counts[platform],
        })
    artifacts.append({"key": "call_logs", "label": "Call Logs", "type": "calls", "count": call_count})
    artifacts.append({"key": "contacts", "label": "Contacts", "type": "contacts", "count": contact_count})

    return jsonify({
        "evidence": evidence,
        "artifacts": artifacts,
        "total_messages": sum(msg_counts.values()),
        "total_calls": call_count,
        "total_contacts": contact_count,
    })
```

### Step 2: Commit

```bash
git add app/routes/analysis.py
git commit -m "feat(api): add /analysis/preview endpoint with per-artifact counts"
```

---

## Task 2 — Backend: Artifact Filter + Cancel Support

**Files:**
- Modify: `app/routes/analysis.py`
- Modify: `app/analyzer.py`

### Step 1: Add cancel registry to analysis.py

At the top of `analysis.py`, after `_queues_lock` (line 18), add:

```python
_cancel_events: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


def _get_cancel_event(case_id: str) -> threading.Event:
    with _cancel_lock:
        if case_id not in _cancel_events:
            _cancel_events[case_id] = threading.Event()
        return _cancel_events[case_id]


def _clear_cancel_event(case_id: str) -> None:
    with _cancel_lock:
        if case_id in _cancel_events:
            _cancel_events[case_id].clear()
```

### Step 2: Add cancel endpoint

After the preview endpoint, add:

```python
@bp_analysis.post("/cases/<case_id>/analysis/cancel")
def cancel_analysis(case_id: str):
    """Signal the running analysis to stop after current artifact."""
    evt = _get_cancel_event(case_id)
    evt.set()
    _push_event(case_id, "cancelled", {"case_id": case_id})
    _close_stream(case_id)
    return jsonify({"status": "cancel_requested"}), 200
```

### Step 3: Modify trigger_analysis to accept artifact filter and pass cancel event

Replace the existing `trigger_analysis` function body with:

```python
@bp_analysis.post("/cases/<case_id>/analyze")
def trigger_analysis(case_id: str):
    """Start background LLM analysis for selected artifacts in a case."""
    db = get_db()
    row = db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return jsonify({"error": "case not found"}), 404

    # Parse optional artifact filter from request body
    from flask import request as flask_request
    body = flask_request.get_json(silent=True) or {}
    artifact_filter = body.get("artifacts")  # list of keys or None (= all)

    config = current_app.config["MT_CONFIG"]
    cancel_evt = _get_cancel_event(case_id)
    cancel_evt.clear()  # reset from any previous cancel

    def _run():
        def _callback(artifact_key: str, result: dict) -> None:
            _push_event(case_id, "artifact_done", {
                "artifact_key": artifact_key,
                "provider": result.get("provider", ""),
                "error": result.get("error"),
            })

        try:
            analyzer = MobileAnalyzer(config)
            analyzer.analyze_case(
                case_id, get_db(),
                callback=_callback,
                artifact_filter=artifact_filter,
                cancel_event=cancel_evt,
            )
            if cancel_evt.is_set():
                _push_event(case_id, "cancelled", {"case_id": case_id})
            else:
                _push_event(case_id, "complete", {"case_id": case_id})
        except Exception as exc:
            _push_event(case_id, "error", {"message": str(exc)})
        finally:
            _close_stream(case_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"case_id": case_id, "status": "started"}), 202
```

### Step 4: Modify analyzer.py to accept filter and cancel event

Replace the `analyze_case` method signature and body in `app/analyzer.py`:

```python
    def analyze_case(
        self,
        case_id: str,
        db,
        callback: Callable[[str, dict], None] | None = None,
        artifact_filter: list[str] | None = None,
        cancel_event: "threading.Event | None" = None,
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

                # Persist to DB (best-effort)
                try:
                    db.execute(
                        "INSERT OR REPLACE INTO analysis_results (case_id, artifact_key, result, provider) VALUES (?,?,?,?)",
                        (case_id, artifact_key,
                         result.get("result", result.get("error", "")),
                         result.get("provider", "")),
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
```

Also add the `threading` import at the top of `analyzer.py` (after `logging`):

```python
import threading
```

### Step 5: Commit

```bash
git add app/routes/analysis.py app/analyzer.py
git commit -m "feat(api): artifact filter + cancel support for analysis"
```

---

## Task 3 — Frontend: Preview Panel HTML + CSS

**Files:**
- Modify: `templates/index.html`
- Modify: `static/style.css`

### Step 1: Add preview panel HTML to the analysis tab

In `templates/index.html`, find the analysis tab panel opening:

```html
        <div id="tab-analysis" class="tab-panel" role="tabpanel">
```

Immediately after that line (before the radar progress header), insert:

```html
          <!-- ── Pre-analysis preview panel ── -->
          <div id="analysis-preview" class="analysis-preview">
            <div class="ap-header">
              <div class="ap-title">Analysis Preparation</div>
            </div>
            <div id="ap-evidence" class="ap-evidence"></div>
            <div class="ap-artifacts-header">
              <span>Select artifacts to analyze</span>
              <button id="ap-toggle-all" class="ap-toggle-btn">Deselect All</button>
            </div>
            <div id="ap-artifact-list" class="ap-artifact-list"></div>
            <div class="ap-footer">
              <button id="ap-start-btn" class="btn-primary" disabled>Start Analysis</button>
              <span id="ap-selection-count" class="ap-selection-count"></span>
            </div>
          </div>
```

### Step 2: Add cancel button inside the radar progress header

In `templates/index.html`, find:

```html
              <div class="aph-bottom-row">
                <span id="aph-current" class="aph-current"></span>
              </div>
```

Replace with:

```html
              <div class="aph-bottom-row">
                <span id="aph-current" class="aph-current"></span>
                <button id="aph-cancel-btn" class="aph-cancel-btn aph-hidden">Cancel</button>
              </div>
```

### Step 3: Add preview panel CSS to style.css

Append before the `/* Responsive */` section (before line 476):

```css
/* Analysis preview panel */
.analysis-preview { max-width: 600px; }
.ap-header { margin-bottom: 14px; }
.ap-title { font-size: 1rem; font-weight: 700; color: var(--text); }
.ap-evidence { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; margin-bottom: 14px; font-size: 0.82rem; }
.ap-ev-row { display: flex; align-items: center; gap: 8px; }
.ap-ev-format { color: var(--info); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; }
.ap-ev-path { color: var(--text-muted); word-break: break-all; }
.ap-ev-status { margin-left: auto; font-size: 0.75rem; font-weight: 600; }
.ap-ev-status.done { color: #3fb950; }
.ap-ev-status.error { color: var(--danger); }
.ap-artifacts-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 0.82rem; font-weight: 600; color: var(--text-muted); }
.ap-toggle-btn { background: none; border: none; color: var(--info); font-size: 0.78rem; cursor: pointer; padding: 0; }
.ap-toggle-btn:hover { text-decoration: underline; }
.ap-artifact-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.ap-artifact { display: flex; align-items: center; gap: 10px; background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; cursor: pointer; transition: border-color 0.15s; }
.ap-artifact:hover { border-color: var(--text-muted); }
.ap-artifact.selected { border-color: var(--info); }
.ap-artifact.empty { opacity: 0.5; }
.ap-artifact input[type="checkbox"] { accent-color: var(--info); width: 16px; height: 16px; flex-shrink: 0; }
.ap-artifact-info { flex: 1; display: flex; justify-content: space-between; align-items: center; }
.ap-artifact-label { font-size: 0.85rem; font-weight: 600; }
.ap-artifact-count { font-size: 0.78rem; color: var(--text-muted); }
.ap-artifact-warn { font-size: 0.72rem; color: var(--warning); margin-left: 6px; }
.ap-footer { display: flex; align-items: center; gap: 12px; }
.ap-selection-count { font-size: 0.78rem; color: var(--text-muted); }
.ap-empty-state { text-align: center; padding: 40px 20px; color: var(--text-muted); }
.ap-empty-state-icon { font-size: 2rem; opacity: 0.3; margin-bottom: 8px; }
.ap-empty-state-text { font-size: 0.85rem; }
.aph-cancel-btn { background: none; border: 1px solid var(--danger); color: var(--danger); padding: 3px 10px; border-radius: var(--radius); font-size: 0.72rem; cursor: pointer; margin-left: auto; transition: background 0.15s; }
.aph-cancel-btn:hover { background: rgba(248,81,73,0.1); }
```

### Step 4: Commit

```bash
git add templates/index.html static/style.css
git commit -m "feat(ui): analysis preview panel HTML and CSS"
```

---

## Task 4 — Frontend: Preview Panel Logic

**Files:**
- Modify: `static/js/chat.js`

### Step 1: Add preview loading function

After the existing `dom()` helper (line 12), add a module-level variable:

```javascript
let _currentEs = null; // active EventSource for cancel
```

Add a new exported function after `initChat` (after line 18):

```javascript
export async function loadAnalysisPreview(caseId) {
  const previewEl = dom("analysis-preview");
  if (!previewEl) return;

  // Hide results and stream, show preview
  const resultsView = dom("analysis-results-view");
  const streamEl = dom("analysis-stream");
  const header = dom("analysis-progress-header");
  if (resultsView) resultsView.classList.add("aph-hidden");
  if (streamEl) streamEl.style.display = "none";
  if (header) header.classList.add("aph-hidden");

  let data;
  try {
    data = await apiFetch(`/api/cases/${caseId}/analysis/preview`);
  } catch (err) {
    previewEl.innerHTML = '<div class="ap-empty-state"><div class="ap-empty-state-icon">&#128269;</div><div class="ap-empty-state-text">Could not load analysis preview.</div></div>';
    previewEl.style.display = "";
    return;
  }

  // Evidence section
  const evEl = dom("ap-evidence");
  if (evEl) {
    if (data.evidence && data.evidence.length) {
      evEl.innerHTML = data.evidence.map(e =>
        `<div class="ap-ev-row">
          <span class="ap-ev-format">${e.format || "unknown"}</span>
          <span class="ap-ev-path">${e.source_path || "uploaded file"}</span>
          <span class="ap-ev-status ${e.parse_status === "done" ? "done" : "error"}">${e.parse_status}</span>
        </div>`
      ).join("");
    } else {
      evEl.innerHTML = '<div class="ap-empty-state"><div class="ap-empty-state-icon">&#128193;</div><div class="ap-empty-state-text">No evidence uploaded. Upload evidence first to run analysis.</div></div>';
      const footer = previewEl.querySelector(".ap-footer");
      const artHeader = previewEl.querySelector(".ap-artifacts-header");
      const artList = dom("ap-artifact-list");
      if (footer) footer.style.display = "none";
      if (artHeader) artHeader.style.display = "none";
      if (artList) artList.style.display = "none";
      previewEl.style.display = "";
      return;
    }
  }

  // Artifact checkboxes
  const listEl = dom("ap-artifact-list");
  if (listEl) {
    listEl.innerHTML = data.artifacts.map(a => {
      const empty = a.count === 0;
      const unit = a.type === "messages" ? "messages" : a.type === "calls" ? "records" : "records";
      return `<label class="ap-artifact ${empty ? "empty" : "selected"}" data-key="${a.key}">
        <input type="checkbox" value="${a.key}" ${empty ? "" : "checked"} />
        <div class="ap-artifact-info">
          <span class="ap-artifact-label">${a.label}</span>
          <span>
            <span class="ap-artifact-count">${a.count.toLocaleString()} ${unit}</span>
            ${empty ? '<span class="ap-artifact-warn">&#9888; empty</span>' : ""}
          </span>
        </div>
      </label>`;
    }).join("");

    // Wire checkbox changes
    listEl.querySelectorAll("input[type=checkbox]").forEach(cb => {
      cb.addEventListener("change", () => {
        const label = cb.closest(".ap-artifact");
        if (cb.checked) label.classList.add("selected");
        else label.classList.remove("selected");
        _updateSelectionCount(data.artifacts.length);
      });
    });
  }

  // Toggle all button
  const toggleBtn = dom("ap-toggle-all");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const cbs = listEl.querySelectorAll("input[type=checkbox]");
      const allChecked = [...cbs].filter(c => c.checked).length === cbs.length;
      cbs.forEach(cb => {
        cb.checked = !allChecked;
        const label = cb.closest(".ap-artifact");
        if (cb.checked) label.classList.add("selected");
        else label.classList.remove("selected");
      });
      toggleBtn.textContent = allChecked ? "Select All" : "Deselect All";
      _updateSelectionCount(data.artifacts.length);
    });
  }

  // Start button
  const startBtn = dom("ap-start-btn");
  if (startBtn) {
    startBtn.disabled = false;
    startBtn.onclick = () => {
      const selected = [...listEl.querySelectorAll("input[type=checkbox]:checked")].map(c => c.value);
      if (!selected.length) return;
      previewEl.style.display = "none";
      _triggerWithArtifacts(caseId, selected);
    };
  }

  _updateSelectionCount(data.artifacts.length);

  // Show footer/header in case they were hidden
  const footer = previewEl.querySelector(".ap-footer");
  const artHeader = previewEl.querySelector(".ap-artifacts-header");
  if (footer) footer.style.display = "";
  if (artHeader) artHeader.style.display = "";
  if (listEl) listEl.style.display = "";

  previewEl.style.display = "";
}

function _updateSelectionCount(total) {
  const listEl = dom("ap-artifact-list");
  const countEl = dom("ap-selection-count");
  const startBtn = dom("ap-start-btn");
  const toggleBtn = dom("ap-toggle-all");
  if (!listEl) return;
  const checked = listEl.querySelectorAll("input[type=checkbox]:checked").length;
  if (countEl) countEl.textContent = `${checked} of ${total} artifacts selected`;
  if (startBtn) startBtn.disabled = checked === 0;
  if (toggleBtn) toggleBtn.textContent = checked === total ? "Deselect All" : "Select All";
}
```

### Step 2: Replace triggerAnalysis to support artifact filter and cancel

Replace the existing `triggerAnalysis` function with:

```javascript
async function _triggerWithArtifacts(caseId, artifacts) {
  // Reset UI: show radar, clear stream list, hide results view + preview
  _setRadar({ state: "running", label: "Starting analysis…", count: 0, total: artifacts.length });
  const streamList = dom("analysis-stream-list");
  const resultsView = dom("analysis-results-view");
  const previewEl = dom("analysis-preview");
  if (streamList) streamList.innerHTML = "";
  if (resultsView) resultsView.classList.add("aph-hidden");
  if (previewEl) previewEl.style.display = "none";
  const streamEl = dom("analysis-stream");
  if (streamEl) streamEl.style.display = "";

  // Show cancel button
  const cancelBtn = dom("aph-cancel-btn");
  if (cancelBtn) {
    cancelBtn.classList.remove("aph-hidden");
    cancelBtn.onclick = () => _cancelAnalysis(caseId);
  }

  try {
    await apiFetch(`/api/cases/${caseId}/analyze`, {
      method: "POST",
      body: JSON.stringify({ artifacts }),
    });
  } catch (err) {
    _setRadar({ state: "failed", label: `Failed to start: ${err.message}`, count: 0, total: 0 });
    if (cancelBtn) cancelBtn.classList.add("aph-hidden");
    return;
  }

  const es = new EventSource(`/api/cases/${caseId}/analysis/stream`);
  _currentEs = es;
  const done = [];

  es.addEventListener("artifact_done", (e) => {
    const d = JSON.parse(e.data);
    done.push(d.artifact_key);
    _setRadar({
      state: "running",
      label: `Analyzing ${d.artifact_key}…`,
      count: done.length,
      total: artifacts.length,
      current: d.artifact_key,
    });
    if (streamList) {
      const card = document.createElement("div");
      card.className = "analysis-stream-card";
      card.innerHTML = `
        <div class="asc-header">
          <span class="asc-title">${d.artifact_key}</span>
          <span class="asc-meta">${d.provider || ""}</span>
        </div>
        <div class="asc-meta">${d.error ? "Error: " + d.error : "Done"}</div>
      `;
      streamList.appendChild(card);
    }
  });

  es.addEventListener("complete", () => {
    _setRadar({ state: "complete", label: "Analysis complete", count: done.length, total: artifacts.length, current: "" });
    es.close();
    _currentEs = null;
    if (cancelBtn) cancelBtn.classList.add("aph-hidden");
    if (streamEl) streamEl.style.display = "none";
    loadAnalysisResults(caseId);
  });

  es.addEventListener("cancelled", () => {
    _setRadar({ state: "failed", label: "Analysis cancelled", count: done.length, total: artifacts.length, current: "" });
    es.close();
    _currentEs = null;
    if (cancelBtn) cancelBtn.classList.add("aph-hidden");
    // Show preview again so user can re-run
    if (previewEl) previewEl.style.display = "";
    // Still load any partial results
    if (done.length > 0) loadAnalysisResults(caseId);
  });

  es.addEventListener("error", (e) => {
    let msg = "Analysis failed.";
    if (e.data) {
      try { msg = JSON.parse(e.data).message || msg; } catch (_) {}
    }
    _setRadar({ state: "failed", label: msg, count: done.length, total: artifacts.length });
    es.close();
    _currentEs = null;
    if (cancelBtn) cancelBtn.classList.add("aph-hidden");
  });
}

async function _cancelAnalysis(caseId) {
  try {
    await apiFetch(`/api/cases/${caseId}/analysis/cancel`, { method: "POST" });
  } catch (_) {}
  if (_currentEs) {
    _currentEs.close();
    _currentEs = null;
  }
}

export async function triggerAnalysis(caseId) {
  // Called from the "Run Analysis" button in dashboard header — loads preview first
  await loadAnalysisPreview(caseId);
}
```

### Step 3: Update loadAnalysisResults to handle the "Re-run" button

In the existing `loadAnalysisResults` function, find the rerun button handler (around line 266-272):

```javascript
  const rerunBtn = dom("btn-rerun-analysis");
  if (rerunBtn) {
    rerunBtn.onclick = () => {
      resultsView.classList.add("aph-hidden");
      const header = dom("analysis-progress-header");
      if (header) header.classList.add("aph-hidden");
      triggerAnalysis(caseId);
    };
  }
```

This already calls `triggerAnalysis(caseId)` which now loads the preview — no change needed.

### Step 4: Also hide the preview when results load

In `loadAnalysisResults`, after `resultsView.classList.remove("aph-hidden");` (around line 276), add:

```javascript
  const previewEl = dom("analysis-preview");
  if (previewEl) previewEl.style.display = "none";
```

### Step 5: Commit

```bash
git add static/js/chat.js
git commit -m "feat(ui): analysis preview panel logic with artifact selection and cancel"
```

---

## Task 5 — Wire Up: Cases.js Integration

**Files:**
- Modify: `static/js/cases.js`

### Step 1: Import loadAnalysisPreview

Find the existing import from chat.js:

```javascript
import { initChat, triggerAnalysis, loadAnalysisResults } from "./chat.js";
```

Replace with:

```javascript
import { initChat, triggerAnalysis, loadAnalysisResults, loadAnalysisPreview } from "./chat.js";
```

### Step 2: Load preview when switching to analysis tab

In the tab switching handler, find:

```javascript
    // Lazy-load analysis results when switching to analysis tab
    if (btn.dataset.tab === "tab-analysis" && activeCaseId) {
      loadAnalysisResults(activeCaseId);
    }
```

Replace with:

```javascript
    // Load analysis preview when switching to analysis tab
    if (btn.dataset.tab === "tab-analysis" && activeCaseId) {
      loadAnalysisPreview(activeCaseId);
    }
```

### Step 3: Update the btnAnalyze handler to show preview

Find the `btnAnalyze` click handler:

```javascript
if (btnAnalyze) {
  btnAnalyze.addEventListener("click", async () => {
    if (!activeCaseId) return;
    // Switch to analysis tab
    document.querySelectorAll(".tab-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    document.querySelector('[data-tab="tab-analysis"]')?.classList.add("active");
    document.getElementById("tab-analysis")?.classList.add("active");
    await triggerAnalysis(activeCaseId);
  });
}
```

The `triggerAnalysis` function now shows the preview instead of immediately starting analysis, so this handler already works correctly. But we need to set the aria-selected attribute on the analysis tab button:

Replace with:

```javascript
if (btnAnalyze) {
  btnAnalyze.addEventListener("click", async () => {
    if (!activeCaseId) return;
    // Switch to analysis tab
    document.querySelectorAll(".tab-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    const analysisTabBtn = document.querySelector('[data-tab="tab-analysis"]');
    if (analysisTabBtn) { analysisTabBtn.classList.add("active"); analysisTabBtn.setAttribute("aria-selected", "true"); }
    document.getElementById("tab-analysis")?.classList.add("active");
    await loadAnalysisPreview(activeCaseId);
  });
}
```

### Step 4: Commit

```bash
git add static/js/cases.js
git commit -m "feat(ui): wire analysis preview into tab switching and Run Analysis button"
```

---

## Task 6 — Verify & Polish

**Files:**
- All modified files

### Step 1: Run tests

```bash
python -m pytest tests/ -q
```

Expected: All existing tests pass (the new endpoint has no test yet, but existing behavior should be unchanged).

### Step 2: Manual verification checklist

1. Open app in browser
2. Create a case, upload evidence
3. Click "Analysis" tab → should see preview panel with artifact counts
4. Verify empty artifacts show warning badge and are unchecked
5. Click "Deselect All" → all unchecked, button says "Select All", Start disabled
6. Select a few artifacts → count updates, Start enabled
7. Click "Start Analysis" → preview hides, radar shows with cancel button
8. Click "Cancel" → analysis stops, preview reappears, partial results load
9. Click "Run Analysis" (header button) → switches to analysis tab, shows preview
10. Complete a full analysis → results view shows, "Re-run" returns to preview

### Step 3: Final commit if any polish needed

```bash
git add -A
git commit -m "fix(ui): analysis preview panel polish"
```
