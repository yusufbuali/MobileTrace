# Phase 4: Advanced Features — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add interactive analysis-to-conversation navigation, media gallery, date jump, timeline sparkline, case grouping, and analysis export.

**Architecture:** Cross-tab navigation via a global event bus pattern (`window.dispatchEvent`). Media gallery uses CSS Grid with a lightbox overlay. Sparkline is a pure SVG polyline generated client-side. Export generates a Markdown blob and triggers browser download. No new dependencies.

**Tech Stack:** Vanilla JS (ES6 modules), CSS Grid, SVG for sparklines, native HTML5 date input, Blob API for export.

---

## Task 1 — Interactive Citations (Analysis → Conversations Jump)

**Files:**
- Modify: `static/js/chat.js`
- Modify: `static/js/conversations.js`
- Modify: `static/js/cases.js`

### Step 1: Expose a selectThread function from conversations.js

Find:
```javascript
export function initConversations(caseId) {
```

Replace with:
```javascript
export function selectThread(platform, threadId) {
  if (!_caseId) return;
  _activePlatform = platform || null;
  const thread = _threads.find(t =>
    (t.thread === threadId || t.thread_id === threadId) &&
    (!platform || t.platform === platform)
  );
  if (thread) {
    _renderPlatformPills();
    _renderThreadList(_activePlatform ? _threads.filter(t => t.platform === _activePlatform) : _threads);
    _openThread(thread.platform, thread.thread, thread.message_count);
    // Highlight the thread in the list
    setTimeout(() => {
      const items = document.querySelectorAll(".conv-thread-item");
      items.forEach(el => {
        el.classList.remove("active");
        const nameEl = el.querySelector(".conv-thread-name");
        if (nameEl && nameEl.textContent === (thread.thread || "(unknown)")) el.classList.add("active");
      });
    }, 50);
  }
}

export function initConversations(caseId) {
```

### Step 2: Import selectThread in cases.js and wire cross-tab navigation

Find:
```javascript
import { initConversations } from "./conversations.js";
```

Replace with:
```javascript
import { initConversations, selectThread } from "./conversations.js";
```

### Step 3: Add global event listener for cross-tab navigation in cases.js

Find:
```javascript
// ── Sidebar toggle (mobile) ──────────────────────────────────────────────────
```

Replace with:
```javascript
// ── Cross-tab navigation (Analysis → Conversations) ─────────────────────────
window.addEventListener("mt:navigate-thread", (e) => {
  const { threadId, platform } = e.detail || {};
  if (!threadId || !activeCaseId) return;
  // Switch to conversations tab
  document.querySelectorAll(".tab-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  const convBtn = document.querySelector('[data-tab="tab-conversations"]');
  if (convBtn) { convBtn.classList.add("active"); convBtn.setAttribute("aria-selected", "true"); }
  document.getElementById("tab-conversations")?.classList.add("active");
  initConversations(activeCaseId);
  // Small delay to let threads load
  setTimeout(() => selectThread(platform, threadId), 300);
});

// ── Sidebar toggle (mobile) ──────────────────────────────────────────────────
```

### Step 4: Make thread_id clickable in analysis results

In `static/js/chat.js`, find:
```javascript
        <div class="atc-header">
          <span class="atc-thread-id">${esc(t.thread_id || "—")}</span>
```

Replace with:
```javascript
        <div class="atc-header">
          <span class="atc-thread-id atc-thread-link" data-thread="${esc(t.thread_id || "")}" style="cursor:pointer;text-decoration:underline">${esc(t.thread_id || "—")}</span>
```

### Step 5: Make finding thread_id clickable

Find:
```javascript
      let inner = `<div class="afb-thread">${esc(tc.thread_id||"")}</div>
```

Replace with:
```javascript
      let inner = `<div class="afb-thread atc-thread-link" data-thread="${esc(tc.thread_id||"")}" style="cursor:pointer;text-decoration:underline">${esc(tc.thread_id||"")}</div>
```

### Step 6: Add click delegation for thread links in _renderJsonAnalysis

Find:
```javascript
  if (extra.length) {
```

Insert before that line:

```javascript
  // Wire thread-id click navigation
  container.addEventListener("click", (e) => {
    const link = e.target.closest(".atc-thread-link");
    if (link && link.dataset.thread) {
      window.dispatchEvent(new CustomEvent("mt:navigate-thread", { detail: { threadId: link.dataset.thread } }));
    }
  });

```

### Step 7: Commit

```bash
git add static/js/chat.js static/js/conversations.js static/js/cases.js
git commit -m "feat(ui): clickable thread IDs jump from analysis to conversations"
```

---

## Task 2 — Date Jump in Conversations

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/conversations.js`
- Modify: `static/style.css`

### Step 1: Add date input in conversations sidebar

Find:
```html
              <input id="conv-search" type="text" placeholder="Search messages&hellip;" aria-label="Search messages" />
```

Replace with:
```html
              <input id="conv-search" type="text" placeholder="Search messages&hellip;" aria-label="Search messages" />
              <input id="conv-date-jump" type="date" class="conv-date-jump" aria-label="Jump to date" title="Jump to date" />
