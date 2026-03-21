# Phase 3: Content Enhancement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance conversation UX with search highlighting and avatars, improve overview stats, add AI typing indicator, rich citations, and analysis insights summary.

**Architecture:** All changes are vanilla JS + CSS. Search highlighting wraps matches in `<mark>` tags. Avatars use CSS circles with initials and a deterministic color hash. Typing indicator is a CSS-only animation. No new dependencies.

**Tech Stack:** Vanilla JS (ES6 modules), CSS custom properties and animations.

---

## Task 1 — Search Highlighting in Conversations

**Files:**
- Modify: `static/js/conversations.js`
- Modify: `static/style.css`

### Step 1: Add highlight CSS

Append to end of `static/style.css`:

```css

/* Search highlighting */
.msg-bubble mark { background: rgba(227,179,65,0.35); color: inherit; border-radius: 2px; padding: 0 1px; }
```

### Step 2: Add highlight helper function in conversations.js

Find:
```javascript
function _escHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
```

Replace with:
```javascript
let _activeQuery = "";

function _escHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _highlightText(text, query) {
  if (!query) return _escHtml(text);
  const escaped = _escHtml(text);
  const qEsc = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return escaped.replace(new RegExp(`(${qEsc})`, "gi"), "<mark>$1</mark>");
}
```

### Step 3: Store active query during search

Find:
```javascript
  _searchTimer = setTimeout(() => _search(q), 400);
```

Replace with:
```javascript
  _searchTimer = setTimeout(() => { _activeQuery = q; _search(q); }, 400);
```

### Step 4: Clear query when search is cleared

Find:
```javascript
  if (!q) {
    _renderPlatformPills();
    _renderThreadList(_activePlatform ? _threads.filter(t => t.platform === _activePlatform) : _threads);
    _showEmptyMain();
    return;
  }
```

Replace with:
```javascript
  if (!q) {
    _activeQuery = "";
    _renderPlatformPills();
    _renderThreadList(_activePlatform ? _threads.filter(t => t.platform === _activePlatform) : _threads);
    _showEmptyMain();
    return;
  }
```

### Step 5: Apply highlighting in bubble rendering

Find:
```javascript
  const body = msg.body ? msg.body.trim() : "";
  if (body) {
    bubble.textContent = body;
  } else {
```

Replace with:
```javascript
  const body = msg.body ? msg.body.trim() : "";
  if (body) {
    if (_activeQuery) {
      bubble.innerHTML = _highlightText(body, _activeQuery);
    } else {
      bubble.textContent = body;
    }
  } else {
```

### Step 6: Clear query when opening a thread directly

Find:
```javascript
async function _openThread(platform, thread, messageCount) {
```

Replace with:
```javascript
async function _openThread(platform, thread, messageCount) {
  _activeQuery = "";
```

### Step 7: Commit

```bash
git add static/js/conversations.js static/style.css
git commit -m "feat(ui): search result highlighting in conversations"
```

---

## Task 2 — User Avatars (Initials)

**Files:**
- Modify: `static/js/conversations.js`
- Modify: `static/style.css`

### Step 1: Add avatar CSS

Append to `static/style.css`:

```css

/* User avatars */
.msg-avatar { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.65rem; font-weight: 700; color: #fff; flex-shrink: 0; text-transform: uppercase; }
.msg-wrap { flex-direction: row; gap: 8px; }
.msg-wrap.sent { flex-direction: row-reverse; }
.msg-content { display: flex; flex-direction: column; min-width: 0; }
.msg-wrap.sent .msg-content { align-items: flex-end; }
.msg-wrap.received .msg-content { align-items: flex-start; }
```

### Step 2: Add avatar color helper in conversations.js

Find:
```javascript
let _activeQuery = "";
```

Replace with:
```javascript
let _activeQuery = "";

const _avatarColors = ["#e06c75","#e5c07b","#98c379","#56b6c2","#61afef","#c678dd","#be5046","#d19a66"];
function _avatarColor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  return _avatarColors[Math.abs(h) % _avatarColors.length];
}
function _initials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? (parts[0][0] + parts[parts.length-1][0]) : name.slice(0, 2);
}
```

### Step 3: Add avatar to message bubble rendering

Find:
```javascript
  const bubble = document.createElement("div");
  bubble.className = `msg-bubble ${isSent ? "msg-sent" : "msg-received"}`;

  const body = msg.body ? msg.body.trim() : "";
```

Replace with:
```javascript
  // Avatar
  const senderName = msg.sender || (isSent ? "Me" : "?");
  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.style.background = _avatarColor(senderName);
  avatar.textContent = _initials(senderName);
  wrap.appendChild(avatar);

  const content = document.createElement("div");
  content.className = "msg-content";

  const bubble = document.createElement("div");
  bubble.className = `msg-bubble ${isSent ? "msg-sent" : "msg-received"}`;

  const body = msg.body ? msg.body.trim() : "";
```

### Step 4: Wrap bubble and timestamp in content div

Find:
```javascript
  wrap.appendChild(bubble);
  wrap.appendChild(ts);
  return wrap;
```

