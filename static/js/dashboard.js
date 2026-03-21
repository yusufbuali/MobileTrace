import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";

/* global Chart */

let _chartRisk = null, _chartStatus = null, _chartCrimes = null;
let _sortCol = "created_at", _sortDir = "desc", _tableData = [];
let _onCaseClick = null;

const _RISK_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NOT_ANALYZED"];

export async function initDashboard(onCaseClick) {
  _onCaseClick = onCaseClick;
  try {
    const stats = await apiFetch("/api/dashboard/stats");
    _renderKPIs(stats.kpis);
    _renderRiskChart(stats.risk_distribution);
    _renderStatusChart(stats.status_pipeline);
    _renderCrimesChart(stats.crime_categories || []);
    _renderActivityFeed(stats.recent_activity || []);
    _tableData = stats.cases_table || [];
    _renderCasesTable(_tableData, onCaseClick);
    _wireTableHeaders(onCaseClick);
  } catch (err) {
    showToast("Failed to load dashboard: " + err.message, "error");
  }
}

// ── KPI cards ─────────────────────────────────────────────────────────────────
function _renderKPIs(kpis) {
  const el = document.getElementById("gdb-kpis");
  if (!el) return;
  const cards = [
    { label: "Total Cases",           value: kpis.total_cases,            color: "blue" },
    { label: "High-Risk Cases",        value: kpis.high_risk_cases,         color: "red" },
    { label: "Crime Indicators",       value: kpis.crime_indicators_found,  color: "orange" },
    { label: "Total Artifacts",        value: kpis.total_artifacts,         color: "green" },
  ];
  el.innerHTML = cards.map(c => `
    <div class="stat-card stat-card-${c.color}">
      <div class="stat-value">${c.value.toLocaleString()}</div>
      <div class="stat-label">${c.label}</div>
    </div>`).join("");
}

// ── Risk doughnut chart ───────────────────────────────────────────────────────
function _renderRiskChart(dist) {
  const canvas = document.getElementById("chart-risk");
  if (!canvas || !window.Chart) return;
  if (_chartRisk) { _chartRisk.destroy(); _chartRisk = null; }

  const labels = _RISK_ORDER;
  const data   = labels.map(l => dist[l] || 0);
  const colors = ["#f85149", "#f97316", "#d29922", "#3fb950", "#8b949e"];

  _chartRisk = new Chart(canvas, {
    type: "doughnut",
    data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 1, borderColor: _getCSSVar("--surface") }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "65%",
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: _getCSSVar("--text-muted"), font: { size: 10 }, boxWidth: 10, padding: 8 },
        },
      },
    },
  });
}

// ── Status pipeline bar chart ─────────────────────────────────────────────────
function _renderStatusChart(pipeline) {
  const canvas = document.getElementById("chart-status");
  if (!canvas || !window.Chart) return;
  if (_chartStatus) { _chartStatus.destroy(); _chartStatus = null; }

  const labels = ["Open", "In Review", "On Hold", "Closed"];
  const keys   = ["open", "in_review", "on_hold", "closed"];
  const data   = keys.map(k => pipeline[k] || 0);
  const colors = ["#58a6ff", "#f97316", "#d29922", "#8b949e"];
  const gridColor = _getCSSVar("--border");
  const textColor = _getCSSVar("--text-muted");

  _chartStatus = new Chart(canvas, {
    type: "bar",
    data: { labels, datasets: [{ data, backgroundColor: colors, borderRadius: 4, borderSkipped: false }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: textColor, font: { size: 10 } }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, font: { size: 10 } }, grid: { display: false } },
      },
    },
  });
}

// ── Crime categories bar chart ────────────────────────────────────────────────
function _renderCrimesChart(cats) {
  const card = document.querySelector(".gdb-chart-card--wide");
  const canvas = document.getElementById("chart-crimes");
  if (!card || !canvas || !window.Chart) return;

  if (!cats.length) {
    if (_chartCrimes) { _chartCrimes.destroy(); _chartCrimes = null; }
    canvas.style.display = "none";
    if (!card.querySelector(".gdb-chart-empty")) {
      const el = document.createElement("div");
      el.className = "gdb-chart-empty";
      el.textContent = "No analysis data yet";
      card.appendChild(el);
    }
    return;
  }

  // Remove any previous empty-state element
  card.querySelector(".gdb-chart-empty")?.remove();
  canvas.style.display = "";

  if (_chartCrimes) { _chartCrimes.destroy(); _chartCrimes = null; }

  const top = cats.slice(0, 12);
  const labels = top.map(c => c.category.replace(/_/g, " "));
  const data   = top.map(c => c.count);
  const gridColor = _getCSSVar("--border");
  const textColor = _getCSSVar("--text-muted");
  const accent    = _getCSSVar("--accent") || "#58a6ff";

  _chartCrimes = new Chart(canvas, {
    type: "bar",
    data: { labels, datasets: [{ data, backgroundColor: accent + "cc", borderRadius: 3, borderSkipped: false }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: textColor, font: { size: 10 } }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, font: { size: 10 } }, grid: { display: false } },
      },
    },
  });
}

