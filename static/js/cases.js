import { api, apiFetch } from "./api.js";
import { initChat, triggerAnalysis, loadAnalysisResults } from "./chat.js";
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
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    const target = document.getElementById(btn.dataset.tab);
    if (target) target.classList.add("active");
    // Lazy-load analysis results when switching to analysis tab
    if (btn.dataset.tab === "tab-analysis" && activeCaseId) {
      loadAnalysisResults(activeCaseId);
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
      diEl.innerHTML = "<dl>" + Object.entries(di).map(([k, v]) =>
        `<dt>${k}</dt><dd>${v}</dd>`).join("") + "</dl>";
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
  } catch (_) { /* stats not critical */ }
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
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    document.querySelector('[data-tab="tab-analysis"]')?.classList.add("active");
    document.getElementById("tab-analysis")?.classList.add("active");
    await triggerAnalysis(activeCaseId);
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
      if (statusEl) statusEl.textContent = `Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`;
      _loadEvidence(activeCaseId);
      openCase(activeCaseId);
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    }
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
      if (statusEl) statusEl.textContent = `Parsed — ${data.stats?.messages ?? 0} msgs, ${data.stats?.contacts ?? 0} contacts`;
      _loadEvidence(activeCaseId);
      openCase(activeCaseId);
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    }
  });
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
    alert("Failed to create case: " + err.message);
  }
});

// ── Boot ──────────────────────────────────────────────────────────────────────
loadCases();
showView("view-welcome");
