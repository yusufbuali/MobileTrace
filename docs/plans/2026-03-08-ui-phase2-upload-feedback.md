# Phase 2: Upload & Feedback — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add drag-and-drop evidence upload, upload progress tracking, file type icons, light/dark mode, and responsive layout.

**Architecture:** Drag-and-drop via HTML5 drag events on the existing upload area. Upload progress via XMLHttpRequest replacing fetch(). Light mode via a second set of CSS custom properties applied with `[data-theme="light"]`. Responsive via `@media` queries. No new dependencies.

**Tech Stack:** Vanilla JS (ES6 modules), CSS custom properties, HTML5 Drag-and-Drop API, XMLHttpRequest.

---

## Task 1 — Drag & Drop Zone

**Files:**
- Modify: `static/style.css`
- Modify: `static/js/cases.js`

### Step 1: Add drag-and-drop CSS styles

Append after the `.ev-status` rule in `static/style.css`:

Find:
```css
.ev-status { font-size: 0.8rem; color: var(--info); margin-top: 2px; }
```

Replace with:
```css
.ev-status { font-size: 0.8rem; color: var(--info); margin-top: 2px; }
.evidence-upload-area.drag-over { border-color: var(--info); border-style: dashed; background: rgba(88,166,255,0.06); }
.ev-drop-hint { display: none; text-align: center; padding: 20px; color: var(--info); font-size: 0.85rem; font-weight: 600; }
.evidence-upload-area.drag-over .ev-drop-hint { display: block; }
.evidence-upload-area.drag-over .upload-form { display: none; }
.evidence-upload-area.drag-over .ev-mode-tabs { display: none; }
```

### Step 2: Add drop hint element in index.html

Find:
```html
          <div class="evidence-upload-area">
            <!-- Mode toggle -->
```

Replace with:
```html
          <div class="evidence-upload-area">
            <div class="ev-drop-hint">Drop evidence file here</div>
            <!-- Mode toggle -->
```

### Step 3: Add drag-and-drop event handlers in cases.js

Find:
```javascript
// ── Evidence upload ───────────────────────────────────────────────────────────
```

Replace with:
```javascript
// ── Evidence drag & drop ─────────────────────────────────────────────────────

const uploadArea = document.querySelector(".evidence-upload-area");
if (uploadArea) {
  ["dragenter", "dragover"].forEach(evt => {
    uploadArea.addEventListener(evt, (e) => {
      e.preventDefault();
      uploadArea.classList.add("drag-over");
    });
  });
  ["dragleave", "drop"].forEach(evt => {
    uploadArea.addEventListener(evt, (e) => {
      e.preventDefault();
      uploadArea.classList.remove("drag-over");
    });
  });
  uploadArea.addEventListener("drop", (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (!file || !activeCaseId) return;
    const fd = new FormData();
    fd.append("file", file);
    // Reuse upload logic
    const statusEl = document.getElementById("ev-upload-status");
    if (statusEl) statusEl.textContent = "Uploading…";
    fetch(`/api/cases/${activeCaseId}/evidence`, { method: "POST", body: fd })
      .then(r => r.json().then(data => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) throw new Error(data.error || "Upload failed");
        if (statusEl) statusEl.textContent = "";
        showToast(`Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`, "success");
        _loadEvidence(activeCaseId);
        openCase(activeCaseId);
      })
      .catch(err => {
        if (statusEl) statusEl.textContent = "";
        showToast(`Upload error: ${err.message}`, "error");
      });
  });
}

// ── Evidence upload ───────────────────────────────────────────────────────────
```

### Step 4: Commit

```bash
git add static/style.css static/js/cases.js templates/index.html
git commit -m "feat(ui): drag-and-drop evidence upload zone"
```

---

## Task 2 — File Type Icons in Evidence List

**Files:**
- Modify: `static/js/cases.js`
- Modify: `static/style.css`

### Step 1: Add format icon helper function in cases.js

Find:
```javascript
async function _loadEvidence(caseId) {
```

Insert before that line:

