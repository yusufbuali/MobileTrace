# Phase 1: Foundation & Polish — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve semantic HTML, accessibility, visual polish, and add a reusable toast notification system.

**Architecture:** Pure CSS + vanilla JS changes. No new dependencies. Toast system as a standalone ES6 module. Semantic HTML upgrades in index.html. CSS transitions and typography refinements in style.css.

**Tech Stack:** Vanilla JS (ES6 modules), CSS custom properties, HTML5 semantic elements.

---

## Task 1 — Semantic HTML & Accessibility

**Files:**
- Modify: `templates/index.html`

### Step 1: Wrap sidebar case list in semantic elements

Find:
```html
      <div id="case-list"></div>
```

Replace with:
```html
      <nav id="case-list" aria-label="Case list"></nav>
```

### Step 2: Add ARIA roles to tab buttons

Find:
```html
        <div class="tabs">
          <button class="tab-btn active" data-tab="tab-overview">Overview</button>
          <button class="tab-btn" data-tab="tab-evidence">Evidence</button>
          <button class="tab-btn" data-tab="tab-conversations">Conversations</button>
          <button class="tab-btn" data-tab="tab-analysis">Analysis</button>
          <button class="tab-btn" data-tab="tab-chat">Chat</button>
        </div>
```

Replace with:
```html
        <div class="tabs" role="tablist" aria-label="Case sections">
          <button class="tab-btn active" data-tab="tab-overview" role="tab" aria-selected="true" aria-controls="tab-overview">Overview</button>
          <button class="tab-btn" data-tab="tab-evidence" role="tab" aria-selected="false" aria-controls="tab-evidence">Evidence</button>
          <button class="tab-btn" data-tab="tab-conversations" role="tab" aria-selected="false" aria-controls="tab-conversations">Conversations</button>
          <button class="tab-btn" data-tab="tab-analysis" role="tab" aria-selected="false" aria-controls="tab-analysis">Analysis</button>
          <button class="tab-btn" data-tab="tab-chat" role="tab" aria-selected="false" aria-controls="tab-chat">Chat</button>
        </div>
```

### Step 3: Add `role="tabpanel"` to each tab panel

Find each of these and add `role="tabpanel"`:

```html
        <div id="tab-overview" class="tab-panel active">
```
→
```html
        <div id="tab-overview" class="tab-panel active" role="tabpanel">
```

```html
        <div id="tab-evidence" class="tab-panel">
```
→
```html
        <div id="tab-evidence" class="tab-panel" role="tabpanel">
```

```html
        <div id="tab-conversations" class="tab-panel">
```
→
```html
        <div id="tab-conversations" class="tab-panel" role="tabpanel">
```

```html
        <div id="tab-analysis" class="tab-panel">
```
→
```html
        <div id="tab-analysis" class="tab-panel" role="tabpanel">
```

```html
        <div id="tab-chat" class="tab-panel">
```
→
```html
        <div id="tab-chat" class="tab-panel" role="tabpanel">
```

### Step 4: Add dialog role to settings modal

Find:
```html
      <div class="modal-box">
```

Replace with:
```html
      <div class="modal-box" role="dialog" aria-modal="true" aria-label="AI Provider Settings">
```

### Step 5: Add aria-labels to search inputs

Find:
```html
        <input id="search-cases" type="text" placeholder="Search cases&hellip;" />
```

Replace with:
```html
        <input id="search-cases" type="text" placeholder="Search cases&hellip;" aria-label="Search cases" />
```

Find:
```html
              <input id="conv-search" type="text" placeholder="Search messages&hellip;" />
```

Replace with:
```html
              <input id="conv-search" type="text" placeholder="Search messages&hellip;" aria-label="Search messages" />
```

### Step 6: Update tab switching JS for ARIA

In `static/js/cases.js`, find:
```javascript
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    const target = document.getElementById(btn.dataset.tab);
    if (target) target.classList.add("active");
```

Replace with:
```javascript
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    btn.setAttribute("aria-selected", "true");
    const target = document.getElementById(btn.dataset.tab);
    if (target) target.classList.add("active");
```

### Step 7: Commit

```bash
git add templates/index.html static/js/cases.js
git commit -m "feat(ui): semantic HTML and ARIA accessibility improvements"
```

---

