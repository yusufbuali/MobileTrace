import { api, apiFetch } from "./api.js";
import { initChat, triggerAnalysis, loadAnalysisResults, loadAnalysisPreview } from "./chat.js";
import { initConversations } from "./conversations.js";
import { showToast } from "./toast.js";

const caseList = document.getElementById("case-list");
const searchInput = document.getElementById("search-cases");
const filterStatus = document.getElementById("filter-status");
const btnNewCase = document.getElementById("btn-new-case");
const btnCancel = document.getElementById("btn-cancel-case");
const formNewCase = document.getElementById("form-new-case");
const btnAnalyze = document.getElementById("btn-analyze");
const btnReport = document.getElementById("btn-report");
const formUpload = document.getElementById("form-upload-evidence");
const formPath = document.getElementById("form-path-evidence");

let allCases = [];
let activeCaseId = null;

// ── Status badge ─────────────────────────────────────────────────────────────

function statusBadge(status) {
  return `<span class="status-badge status-${status}">${status.replace("_", " ")}</span>`;
}

// ── Case list ────────────────────────────────────────────────────────────────

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
        <div class="case-item ${c.id === activeCaseId ? "active" : ""}"
             data-id="${c.id}"
             role="button"
             aria-pressed="${c.id === activeCaseId ? "true" : "false"}"
             tabindex="0">
          <div class="case-title">${c.title}</div>
          <div class="case-meta">${c.officer || "&mdash;"}</div>
        </div>
      `).join("")}
    </details>
  `).join("");

  caseList.querySelectorAll(".case-item").forEach(el => {
    el.addEventListener("click", () => openCase(el.dataset.id));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openCase(el.dataset.id);
      }
    });
  });
}

async function loadCases() {
  const status = filterStatus.value;
  allCases = await api.getCases(status);
  filterCases();
}

function filterCases() {
  const q = searchInput.value.toLowerCase();
  const filtered = q
    ? allCases.filter(c => c.title.toLowerCase().includes(q) || (c.case_number || "").toLowerCase().includes(q))
    : allCases;
  renderCases(filtered);
}

// ── View switching ────────────────────────────────────────────────────────────

function showView(id) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById(id)?.classList.add("active");
}

// ── Tab switching ─────────────────────────────────────────────────────────────

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    btn.setAttribute("aria-selected", "true");
    const target = document.getElementById(btn.dataset.tab);
    if (target) target.classList.add("active");
    // Load analysis preview when switching to analysis tab
    if (btn.dataset.tab === "tab-analysis" && activeCaseId) {
      loadAnalysisPreview(activeCaseId);
    }
    // Load conversations when switching to conversations tab
    if (btn.dataset.tab === "tab-conversations") {
      initConversations(activeCaseId);
    }
  });
});

// ── Open a case ───────────────────────────────────────────────────────────────

async function openCase(id) {
  activeCaseId = id;
  renderCases(allCases);
  showView("view-case-dashboard");

  try {
    const c = await api.getCase(id);
    document.getElementById("dash-title").textContent = c.title;
    document.getElementById("dash-meta").innerHTML =
      `${c.case_number ? `<strong>${c.case_number}</strong> &middot; ` : ""}` +
      `${c.officer || ""} &middot; ${statusBadge(c.status)}`;

    // Device info
    const di = typeof c.device_info === "string" ? JSON.parse(c.device_info || "{}") : (c.device_info || {});
    const diEl = document.getElementById("dash-device-info");
    if (Object.keys(di).length) {
      diEl.innerHTML = `
        <div class="device-card">
          <div class="device-card-header">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12" y2="18.01"/></svg>
            <span>Device Identity</span>
          </div>
          <div class="device-grid">
            ${Object.entries(di).map(([k, v]) => `
              <div class="device-prop">
                <div class="device-prop-label">${k}</div>
                <div class="device-prop-value">${v}</div>
              </div>
            `).join("")}
          </div>
        </div>`;
    } else {
      diEl.innerHTML = '<p class="muted">No device info yet — upload evidence to populate.</p>';
    }

    // Stats
    _loadStats(id);
    // Evidence list
    _loadEvidence(id);
    // Report link
    if (btnReport) btnReport.href = `/api/cases/${id}/report`;
    // Chat
    initChat(id);
    // Refresh conversations if that tab is already active
    if (document.querySelector('.tab-btn[data-tab="tab-conversations"]')?.classList.contains("active")) {
      initConversations(id);
    }
  } catch (err) {
    document.getElementById("dash-title").textContent = "Error loading case";
  }
}