```javascript
function _formatIcon(format) {
  const icons = {
    ufdr: '<svg class="ev-icon" viewBox="0 0 16 16" width="16" height="16"><rect x="4" y="1" width="8" height="14" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.2"/><line x1="8" y1="12" x2="8" y2="12.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    xry: '<svg class="ev-icon" viewBox="0 0 16 16" width="16" height="16"><rect x="2" y="4" width="12" height="8" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" stroke-width="1"/><line x1="5" y1="4" x2="5" y2="2" stroke="currentColor" stroke-width="1.2"/><line x1="8" y1="4" x2="8" y2="2" stroke="currentColor" stroke-width="1.2"/><line x1="11" y1="4" x2="11" y2="2" stroke="currentColor" stroke-width="1.2"/></svg>',
    oxygen: '<svg class="ev-icon" viewBox="0 0 16 16" width="16" height="16"><ellipse cx="8" cy="8" rx="6" ry="5" fill="none" stroke="currentColor" stroke-width="1.2"/><ellipse cx="8" cy="8" rx="2.5" ry="2" fill="none" stroke="currentColor" stroke-width="1"/></svg>',
    ios_fs: '<svg class="ev-icon" viewBox="0 0 16 16" width="16" height="16"><rect x="4" y="1" width="8" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.2"/><line x1="6" y1="3" x2="10" y2="3" stroke="currentColor" stroke-width="1" stroke-linecap="round"/></svg>',
    android_tar: '<svg class="ev-icon" viewBox="0 0 16 16" width="16" height="16"><rect x="4" y="6" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.2"/><circle cx="6.5" cy="9" r="0.7" fill="currentColor"/><circle cx="9.5" cy="9" r="0.7" fill="currentColor"/><line x1="4.5" y1="6" x2="3" y2="3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><line x1="11.5" y1="6" x2="13" y2="3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>',
  };
  return icons[format] || icons[Object.keys(icons).find(k => (format || "").includes(k))] || '<svg class="ev-icon" viewBox="0 0 16 16" width="16" height="16"><rect x="3" y="1" width="10" height="14" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/><line x1="5" y1="5" x2="11" y2="5" stroke="currentColor" stroke-width="1"/><line x1="5" y1="8" x2="11" y2="8" stroke="currentColor" stroke-width="1"/></svg>';
}

```

### Step 2: Add icon to evidence item rendering

Find:
```javascript
              <span class="ev-format">${e.format}</span>
```

Replace with:
```javascript
              ${_formatIcon(e.format)}
              <span class="ev-format">${e.format}</span>
```

### Step 3: Add icon CSS

Append to `static/style.css` after `.evidence-item .ev-status-error`:

Find:
```css
.evidence-item .ev-status-error { color: var(--danger); }
```

Replace with:
```css
.evidence-item .ev-status-error { color: var(--danger); }
.ev-icon { vertical-align: middle; margin-right: 4px; color: var(--info); flex-shrink: 0; }
```

### Step 4: Commit

```bash
git add static/js/cases.js static/style.css
git commit -m "feat(ui): file type SVG icons in evidence list"
```

---

## Task 3 — Upload Progress Bar

**Files:**
- Modify: `static/js/cases.js`
- Modify: `templates/index.html`
- Modify: `static/style.css`

### Step 1: Add progress bar element in index.html

Find:
```html
              <button type="submit" class="btn-primary">Upload &amp; Parse</button>
              <span id="ev-upload-status" class="ev-status"></span>
```

Replace with:
```html
              <button type="submit" class="btn-primary">Upload &amp; Parse</button>
              <div id="ev-progress-wrap" class="ev-progress-wrap" style="display:none">
                <div class="ev-progress-track"><div id="ev-progress-fill" class="ev-progress-fill"></div></div>
                <span id="ev-progress-pct" class="ev-progress-pct">0%</span>
              </div>
              <span id="ev-upload-status" class="ev-status"></span>
```

### Step 2: Add progress bar CSS

Append to `static/style.css` after the `.ev-icon` rule:

Find:
```css
.ev-icon { vertical-align: middle; margin-right: 4px; color: var(--info); flex-shrink: 0; }
```

Replace with:
```css
.ev-icon { vertical-align: middle; margin-right: 4px; color: var(--info); flex-shrink: 0; }
.ev-progress-wrap { display: flex; align-items: center; gap: 8px; }
.ev-progress-track { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
.ev-progress-fill { height: 100%; width: 0%; background: var(--info); border-radius: 3px; transition: width 0.2s; }
.ev-progress-pct { font-size: 0.75rem; color: var(--text-muted); min-width: 32px; }
```