// ── Activity feed ─────────────────────────────────────────────────────────────
function _renderActivityFeed(acts) {
  const el = document.getElementById("gdb-activity-feed");
  if (!el) return;
  if (!acts.length) {
    el.innerHTML = `<div class="gdb-activity-item">No recent activity</div>`;
    return;
  }

  const typeClass = { evidence_imported: "evidence", analysis_completed: "analysis", case_created: "case" };
  const typeLabel = { evidence_imported: "Evidence imported", analysis_completed: "Analysis completed", case_created: "Case created" };

  el.innerHTML = acts.map(a => {
    const cls  = typeClass[a.type] || "case";
    const lbl  = typeLabel[a.type] || a.type;
    const det  = a.detail ? ` — ${a.detail}` : "";
    return `<div class="gdb-activity-item gdb-activity-item--${cls}">
      <span class="gdb-activity-case">${_esc(a.case_title)}</span>
      <span class="gdb-activity-detail"> · ${lbl}${_esc(det)}</span>
      <span class="gdb-activity-time">${_formatRelativeTime(a.timestamp)}</span>
    </div>`;
  }).join("");
}

// ── Cases table ───────────────────────────────────────────────────────────────
function _renderCasesTable(cases, onCaseClick) {
  const tbody = document.getElementById("gdb-cases-tbody");
  if (!tbody) return;

  if (!cases.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px">No cases yet — create your first case</td></tr>`;
    return;
  }

  tbody.innerHTML = cases.map(c => `
    <tr data-case-id="${_esc(c.id)}">
      <td>
        <div class="gdb-case-title">${_esc(c.title)}</div>
        ${c.case_number ? `<div class="gdb-case-number">${_esc(c.case_number)}</div>` : ""}
      </td>
      <td>${_esc(c.officer || "—")}</td>
      <td>${_statusBadge(c.status)}</td>
      <td><span class="gdb-risk-badge risk-${_esc(c.risk_level)}">${_esc(c.risk_level)}</span></td>
      <td>${c.artifact_count.toLocaleString()}</td>
      <td>${c.created_at ? c.created_at.slice(0, 10) : "—"}</td>
    </tr>`).join("");

  tbody.querySelectorAll("tr[data-case-id]").forEach(tr => {
    tr.addEventListener("click", () => {
      const id = tr.getAttribute("data-case-id");
      if (id && typeof onCaseClick === "function") onCaseClick(id);
    });
  });
}

function _wireTableHeaders(onCaseClick) {
  const table = document.getElementById("gdb-cases-table");
  if (!table) return;
  table.querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.getAttribute("data-sort");
      if (_sortCol === col) {
        _sortDir = _sortDir === "asc" ? "desc" : "asc";
      } else {
        _sortCol = col;
        _sortDir = "asc";
      }
      _applySort(onCaseClick);
      // Update header indicators
      table.querySelectorAll("th[data-sort]").forEach(t => {
        t.classList.remove("sort-asc", "sort-desc");
      });
      th.classList.add(_sortDir === "asc" ? "sort-asc" : "sort-desc");
    });
  });
}

function _applySort(onCaseClick) {
  const col = _sortCol;
  const dir = _sortDir === "asc" ? 1 : -1;
  const sorted = [..._tableData].sort((a, b) => {
    const av = a[col] ?? "";
    const bv = b[col] ?? "";
    if (typeof av === "number") return dir * (av - bv);
    return dir * String(av).localeCompare(String(bv));
  });
  _renderCasesTable(sorted, onCaseClick);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function _getCSSVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function _esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function _statusBadge(status) {
  const map = {
    open: "badge-open",
    in_review: "badge-in-review",
    on_hold: "badge-on-hold",
    closed: "badge-closed",
  };
  const cls = map[status] || "";
  return `<span class="status-badge ${cls}">${_esc(status || "open")}</span>`;
}

function _formatRelativeTime(iso) {
  if (!iso) return "";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const s = Math.floor(diff / 1000);
    if (s < 60)  return "just now";
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
    return iso.slice(0, 10);
  } catch {
    return iso.slice(0, 10);
  }
}