## Task 2 — Toast Notification System

**Files:**
- Create: `static/js/toast.js`
- Modify: `static/style.css`
- Modify: `templates/index.html`
- Modify: `static/js/cases.js`

### Step 1: Create toast.js module

Create `static/js/toast.js`:

```javascript
/**
 * toast.js — Lightweight toast notification system for MobileTrace.
 */

let _container = null;

function _getContainer() {
  if (_container) return _container;
  _container = document.createElement("div");
  _container.id = "toast-container";
  document.body.appendChild(_container);
  return _container;
}

/**
 * Show a toast notification.
 * @param {string} message - Text to display
 * @param {"success"|"error"|"info"|"warning"} [type="info"] - Toast type
 * @param {number} [duration=4000] - Auto-dismiss time in ms
 */
export function showToast(message, type = "info", duration = 4000) {
  const container = _getContainer();
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  // Close button
  const close = document.createElement("button");
  close.className = "toast-close";
  close.innerHTML = "&times;";
  close.addEventListener("click", () => _dismiss(toast));
  toast.appendChild(close);

  container.appendChild(toast);

  // Trigger enter animation
  requestAnimationFrame(() => toast.classList.add("toast-visible"));

  // Auto-dismiss
  if (duration > 0) {
    setTimeout(() => _dismiss(toast), duration);
  }
}

function _dismiss(toast) {
  if (!toast || toast.dataset.dismissing) return;
  toast.dataset.dismissing = "1";
  toast.classList.remove("toast-visible");
  toast.addEventListener("transitionend", () => toast.remove(), { once: true });
  // Fallback removal if transition doesn't fire
  setTimeout(() => toast.remove(), 400);
}
```

### Step 2: Add toast CSS to style.css

Append to the end of `static/style.css`:

```css

/* Toast notifications */
#toast-container { position: fixed; top: 16px; right: 16px; z-index: 1100; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast { pointer-events: auto; display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: var(--radius); font-size: 0.82rem; color: #fff; opacity: 0; transform: translateX(40px); transition: opacity 0.25s, transform 0.25s; max-width: 360px; box-shadow: 0 4px 16px rgba(0,0,0,0.4); }
.toast-visible { opacity: 1; transform: translateX(0); }
.toast-success { background: #1a7f37; }
.toast-error { background: #b62324; }
.toast-info { background: #1a4a7a; }
.toast-warning { background: #7a5a1a; }
.toast-close { background: none; border: none; color: rgba(255,255,255,0.7); font-size: 1.1rem; cursor: pointer; padding: 0 2px; line-height: 1; flex-shrink: 0; }
.toast-close:hover { color: #fff; }
```

### Step 3: Add toast.js script tag to index.html

Find:
```html
  <script type="module" src="/static/js/settings.js?v=20260308"></script>
```

Replace with:
```html
  <script type="module" src="/static/js/toast.js?v=20260308"></script>
  <script type="module" src="/static/js/settings.js?v=20260308"></script>
```

### Step 4: Replace alert() in cases.js with toast

In `static/js/cases.js`, add import at top:

Find:
```javascript
import { api, apiFetch } from "./api.js";
```

Replace with:
```javascript
import { api, apiFetch } from "./api.js";
import { showToast } from "./toast.js";
```

Find:
```javascript
    alert("Failed to create case: " + err.message);
```

Replace with:
```javascript
    showToast("Failed to create case: " + err.message, "error");
```

### Step 5: Replace inline upload status with toasts

In `static/js/cases.js`, find the browser upload success/error block:

Find:
```javascript
      formUpload.reset();
      if (statusEl) statusEl.textContent = `Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`;
      _loadEvidence(activeCaseId);
      openCase(activeCaseId);
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    }
```

Replace with:
```javascript
      formUpload.reset();
      if (statusEl) statusEl.textContent = "";
      showToast(`Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`, "success");
      _loadEvidence(activeCaseId);
      openCase(activeCaseId);
    } catch (err) {
      if (statusEl) statusEl.textContent = "";
      showToast(`Upload error: ${err.message}`, "error");
    }
```

Find the local path success/error block:

Find:
```javascript
      formPath.reset();
      if (statusEl) statusEl.textContent = `Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`;
      _loadEvidence(activeCaseId);
      openCase(activeCaseId);
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    }
```