### Step 3: Replace fetch with XMLHttpRequest for browser upload

In `static/js/cases.js`, replace the entire browser upload handler:

Find:
```javascript
if (formUpload) {
  formUpload.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeCaseId) return;
    const statusEl = document.getElementById("ev-upload-status");
    if (statusEl) statusEl.textContent = "Uploading…";
    const fd = new FormData(formUpload);
    try {
      const res = await fetch(`/api/cases/${activeCaseId}/evidence`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Upload failed");
      formUpload.reset();
      if (statusEl) statusEl.textContent = "";
      showToast(`Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`, "success");
      _loadEvidence(activeCaseId);
      openCase(activeCaseId);
    } catch (err) {
      if (statusEl) statusEl.textContent = "";
      showToast(`Upload error: ${err.message}`, "error");
    }
  });
}
```

Replace with:
```javascript
if (formUpload) {
  formUpload.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!activeCaseId) return;
    const statusEl = document.getElementById("ev-upload-status");
    const progressWrap = document.getElementById("ev-progress-wrap");
    const progressFill = document.getElementById("ev-progress-fill");
    const progressPct = document.getElementById("ev-progress-pct");
    if (statusEl) statusEl.textContent = "";
    if (progressWrap) progressWrap.style.display = "";
    if (progressFill) progressFill.style.width = "0%";
    if (progressPct) progressPct.textContent = "0%";

    const fd = new FormData(formUpload);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/cases/${activeCaseId}/evidence`);

    xhr.upload.addEventListener("progress", (ev) => {
      if (ev.lengthComputable) {
        const pct = Math.round((ev.loaded / ev.total) * 100);
        if (progressFill) progressFill.style.width = pct + "%";
        if (progressPct) progressPct.textContent = pct + "%";
      }
    });

    xhr.addEventListener("load", () => {
      if (progressWrap) progressWrap.style.display = "none";
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 400) throw new Error(data.error || "Upload failed");
        formUpload.reset();
        showToast(`Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`, "success");
        _loadEvidence(activeCaseId);
        openCase(activeCaseId);
      } catch (err) {
        showToast(`Upload error: ${err.message}`, "error");
      }
    });

    xhr.addEventListener("error", () => {
      if (progressWrap) progressWrap.style.display = "none";
      showToast("Upload failed — network error", "error");
    });

    xhr.send(fd);
  });
}
```

### Step 4: Commit

```bash
git add static/js/cases.js templates/index.html static/style.css
git commit -m "feat(ui): upload progress bar with XMLHttpRequest"
```

---

## Task 4 — Light/Dark Mode Toggle

**Files:**
- Modify: `static/style.css`
- Modify: `templates/index.html`
- Modify: `static/js/cases.js`

### Step 1: Add light theme CSS variables

In `static/style.css`, find:
```css
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --surface2: #21262d;
  --border: #30363d;
  --accent: #238636;
  --accent-hover: #2ea043;
  --text: #c9d1d9;
  --text-muted: #8b949e;
  --danger: #f85149;
  --warning: #e3b341;
  --info: #58a6ff;
  --font: 'Segoe UI', system-ui, sans-serif;
  --radius: 6px;
}
```

Replace with:
```css
:root {
  --bg: #0d1117;
  --surface: #161b22;
  --surface2: #21262d;
  --border: #30363d;
  --accent: #238636;
  --accent-hover: #2ea043;
  --text: #c9d1d9;
  --text-muted: #8b949e;
  --danger: #f85149;
  --warning: #e3b341;
  --info: #58a6ff;
  --font: 'Segoe UI', system-ui, sans-serif;
  --radius: 6px;
}
[data-theme="light"] {
  --bg: #ffffff;
  --surface: #f6f8fa;
  --surface2: #eaeef2;
  --border: #d0d7de;
  --accent: #1a7f37;
  --accent-hover: #218739;
  --text: #1f2328;
  --text-muted: #656d76;
  --danger: #cf222e;
  --warning: #9a6700;
  --info: #0969da;
}
```

### Step 2: Add theme toggle button in sidebar

Find:
```html
      <button id="btn-settings" class="btn-gear" title="AI Settings">&#9881; Settings</button>
