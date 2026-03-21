/**
 * ioc.js — Intelligence tab: IOC extraction results renderer.
 * Exports initIoc(caseId) called by cases.js on tab switch.
 */

const _TYPE_LABELS = {
  phone: "Phone",
  email: "Email",
  url: "URL",
  crypto: "Crypto",
  ip: "IP Address",
  coords: "Coordinates",
};

const _TYPE_COLORS = {
  phone:  "var(--success)",
  email:  "var(--info)",
  url:    "var(--accent)",
  crypto: "#f59e0b",
  ip:     "#a78bfa",
  coords: "#34d399",
};

let _allIocs = [];
let _activeFilter = "all";
let _caseId = null;

function dom(id) { return document.getElementById(id); }

function _esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Public entry point ───────────────────────────────────────────────────────

export async function initIoc(caseId) {
  if (!caseId) return;
  _caseId = caseId;
  _activeFilter = "all";

  const wrap = dom("ioc-table-wrap");
  wrap.innerHTML = '<div class="ioc-loading">Scanning evidence\u2026</div>';
  dom("ioc-summary-bar").innerHTML = "";
  dom("ioc-filter-pills").innerHTML = "";
  dom("btn-ioc-export-csv").style.display = "none";

  try {
    const res = await fetch(`/api/cases/${caseId}/ioc`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _allIocs = data.iocs || [];
    _renderSummary(data.summary || {});
    _renderFilterPills(data.summary?.by_type || {});
    _renderTable(_allIocs);
    if (_allIocs.length) dom("btn-ioc-export-csv").style.display = "";
  } catch (err) {
    wrap.innerHTML = `<div class="ioc-empty-state">Failed to load IOCs: ${_esc(err.message)}</div>`;
  }
}

// ── Summary bar ──────────────────────────────────────────────────────────────

function _renderSummary(summary) {
  const bar = dom("ioc-summary-bar");
  if (!summary.total) {
    bar.innerHTML = '<span class="ioc-summary-chip">No indicators found in this case.</span>';
    return;
  }
  const chips = Object.entries(summary.by_type || {}).map(([type, count]) => {
    const label = _TYPE_LABELS[type] || type;
    const color = _TYPE_COLORS[type] || "var(--muted)";
    return `<span class="ioc-summary-chip" style="border-color:${color};color:${color}">${label} <strong>${count}</strong></span>`;
  });
  bar.innerHTML = `<span class="ioc-total-chip">Total <strong>${summary.total}</strong></span> ` + chips.join(" ");
}

// ── Filter pills ─────────────────────────────────────────────────────────────

function _renderFilterPills(byType) {
  const wrap = dom("ioc-filter-pills");
  const types = ["all", ...Object.keys(byType)];
  wrap.innerHTML = types.map(t => {
    const label = t === "all" ? "All" : (_TYPE_LABELS[t] || t);
    const active = t === _activeFilter ? " active" : "";
    return `<button class="ioc-filter-pill${active}" data-type="${_esc(t)}">${_esc(label)}</button>`;
  }).join("");

  wrap.querySelectorAll(".ioc-filter-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      _activeFilter = btn.dataset.type;
      wrap.querySelectorAll(".ioc-filter-pill").forEach(b =>
        b.classList.toggle("active", b.dataset.type === _activeFilter));
      const filtered = _activeFilter === "all"
        ? _allIocs
        : _allIocs.filter(i => i.type === _activeFilter);
      _renderTable(filtered);
    });
  });
}

// ── Table ────────────────────────────────────────────────────────────────────