Replace with:
```javascript
  content.appendChild(bubble);
  content.appendChild(ts);
  wrap.appendChild(content);
  return wrap;
```

### Step 5: Commit

```bash
git add static/js/conversations.js static/style.css
git commit -m "feat(ui): initials-based avatars for conversation messages"
```

---

## Task 3 — Stats Icons & Device Card Redesign

**Files:**
- Modify: `static/js/cases.js`
- Modify: `static/style.css`

### Step 1: Add SVG icons to stat cards

Find:
```javascript
    el.innerHTML = [
      { label: "Messages",  value: msgs.count ?? msgs.length ?? 0 },
      { label: "Contacts",  value: contacts.count ?? contacts.length ?? 0 },
      { label: "Calls",     value: calls.count ?? calls.length ?? 0 },
      { label: "Analyses",  value: Array.isArray(analysis) ? analysis.length : 0 },
    ].map(s => `
      <div class="stat-card">
        <div class="stat-value">${s.value}</div>
        <div class="stat-label">${s.label}</div>
      </div>`).join("");
```

Replace with:
```javascript
    const statIcons = {
      Messages: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
      Contacts: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>',
      Calls: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.362 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.338 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>',
      Analyses: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    };
    el.innerHTML = [
      { label: "Messages",  value: msgs.count ?? msgs.length ?? 0 },
      { label: "Contacts",  value: contacts.count ?? contacts.length ?? 0 },
      { label: "Calls",     value: calls.count ?? calls.length ?? 0 },
      { label: "Analyses",  value: Array.isArray(analysis) ? analysis.length : 0 },
    ].map(s => `
      <div class="stat-card">
        <div class="stat-icon">${statIcons[s.label] || ""}</div>
        <div class="stat-value">${s.value}</div>
        <div class="stat-label">${s.label}</div>
      </div>`).join("");
```

### Step 2: Add stat icon CSS

Find:
```css
.stat-card { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; }
```

Replace with:
```css
.stat-card { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; }
.stat-icon { color: var(--info); margin-bottom: 6px; opacity: 0.7; }
```

### Step 3: Redesign device info card

Find:
```javascript
    if (Object.keys(di).length) {
      diEl.innerHTML = "<dl>" + Object.entries(di).map(([k, v]) =>
        `<dt>${k}</dt><dd>${v}</dd>`).join("") + "</dl>";
    } else {
```

Replace with:
```javascript
    if (Object.keys(di).length) {
      diEl.innerHTML = `<div class="device-card-header"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12" y2="18.01"/></svg><span>Device Information</span></div><dl>` + Object.entries(di).map(([k, v]) =>
        `<dt>${k}</dt><dd>${v}</dd>`).join("") + "</dl>";
    } else {
```

### Step 4: Add device card header CSS

Find:
```css
.device-info-block { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; font-size: 0.85rem; }
```

Replace with:
```css
.device-info-block { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; font-size: 0.85rem; }
.device-card-header { display: flex; align-items: center; gap: 8px; font-weight: 600; color: var(--info); margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
```

### Step 5: Commit

```bash
git add static/js/cases.js static/style.css
git commit -m "feat(ui): stat card icons and device info card redesign"
```

---

## Task 4 — AI Typing Indicator

**Files:**
- Modify: `static/js/chat.js`
- Modify: `static/style.css`

### Step 1: Add typing indicator CSS

Append to `static/style.css`:

```css

/* AI typing indicator */
.typing-indicator { display: flex; gap: 4px; align-items: center; padding: 4px 0; }
.typing-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); animation: typing-bounce 1.2s ease-in-out infinite; }
.typing-dot:nth-child(2) { animation-delay: 0.15s; }
.typing-dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes typing-bounce { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }
```

### Step 2: Replace static "Analysing…" with animated dots

In `static/js/chat.js`, find:

```javascript
function _appendThinking() {
  const container = dom("chat-messages");
  if (!container) return null;
  const div = document.createElement("div");
  div.className = "chat-bubble thinking";
  div.textContent = "Analysing…";
  container.appendChild(div);
  _scrollToBottom();
  return div;
}
```

Replace with:
```javascript
function _appendThinking() {
  const container = dom("chat-messages");
  if (!container) return null;
  const div = document.createElement("div");
  div.className = "chat-bubble thinking";
  div.innerHTML = '<div class="typing-indicator"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>';
  container.appendChild(div);
  _scrollToBottom();
  return div;
}
```

### Step 3: Commit

```bash
git add static/js/chat.js static/style.css
git commit -m "feat(ui): animated typing indicator for AI chat"
```

---

## Task 5 — Rich Citations Styling

**Files:**
- Modify: `static/js/chat.js`
- Modify: `static/style.css`

### Step 1: Improve citations rendering with snippets

Find:
```javascript
function _renderCitations(contextCount) {
  const panel = dom("chat-citations");
  if (!panel) return;
  if (!contextCount) {
    panel.innerHTML = '<p class="muted">No matching evidence found for this query.</p>';
    return;
  }
  panel.innerHTML = `<p class="muted">${contextCount} evidence record${contextCount !== 1 ? "s" : ""} used as context.</p>`;
}
```

Replace with:
```javascript
function _renderCitations(contextCount, citations) {
  const panel = dom("chat-citations");
  if (!panel) return;
  if (!contextCount) {
    panel.innerHTML = '<p class="muted">No matching evidence found for this query.</p>';
    return;
  }
  if (citations && Array.isArray(citations) && citations.length) {
    panel.innerHTML = citations.map((c, i) => `
      <div class="citation-item">
        <div class="cit-num">[${i + 1}]</div>
        <div class="cit-platform">${c.platform || ""} · ${c.thread_id || ""}</div>
        <div class="cit-body">${(c.body || c.text || "").slice(0, 120)}${(c.body || c.text || "").length > 120 ? "…" : ""}</div>
      </div>
    `).join("");
  } else {
    panel.innerHTML = `<p class="muted">${contextCount} evidence record${contextCount !== 1 ? "s" : ""} used as context.</p>`;
  }
}
```

### Step 2: Pass citations array from chat response

Find:
```javascript
    _renderCitations(data.context_count || 0);