async function _loadStats(caseId) {
  const el = document.getElementById("dash-stats");
  if (!el) return;
  try {
    const [msgs, contacts, calls, analysis] = await Promise.all([
      apiFetch(`/api/cases/${caseId}/messages/count`).catch(() => ({ count: 0 })),
      apiFetch(`/api/cases/${caseId}/contacts/count`).catch(() => ({ count: 0 })),
      apiFetch(`/api/cases/${caseId}/calls/count`).catch(() => ({ count: 0 })),
      apiFetch(`/api/cases/${caseId}/analysis`).catch(() => []),
    ]);
    const stats = [
      { label: "Messages", value: msgs.count ?? msgs.length ?? 0, icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>', color: "blue" },
      { label: "Contacts", value: contacts.count ?? contacts.length ?? 0, icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>', color: "green" },
      { label: "Calls",    value: calls.count ?? calls.length ?? 0, icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>', color: "orange" },
      { label: "Analyses", value: Array.isArray(analysis) ? analysis.length : 0, icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>', color: "purple" },
    ];
    el.innerHTML = stats.map(s => `
      <div class="stat-card stat-card-${s.color}">
        <div class="stat-icon">${s.icon}</div>
        <div class="stat-value">${s.value}</div>
        <div class="stat-label">${s.label}</div>
      </div>`).join("");
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

async function _loadEvidence(caseId) {
  const el = document.getElementById("evidence-list");
  if (!el) return;
  try {
    const rows = await apiFetch(`/api/cases/${caseId}/evidence`);
    el.innerHTML = rows.length
      ? rows.map(e => `
          <div class="evidence-item">
            <div>
              ${_formatIcon(e.format)}
              <span class="ev-format">${e.format}</span>
              <span style="margin-left:8px">${e.source_path || "uploaded file"}</span>
            </div>
            <span class="ev-status-${e.parse_status === "done" ? "done" : "error"}">
              ${e.parse_status}
            </span>
          </div>`).join("")
      : '<p class="muted">No evidence uploaded yet.</p>';
  } catch (_) {
    el.innerHTML = '<p class="muted">Could not load evidence files.</p>';
  }
}

// ── Analyze button ────────────────────────────────────────────────────────────

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

// Mode toggle: Browser Upload ↔ Local Path
document.querySelectorAll(".ev-mode-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".ev-mode-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const mode = btn.dataset.mode;
    document.querySelectorAll(".ev-panel").forEach(p => {
      p.style.display = p.dataset.panel === mode ? "" : "none";
    });
  });
});

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

if (formPath) {
  formPath.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeCaseId) return;
    const statusEl = document.getElementById("ev-path-status");
    const fd = new FormData(formPath);
    const path = fd.get("source_path")?.trim();
    const signal_key = fd.get("signal_key")?.trim() || "";
    if (!path) return;
    if (statusEl) statusEl.textContent = "Parsing…";
    try {
      const res = await fetch(`/api/cases/${activeCaseId}/evidence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_path: path, signal_key }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed");
      formPath.reset();
      if (statusEl) statusEl.textContent = "";
      showToast(`Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`, "success");
      _loadEvidence(activeCaseId);
      openCase(activeCaseId);
    } catch (err) {
      if (statusEl) statusEl.textContent = "";
      showToast(`Parse error: ${err.message}`, "error");
    }
  });
}

// ── Folder scan ───────────────────────────────────────────────────────────────

const formFolderScan = document.getElementById("form-folder-scan");
const folderResults = document.getElementById("folder-scan-results");
const folderResultsList = document.getElementById("fs-results-list");
let _lastScanPath = "";
let _lastScanData = null;

function _fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

if (formFolderScan) {
  formFolderScan.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeCaseId) return;
    const statusEl = document.getElementById("folder-scan-status");
    const pathInput = document.getElementById("folder-scan-path");
    const folder = pathInput?.value.trim();
    if (!folder) return;
    if (statusEl) statusEl.textContent = "Scanning…";
    if (folderResults) folderResults.style.display = "none";

    try {
      const res = await fetch(`/api/cases/${activeCaseId}/evidence/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder_path: folder }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Scan failed");
      if (statusEl) statusEl.textContent = "";
      _lastScanPath = folder;
      _lastScanData = data;
      _renderScanResults(data);
    } catch (err) {
      if (statusEl) statusEl.textContent = "";
      showToast(`Scan error: ${err.message}`, "error");
    }
  });
}