function _renderTable(iocs) {
  const wrap = dom("ioc-table-wrap");
  if (!iocs.length) {
    wrap.innerHTML = '<div class="ioc-empty-state">No indicators match the current filter.</div>';
    return;
  }

  const rows = iocs.map((ioc, idx) => {
    const color = _TYPE_COLORS[ioc.type] || "var(--muted)";
    const typeBadge = `<span class="ioc-type-badge" style="background:${color}20;color:${color};border-color:${color}40">${_esc(_TYPE_LABELS[ioc.type] || ioc.type)}</span>`;
    const srcCount = ioc.sources?.length || 0;
    const hasMore = ioc.occurrences > srcCount;
    const srcLabel = hasMore
      ? `${ioc.occurrences} (showing ${srcCount})`
      : ioc.occurrences;

    const firstThread = ioc.sources?.[0]?.thread_id || "";
    const firstPlatform = ioc.sources?.[0]?.platform || "";
    const jumpBtn = firstThread
      ? `<button class="ioc-jump-btn" data-thread="${_esc(firstThread)}" data-platform="${_esc(firstPlatform)}" title="Jump to conversation">&#8599;</button>`
      : "";

    return `
      <tr class="ioc-row" data-idx="${idx}">
        <td class="ioc-val-cell"><span class="ioc-value">${_esc(ioc.value)}</span></td>
        <td>${typeBadge}</td>
        <td class="ioc-num">${srcLabel}</td>
        <td class="ioc-ts">${(ioc.first_seen || "").slice(0, 10)}</td>
        <td class="ioc-ts">${(ioc.last_seen || "").slice(0, 10)}</td>
        <td class="ioc-actions">
          <button class="ioc-copy-btn" data-value="${_esc(ioc.value)}" title="Copy">&#128203;</button>
          ${jumpBtn}
          ${srcCount ? `<button class="ioc-src-btn" data-idx="${idx}" title="Show sources">&#128270; Sources</button>` : ""}
        </td>
      </tr>
      <tr class="ioc-src-row" id="ioc-src-${idx}" style="display:none">
        <td colspan="6">${_renderSources(ioc.sources || [])}</td>
      </tr>`;
  }).join("");

  wrap.innerHTML = `
    <table class="ioc-table">
      <thead>
        <tr>
          <th>Value</th><th>Type</th><th>Occurrences</th>
          <th>First Seen</th><th>Last Seen</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;

  // Wire copy buttons
  wrap.querySelectorAll(".ioc-copy-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(btn.dataset.value).then(() => {
        btn.textContent = "\u2713";
        setTimeout(() => { btn.innerHTML = "&#128203;"; }, 1200);
      });
    });
  });

  // Wire jump buttons
  wrap.querySelectorAll(".ioc-jump-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("mt:jump-to-thread", {
        detail: { platform: btn.dataset.platform, thread: btn.dataset.thread }
      }));
    });
  });

  // Wire source toggle buttons
  wrap.querySelectorAll(".ioc-src-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const srcRow = dom(`ioc-src-${btn.dataset.idx}`);
      const open = srcRow.style.display !== "none";
      srcRow.style.display = open ? "none" : "";
      btn.innerHTML = open ? "&#128270; Sources" : "&#9650; Sources";
    });
  });

  // Wire CSV export button
  dom("btn-ioc-export-csv").onclick = () => _exportCsv(iocs);
}

function _renderSources(sources) {
  if (!sources.length) return "";
  const rows = sources.map(s => `
    <div class="ioc-source-item">
      <span class="ioc-src-badge ioc-src-${_esc(s.platform)}">${_esc(s.platform)}</span>
      <span class="ioc-src-ts">${(s.timestamp || "").slice(0, 16)}</span>
      <span class="ioc-src-snippet">${_esc(s.snippet)}</span>
    </div>`).join("");
  return `<div class="ioc-sources-panel">${rows}</div>`;
}

// ── CSV export ────────────────────────────────────────────────────────────────

function _exportCsv(iocs) {
  const header = "Type,Value,Occurrences,First Seen,Last Seen,Platform,Thread\n";
  const rows = iocs.flatMap(ioc => {
    if (!ioc.sources?.length) {
      return [`${ioc.type},${ioc.value},${ioc.occurrences},${ioc.first_seen},${ioc.last_seen},,`];
    }
    return ioc.sources.map(s =>
      [ioc.type, ioc.value, ioc.occurrences, ioc.first_seen, ioc.last_seen, s.platform, s.thread_id]
        .map(v => `"${String(v ?? "").replace(/"/g, '""')}"`)
        .join(",")
    );
  });
  const blob = new Blob([header + rows.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `ioc-case-${_caseId}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}