```

### Step 2: Add date jump CSS

Append to `static/style.css`:

```css

/* Date jump */
.conv-date-jump { margin: 0 10px 6px; width: calc(100% - 20px); font-size: 0.78rem; padding: 5px 8px; }
```

### Step 3: Wire date jump in conversations.js

Find:
```javascript
function _wireSearch() {
  const input = dom("conv-search");
  if (!input) return;
  input.value = "";
```

Replace with:
```javascript
function _wireDateJump() {
  const dateInput = dom("conv-date-jump");
  if (!dateInput) return;
  dateInput.value = "";
  const fresh = dateInput.cloneNode(true);
  dateInput.parentNode.replaceChild(fresh, dateInput);
  fresh.addEventListener("change", () => {
    const dateStr = fresh.value;
    if (!dateStr) return;
    const target = new Date(dateStr);
    const msgs = dom("conv-messages");
    if (!msgs) return;
    const bubbles = msgs.querySelectorAll(".msg-wrap");
    for (const b of bubbles) {
      const tsEl = b.querySelector(".msg-ts");
      if (!tsEl) continue;
      const ts = tsEl.textContent;
      try {
        const d = new Date(ts);
        if (d >= target) {
          b.scrollIntoView({ behavior: "smooth", block: "start" });
          b.style.outline = "2px solid var(--info)";
          setTimeout(() => b.style.outline = "", 2000);
          return;
        }
      } catch (_) {}
    }
  });
}

function _wireSearch() {
  const input = dom("conv-search");
  if (!input) return;
  input.value = "";
```

### Step 4: Call _wireDateJump from initConversations

Find:
```javascript
  _loadThreads();
  _wireSearch();
}
```

Replace with:
```javascript
  _loadThreads();
  _wireSearch();
  _wireDateJump();
}
```

### Step 5: Commit

```bash
git add templates/index.html static/js/conversations.js static/style.css
git commit -m "feat(ui): date jump input in conversations sidebar"
```

---

## Task 3 — Timeline Sparkline on Overview

**Files:**
- Modify: `static/js/cases.js`
- Modify: `static/style.css`

### Step 1: Add sparkline container in stats loading

Find:
```javascript
  } catch (_) { /* stats not critical */ }
}
```

Replace with:
```javascript
    // Sparkline — message volume by day
    _loadSparkline(caseId);
  } catch (_) { /* stats not critical */ }
}

async function _loadSparkline(caseId) {
  const el = document.getElementById("dash-stats");
  if (!el) return;
  try {
    const rows = await apiFetch(`/api/cases/${caseId}/messages?limit=500`);
    if (!rows.length) return;
    // Group by date
    const counts = {};
    rows.forEach(m => {
      if (!m.timestamp) return;
      const day = m.timestamp.slice(0, 10);
      counts[day] = (counts[day] || 0) + 1;
    });
    const days = Object.keys(counts).sort();
    if (days.length < 2) return;
    const values = days.map(d => counts[d]);
    const max = Math.max(...values);

    // Generate SVG polyline
    const w = 200, h = 40, pad = 2;
    const points = values.map((v, i) => {
      const x = pad + (i / (values.length - 1)) * (w - 2 * pad);
      const y = pad + (1 - v / max) * (h - 2 * pad);
      return `${x},${y}`;
    }).join(" ");

    const sparkCard = document.createElement("div");
    sparkCard.className = "stat-card stat-card-spark";
    sparkCard.innerHTML = `
      <div class="stat-label" style="margin-bottom:6px">Activity (${days[0]} — ${days[days.length - 1]})</div>
      <svg class="sparkline-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        <polyline points="${points}" fill="none" stroke="var(--info)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
    el.appendChild(sparkCard);
  } catch (_) { /* sparkline not critical */ }
}
```

### Step 2: Add sparkline CSS

Append to `static/style.css`:

```css

/* Sparkline */
.stat-card-spark { grid-column: span 2; }
.sparkline-svg { width: 100%; height: 40px; }
```

### Step 3: Commit

```bash
git add static/js/cases.js static/style.css
git commit -m "feat(ui): activity sparkline on overview tab"
```

---

## Task 4 — Export Analysis Findings

**Files:**
- Modify: `static/js/chat.js`
- Modify: `templates/index.html`

### Step 1: Add export button in index.html

Find:
```html
              <button id="btn-view-report" class="btn-secondary">&#128196; View Full Report</button>
              <button id="btn-rerun-analysis" class="btn-secondary">&#8635; Re-run Analysis</button>
```

Replace with:
```html
              <button id="btn-view-report" class="btn-secondary">&#128196; View Full Report</button>
              <button id="btn-export-analysis" class="btn-secondary">&#128229; Export Markdown</button>
              <button id="btn-rerun-analysis" class="btn-secondary">&#8635; Re-run Analysis</button>
```

### Step 2: Add export logic in chat.js

Find:
```javascript
  const rerunBtn = dom("btn-rerun-analysis");
```

Insert before that line:

```javascript
  const exportBtn = dom("btn-export-analysis");
  if (exportBtn) {
    exportBtn.onclick = () => {
      let md = "# MobileTrace Analysis Report\n\n";
      rows.forEach(r => {
        const p = r.result_parsed ? _normalizeAnalysis(r.result_parsed) : null;
        md += `## ${_titleCase(r.artifact_key)}\n\n`;
        if (p) {
          const rsum = p.risk_level_summary || p.summary || "";
          if (rsum) md += `**Risk Summary:** ${rsum}\n\n`;
          const cra = Array.isArray(p.conversation_risk_assessment) ? p.conversation_risk_assessment : [];
          if (cra.length) {
            md += "### Conversation Risk Assessment\n\n";
            md += "| Thread | Risk | Score | Messages | Sent | Received |\n";
            md += "|--------|------|-------|----------|------|----------|\n";
            cra.forEach(t => {
              md += `| ${t.thread_id || "—"} | ${t.risk_level || "—"} | ${t.risk_score || 0}/10 | ${t.messages || 0} | ${t.sent || 0} | ${t.received || 0} |\n`;
            });
            md += "\n";
            cra.forEach(t => {
              if ((t.key_indicators || []).length) {
                md += `**${t.thread_id || "—"} — Key Indicators:**\n`;
                t.key_indicators.forEach(ki => { md += `- ${ki}\n`; });
                md += "\n";
              }
            });
          }
          const kf = p.key_findings;
          if (kf) {
            md += "### Key Findings\n\n";
            (kf.top_significant_conversations || []).forEach(tc => {
              md += `**${tc.thread_id || ""}:** ${tc.summary || ""}\n\n`;
              (tc.key_messages || []).forEach(km => {
                md += `> [${km.timestamp || ""}] (${km.direction || ""}): ${km.body || ""}\n\n`;
              });
            });
            if (kf.note) md += `*Note: ${kf.note}*\n\n`;
          }
        } else if (r.result) {
          md += r.result + "\n\n";
        }
        md += "---\n\n";
      });

      const blob = new Blob([md], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `analysis-${caseId}.md`;
      a.click();
      URL.revokeObjectURL(url);
    };
  }