function _renderScanResults(data) {
  if (!folderResultsList || !folderResults) return;
  folderResultsList.innerHTML = "";

  const total = (data.archives?.length || 0)
    + Object.values(data.platforms || {}).reduce((s, p) => s + (p.databases?.length || 0), 0);

  if (total === 0) {
    folderResultsList.innerHTML = '<p class="muted" style="padding:8px">No importable files found in this folder.</p>';
    folderResults.style.display = "";
    return;
  }

  // ── Archives ──
  if (data.archives?.length) {
    const hdr = document.createElement("div");
    hdr.className = "fs-platform-header";
    hdr.textContent = `Archive Files (${data.archives.length})`;
    folderResultsList.appendChild(hdr);

    data.archives.forEach(a => {
      const item = document.createElement("label");
      item.className = "fs-item selected";
      item.dataset.type = "archive";
      item.dataset.path = a.path;
      item.innerHTML = `
        <input type="checkbox" checked data-type="archive" data-path="${a.path}" />
        <div class="fs-item-info">
          <span class="fs-item-label">${a.name}</span>
          <span><span class="fs-item-meta">${a.format.toUpperCase()}</span> <span class="fs-item-size">${_fmtSize(a.size)}</span></span>
        </div>`;
      item.querySelector("input").addEventListener("change", _onFsCheckChange);
      folderResultsList.appendChild(item);
    });
  }

  // ── Platform databases ──
  for (const [platform, info] of Object.entries(data.platforms || {})) {
    if (!info.databases?.length) continue;
    const hdr = document.createElement("div");
    hdr.className = "fs-platform-header";
    hdr.textContent = `${platform === "android" ? "Android" : "iOS"} Databases (${info.databases.length})`;
    folderResultsList.appendChild(hdr);

    // Platform-level checkbox
    const platItem = document.createElement("label");
    platItem.className = "fs-item selected";
    platItem.dataset.type = "platform";
    platItem.dataset.platform = platform;
    platItem.innerHTML = `
      <input type="checkbox" checked data-type="platform" data-platform="${platform}" />
      <div class="fs-item-info">
        <span class="fs-item-label">Import all ${platform === "android" ? "Android" : "iOS"} databases</span>
        <span class="fs-item-meta">${info.databases.map(d => d.label).join(", ")}</span>
      </div>`;
    platItem.querySelector("input").addEventListener("change", _onFsCheckChange);
    folderResultsList.appendChild(platItem);

    // Individual DB items (informational, dimmed)
    info.databases.forEach(db => {
      const sub = document.createElement("div");
      sub.className = "fs-item";
      sub.style.paddingLeft = "36px";
      sub.style.opacity = "0.7";
      sub.style.cursor = "default";
      sub.innerHTML = `
        <div class="fs-item-info">
          <span class="fs-item-label">${db.label}</span>
          <span class="fs-item-size">${_fmtSize(db.size)}</span>
        </div>`;
      folderResultsList.appendChild(sub);
    });
  }

  folderResults.style.display = "";
  _updateFsSelectionCount();

  // Toggle all button
  const toggleBtn = document.getElementById("fs-toggle-all");
  if (toggleBtn) {
    toggleBtn.onclick = () => {
      const cbs = folderResultsList.querySelectorAll("input[type=checkbox]");
      const allChecked = [...cbs].every(c => c.checked);
      cbs.forEach(cb => {
        cb.checked = !allChecked;
        const label = cb.closest(".fs-item");
        if (label) label.classList.toggle("selected", cb.checked);
      });
      toggleBtn.textContent = allChecked ? "Select All" : "Deselect All";
      _updateFsSelectionCount();
    };
  }

  // Import button
  const importBtn = document.getElementById("fs-import-btn");
  if (importBtn) {
    importBtn.onclick = () => _importSelected();
  }
}

