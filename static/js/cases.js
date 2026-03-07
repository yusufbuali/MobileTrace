import { api, apiFetch } from "./api.js";
import { initChat, triggerAnalysis, loadAnalysisResults } from "./chat.js";
import { initConversations } from "./conversations.js";

const caseList = document.getElementById("case-list");
const searchInput = document.getElementById("search-cases");
const filterStatus = document.getElementById("filter-status");
const btnNewCase = document.getElementById("btn-new-case");
const btnCancel = document.getElementById("btn-cancel-case");
const formNewCase = document.getElementById("form-new-case");
const btnAnalyze = document.getElementById("btn-analyze");
const btnReport = document.getElementById("btn-report");
const formUpload = document.getElementById("form-upload-evidence");

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

async function _loadEvidence(caseId) {
  const el = document.getElementById("evidence-list");
  if (!el) return;
  try {
    const rows = await apiFetch(`/api/cases/${caseId}/evidence`);
    el.innerHTML = rows.length
      ? rows.map(e => `
          <div class="evidence-item">
            <div>
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

// ── Evidence upload ───────────────────────────────────────────────────────────

if (formUpload) {
  formUpload.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeCaseId) return;
    const fd = new FormData(formUpload);
    try {
      await fetch(`/api/cases/${activeCaseId}/evidence`, { method: "POST", body: fd });
      formUpload.reset();
      _loadEvidence(activeCaseId);
      openCase(activeCaseId); // refresh stats
    } catch (err) {
      alert("Upload failed: " + err.message);
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