```

### Step 3: Commit

```bash
git add static/js/chat.js templates/index.html
git commit -m "feat(ui): export analysis findings as Markdown download"
```

---

## Task 5 — Case Grouping by Status

**Files:**
- Modify: `static/js/cases.js`
- Modify: `static/style.css`

### Step 1: Group cases by status in renderCases

Find:
```javascript
function renderCases(cases) {
  caseList.innerHTML = cases.map(c => `
    <div class="case-item ${c.id === activeCaseId ? "active" : ""}" data-id="${c.id}">
      <div class="case-title">${c.title}</div>
      <div class="case-meta">
        ${c.officer || "&mdash;"} &middot; ${statusBadge(c.status)}
      </div>
    </div>
  `).join("");
  caseList.querySelectorAll(".case-item").forEach(el => {
    el.addEventListener("click", () => openCase(el.dataset.id));
  });
}
```

Replace with:
```javascript
function renderCases(cases) {
  // Group by status
  const groups = {};
  const statusOrder = ["open", "in_review", "on_hold", "closed"];
  cases.forEach(c => {
    const s = c.status || "open";
    if (!groups[s]) groups[s] = [];
    groups[s].push(c);
  });

  const sortedStatuses = statusOrder.filter(s => groups[s]?.length);
  // Add any statuses not in the predefined order
  Object.keys(groups).forEach(s => { if (!sortedStatuses.includes(s)) sortedStatuses.push(s); });

  caseList.innerHTML = sortedStatuses.map(status => `
    <details class="case-group" open>
      <summary class="case-group-header">${statusBadge(status)} <span class="case-group-count">${groups[status].length}</span></summary>
      ${groups[status].map(c => `
        <div class="case-item ${c.id === activeCaseId ? "active" : ""}" data-id="${c.id}">
          <div class="case-title">${c.title}</div>
          <div class="case-meta">${c.officer || "&mdash;"}</div>
        </div>
      `).join("")}
    </details>
  `).join("");

  caseList.querySelectorAll(".case-item").forEach(el => {
    el.addEventListener("click", () => openCase(el.dataset.id));
  });
}
```

### Step 2: Add case group CSS

Append to `static/style.css`:

```css

/* Case grouping */
.case-group { margin-bottom: 4px; }
.case-group-header { cursor: pointer; user-select: none; display: flex; align-items: center; gap: 6px; padding: 4px 0; font-size: 0.78rem; color: var(--text-muted); list-style: none; }
.case-group-header::-webkit-details-marker { display: none; }
.case-group-count { font-size: 0.7rem; background: var(--surface2); padding: 1px 6px; border-radius: 8px; }
```

### Step 3: Commit

```bash
git add static/js/cases.js static/style.css
git commit -m "feat(ui): case list grouped by status with collapsible sections"
```