function _onFsCheckChange(e) {
  const label = e.target.closest(".fs-item");
  if (label) label.classList.toggle("selected", e.target.checked);
  _updateFsSelectionCount();
}

function _updateFsSelectionCount() {
  const cbs = folderResultsList?.querySelectorAll("input[type=checkbox]") || [];
  const checked = [...cbs].filter(c => c.checked).length;
  const countEl = document.getElementById("fs-selection-count");
  const importBtn = document.getElementById("fs-import-btn");
  if (countEl) countEl.textContent = `${checked} of ${cbs.length} selected`;
  if (importBtn) importBtn.disabled = checked === 0;
}

async function _importSelected() {
  if (!activeCaseId || !_lastScanPath) return;
  const cbs = folderResultsList?.querySelectorAll("input[type=checkbox]:checked") || [];
  const archives = [];
  const platforms = [];
  cbs.forEach(cb => {
    if (cb.dataset.type === "archive") archives.push(cb.dataset.path);
    if (cb.dataset.type === "platform") platforms.push(cb.dataset.platform);
  });
  if (!archives.length && !platforms.length) return;

  const importBtn = document.getElementById("fs-import-btn");
  if (importBtn) { importBtn.disabled = true; importBtn.textContent = "Importing…"; }
  const signalKey = document.getElementById("folder-signal-key")?.value.trim() || "";

  try {
    const res = await fetch(`/api/cases/${activeCaseId}/evidence/import-folder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        folder_path: _lastScanPath,
        archives,
        platforms,
        signal_key: signalKey,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Import failed");

    const totalMsgs = data.imported.reduce((s, i) => s + (i.stats?.messages || 0), 0);
    const totalContacts = data.imported.reduce((s, i) => s + (i.stats?.contacts || 0), 0);
    showToast(`Imported ${data.imported.length} source(s) — ${totalMsgs} msgs, ${totalContacts} contacts`, "success");

    if (data.errors?.length) {
      data.errors.forEach(e => showToast(`Error: ${e.error}`, "error"));
    }

    // Show warnings
    data.imported.forEach(i => {
      (i.warnings || []).forEach(w => showToast(w, "warning"));
    });

    _loadEvidence(activeCaseId);
    openCase(activeCaseId);
    if (folderResults) folderResults.style.display = "none";
  } catch (err) {
    showToast(`Import error: ${err.message}`, "error");
  } finally {
    if (importBtn) { importBtn.disabled = false; importBtn.textContent = "Import Selected"; }
  }
}

// ── New case form ─────────────────────────────────────────────────────────────

btnNewCase?.addEventListener("click", () => showView("view-new-case"));
btnCancel?.addEventListener("click", () => showView("view-welcome"));
searchInput?.addEventListener("input", filterCases);
filterStatus?.addEventListener("change", loadCases);

formNewCase?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(formNewCase);
  const body = { title: fd.get("title"), officer: fd.get("officer"), case_number: fd.get("case_number") };
  try {
    const c = await api.createCase(body);
    allCases.unshift(c);
    activeCaseId = c.id;
    filterCases();
    showView("view-case-dashboard");
    openCase(c.id);
    formNewCase.reset();
  } catch (err) {
    showToast("Failed to create case: " + err.message, "error");
  }
});

// ── Sidebar toggle (mobile) ──────────────────────────────────────────────────
const btnSidebarToggle = document.getElementById("btn-sidebar-toggle");
const sidebar = document.getElementById("sidebar");
if (btnSidebarToggle && sidebar) {
  btnSidebarToggle.addEventListener("click", () => sidebar.classList.toggle("sidebar-open"));
  sidebar.addEventListener("click", (e) => {
    if (e.target.closest(".case-item")) sidebar.classList.remove("sidebar-open");
  });
}

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
showView("view-welcome");