Replace with:
```javascript
      formPath.reset();
      if (statusEl) statusEl.textContent = "";
      showToast(`Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`, "success");
      _loadEvidence(activeCaseId);
      openCase(activeCaseId);
    } catch (err) {
      if (statusEl) statusEl.textContent = "";
      showToast(`Parse error: ${err.message}`, "error");
    }
```

### Step 6: Commit

```bash
git add static/js/toast.js static/style.css templates/index.html static/js/cases.js
git commit -m "feat(ui): add toast notification system, replace alerts and inline status"
```

---

## Task 3 — Brand SVG & Sidebar Polish

**Files:**
- Modify: `templates/index.html`
- Modify: `static/style.css`

### Step 1: Replace phone emoji with inline SVG brand icon

Find:
```html
        <span class="brand-icon">&#128241;</span>
```

Replace with:
```html
        <span class="brand-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12" y2="18.01"/><circle cx="17" cy="6" r="3" fill="none" stroke="currentColor" stroke-width="1.5"/><line x1="19.1" y1="8.1" x2="21" y2="10"/></svg></span>
```

### Step 2: Add left accent bar to active case item

Find:
```css
.case-item.active { background: var(--surface2); border-color: var(--info); }
```

Replace with:
```css
.case-item.active { background: var(--surface2); border-color: var(--info); border-left: 3px solid var(--info); }
```

### Step 3: Add hover transition to case items

Find:
```css
.case-item { padding: 10px 12px; border-radius: var(--radius); cursor: pointer; border: 1px solid transparent; transition: background 0.15s; }
```

Replace with:
```css
.case-item { padding: 10px 12px; border-radius: var(--radius); cursor: pointer; border: 1px solid transparent; border-left: 3px solid transparent; transition: background 0.15s, border-color 0.15s; }
```

### Step 4: Commit

```bash
git add templates/index.html static/style.css
git commit -m "feat(ui): SVG brand icon and sidebar active state polish"
```

---

## Task 4 — Typography & Micro-animations

**Files:**
- Modify: `static/style.css`

### Step 1: Add tab hover/active transition

Find:
```css
.tab-btn { background: none; border: none; color: var(--text-muted); padding: 8px 16px; cursor: pointer; font-size: 0.9rem; border-bottom: 2px solid transparent; margin-bottom: -1px; }
```

Replace with:
```css
.tab-btn { background: none; border: none; color: var(--text-muted); padding: 8px 16px; cursor: pointer; font-size: 0.82rem; border-bottom: 2px solid transparent; margin-bottom: -1px; transition: color 0.15s, border-color 0.15s; }
```

### Step 2: Add modal fade-in animation

Find:
```css
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 999; }
```

Replace with:
```css
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 999; animation: modal-fadein 0.2s ease; }
@keyframes modal-fadein { from { opacity: 0; } to { opacity: 1; } }
.modal-box { animation: modal-slidein 0.2s ease; }
@keyframes modal-slidein { from { opacity: 0; transform: translateY(-12px); } to { opacity: 1; transform: translateY(0); } }
```

Note: The existing `.modal-box` rule on the next line remains unchanged.

### Step 3: Enhance stat card values for better hierarchy

Find:
```css
.stat-card .stat-value { font-size: 1.6rem; font-weight: 700; color: var(--info); }
```

Replace with:
```css
.stat-card .stat-value { font-size: 1.8rem; font-weight: 700; color: var(--info); letter-spacing: -0.02em; }
```

### Step 4: Add hover transition to secondary buttons

Find:
```css
.btn-secondary { background: var(--surface2); color: var(--info); border: 1px solid var(--info); padding: 10px 18px; border-radius: var(--radius); cursor: pointer; font-size: 0.9rem; text-decoration: none; display: inline-block; }
```

Replace with:
```css
.btn-secondary { background: var(--surface2); color: var(--info); border: 1px solid var(--info); padding: 10px 18px; border-radius: var(--radius); cursor: pointer; font-size: 0.9rem; text-decoration: none; display: inline-block; transition: background 0.15s, border-color 0.15s; }
.btn-secondary:hover { background: rgba(88,166,255,0.08); }
```

### Step 5: Commit

```bash
git add static/style.css
git commit -m "feat(ui): typography refinements and micro-animations"
```