```

Replace with:
```javascript
    _renderCitations(data.context_count || 0, data.citations || []);
```

### Step 3: Enhance citation item CSS

Find:
```css
.citation-item { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 10px; }
.citation-item .cit-platform { font-size: 0.7rem; color: var(--info); font-weight: 600; margin-bottom: 2px; }
.citation-item .cit-body { color: var(--text-muted); }
```

Replace with:
```css
.citation-item { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 10px; position: relative; }
.citation-item .cit-num { position: absolute; top: 6px; right: 8px; font-size: 0.65rem; color: var(--info); font-weight: 700; background: rgba(88,166,255,0.1); padding: 1px 5px; border-radius: 3px; }
.citation-item .cit-platform { font-size: 0.7rem; color: var(--info); font-weight: 600; margin-bottom: 2px; }
.citation-item .cit-body { color: var(--text-muted); font-size: 0.75rem; line-height: 1.4; }
```

### Step 4: Commit

```bash
git add static/js/chat.js static/style.css
git commit -m "feat(ui): rich citations with snippets and numbered badges"
```

---

## Task 6 — Top Insights Summary

**Files:**
- Modify: `static/js/chat.js`
- Modify: `static/style.css`

### Step 1: Add insights summary CSS

Append to `static/style.css`:

```css

/* Analysis insights bar */
.analysis-insights-bar { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.insight-chip { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 14px; font-size: 0.78rem; display: flex; align-items: center; gap: 6px; }
.insight-chip-value { font-weight: 700; color: var(--info); font-size: 0.95rem; }
.insight-chip-label { color: var(--text-muted); }
```

### Step 2: Add insights bar rendering in loadAnalysisResults

In `static/js/chat.js`, find:
```javascript
  // ── Executive Summary ──────────────────────────────────────────
  execContent.innerHTML = "";
```

Replace with:
```javascript
  // ── Insights Bar ───────────────────────────────────────────────
  let existingBar = resultsView.querySelector(".analysis-insights-bar");
  if (existingBar) existingBar.remove();
  const insightsBar = document.createElement("div");
  insightsBar.className = "analysis-insights-bar";
  const totalThreads = rows.reduce((s, r) => s + ((r.result_parsed?.conversation_risk_assessment) || []).length, 0);
  const topRisk = rows.reduce((best, r) => {
    const rl = _jsonRiskLevel(r.result_parsed || {});
    if (!best) return rl;
    const order = ["CRITICAL","HIGH","MEDIUM","LOW"];
    return order.indexOf(rl) < order.indexOf(best) ? rl : best;
  }, null);
  const platforms = [...new Set(rows.flatMap(r => ((r.result_parsed?.conversation_risk_assessment) || []).map(t => {
    const tid = t.thread_id || "";
    if (tid.includes("whatsapp")) return "WhatsApp";
    if (tid.includes("telegram")) return "Telegram";
    if (tid.includes("signal")) return "Signal";
    return "SMS";
  })))];
  insightsBar.innerHTML = [
    { value: rows.length, label: "Artifacts" },
    { value: totalThreads, label: "Threads" },
    topRisk ? { value: `<span class="confidence-inline ${_confidenceClass(topRisk)}">${topRisk}</span>`, label: "Risk" } : null,
    platforms.length ? { value: platforms.join(", "), label: "Platforms" } : null,
  ].filter(Boolean).map(c => `<div class="insight-chip"><span class="insight-chip-value">${c.value}</span><span class="insight-chip-label">${c.label}</span></div>`).join("");
  resultsView.insertBefore(insightsBar, resultsView.firstChild);

  // ── Executive Summary ──────────────────────────────────────────
  execContent.innerHTML = "";
```

### Step 3: Commit

```bash
git add static/js/chat.js static/style.css
git commit -m "feat(ui): analysis insights summary bar with key metrics"
```