```

Replace with:
```html
      <div class="sidebar-bottom-row">
        <button id="btn-theme" class="btn-gear" title="Toggle light/dark mode">&#9790; Theme</button>
        <button id="btn-settings" class="btn-gear" title="AI Settings">&#9881; Settings</button>
      </div>
```

### Step 3: Add sidebar bottom row CSS

Append to `static/style.css` after the `.btn-gear:hover` rule:

Find:
```css
.btn-gear:hover { color: var(--text); border-color: var(--text-muted); }
```

Replace with:
```css
.btn-gear:hover { color: var(--text); border-color: var(--text-muted); }
.sidebar-bottom-row { display: flex; gap: 6px; }
.sidebar-bottom-row .btn-gear { flex: 1; }
```

### Step 4: Add theme toggle logic in cases.js

Find:
```javascript
// ── Boot ──────────────────────────────────────────────────────────────────────
loadCases();
```

Replace with:
```javascript
// ── Theme toggle ─────────────────────────────────────────────────────────────
const btnTheme = document.getElementById("btn-theme");
function _applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("mt-theme", theme);
  if (btnTheme) btnTheme.innerHTML = theme === "light" ? "&#9728; Theme" : "&#9790; Theme";
}
_applyTheme(localStorage.getItem("mt-theme") || "dark");
if (btnTheme) {
  btnTheme.addEventListener("click", () => {
    _applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light");
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────────
loadCases();
```

### Step 5: Commit

```bash
git add static/style.css templates/index.html static/js/cases.js
git commit -m "feat(ui): light/dark mode toggle with localStorage persistence"
```

---

## Task 5 — Responsive Breakpoints

**Files:**
- Modify: `static/style.css`
- Modify: `templates/index.html`
- Modify: `static/js/cases.js`

### Step 1: Add hamburger button in index.html

Find:
```html
    <main id="main">
```

Replace with:
```html
    <main id="main">
      <button id="btn-sidebar-toggle" class="sidebar-toggle" aria-label="Toggle sidebar">&#9776;</button>
```

### Step 2: Add responsive CSS at end of style.css

Append to the end of `static/style.css`:

```css

/* Responsive */
.sidebar-toggle { display: none; position: fixed; top: 10px; left: 10px; z-index: 100; background: var(--surface2); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: var(--radius); cursor: pointer; font-size: 1.1rem; }

@media (max-width: 1024px) {
  #app { grid-template-columns: 220px 1fr; }
  .conv-layout { grid-template-columns: 200px 1fr; }
  .chat-layout { grid-template-columns: 1fr 200px; }
}

@media (max-width: 768px) {
  #app { grid-template-columns: 1fr; }
  #sidebar { position: fixed; left: -280px; top: 0; bottom: 0; width: 280px; z-index: 200; transition: left 0.25s ease; box-shadow: none; }
  #sidebar.sidebar-open { left: 0; box-shadow: 4px 0 20px rgba(0,0,0,0.4); }
  .sidebar-toggle { display: block; }
  #main { padding: 16px; padding-top: 48px; }
  .conv-layout { grid-template-columns: 1fr; height: auto; }
  .conv-sidebar { max-height: 200px; border-right: none; border-bottom: 1px solid var(--border); }
  .chat-layout { grid-template-columns: 1fr; height: auto; }
  .chat-sidebar { display: none; }
  .dashboard-header { flex-direction: column; gap: 12px; }
}
```

### Step 3: Add sidebar toggle logic in cases.js

Find:
```javascript
// ── Theme toggle ─────────────────────────────────────────────────────────────
```

Replace with:
```javascript
// ── Sidebar toggle (mobile) ──────────────────────────────────────────────────
const btnSidebarToggle = document.getElementById("btn-sidebar-toggle");
const sidebar = document.getElementById("sidebar");
if (btnSidebarToggle && sidebar) {
  btnSidebarToggle.addEventListener("click", () => sidebar.classList.toggle("sidebar-open"));
  // Close sidebar on case selection (mobile)
  sidebar.addEventListener("click", (e) => {
    if (e.target.closest(".case-item")) sidebar.classList.remove("sidebar-open");
  });
}

// ── Theme toggle ─────────────────────────────────────────────────────────────
```

### Step 4: Commit

```bash
git add static/style.css templates/index.html static/js/cases.js
git commit -m "feat(ui): responsive layout with mobile sidebar toggle"
```
