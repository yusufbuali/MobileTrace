/* global d3 */
import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";

let _data = null;
let _simulation = null;
let _activeFilters = { platforms: new Set(), risks: new Set() };
let _selectedNode = null;
let _svg = null;
let _zoomBehavior = null;
let _nodeSel = null;
let _linkSel = null;
let _simNodes = null;

export async function initCorrelation(caseId) {
  const statsBar = document.getElementById("corr-stats-bar");
  if (!statsBar) return;

  // Reset state
  _activeFilters = { platforms: new Set(), risks: new Set() };
  _selectedNode = null;
  if (_simulation) { _simulation.stop(); _simulation = null; }
  _svg = null; _nodeSel = null; _linkSel = null; _simNodes = null;

  // Reset filters UI
  const pfEl = document.getElementById("corr-platform-filters");
  const rkEl = document.getElementById("corr-risk-filters");
  if (pfEl) pfEl.innerHTML = "";
  if (rkEl) rkEl.innerHTML = "";

  try {
    _data = await apiFetch(`/api/cases/${caseId}/correlation`);
  } catch (err) {
    showToast("Failed to load correlation data: " + err.message, "error");
    return;
  }

  _renderStatsBar(_data.stats);
  _renderFilters(_data);

  const emptyEl = document.getElementById("corr-graph-empty");
  if (!_data.nodes || _data.nodes.length <= 1) {
    if (emptyEl) emptyEl.style.display = "flex";
    _clearInspector();
    _renderHeatmaps(_data.heatmap || { by_hour: [], by_weekday: [] });
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";

  _renderGraph(_data.nodes, _data.links);
  _renderHeatmaps(_data.heatmap);
  _clearInspector();

  const resetBtn = document.getElementById("corr-reset-zoom");
  if (resetBtn) {
    resetBtn.onclick = () => {
      if (_svg && _zoomBehavior) {
        _svg.transition().duration(500).call(_zoomBehavior.transform, d3.zoomIdentity);
      }
    };
  }
}

// ── Stats bar ─────────────────────────────────────────────────────────────────

function _renderStatsBar(stats) {
  const el = document.getElementById("corr-stats-bar");
  if (!el || !stats) return;
  const chips = [
    { label: "Total Contacts",      value: stats.total_contacts,      cls: "" },
    { label: "High-Risk",           value: stats.high_risk_contacts,   cls: stats.high_risk_contacts > 0 ? "risk-high" : "" },
    { label: "Cross-Platform",      value: stats.cross_platform_contacts, cls: "" },
    { label: "Total Interactions",  value: stats.total_interactions,   cls: "" },
  ];
  el.innerHTML = chips.map(c => `
    <div class="corr-stat-chip ${c.cls}">
      <div class="corr-stat-value">${c.value ?? 0}</div>
      <div class="corr-stat-label">${c.label}</div>
    </div>
  `).join("");
}

// ── Platform + Risk filters ───────────────────────────────────────────────────

function _renderFilters(data) {
  const platforms = new Set();
  const risks = new Set();
  (data.nodes || []).forEach(n => {
    (n.platforms || []).forEach(p => platforms.add(p));
    if (n.risk_level && n.risk_level !== "NONE") risks.add(n.risk_level);
  });

  const pfEl = document.getElementById("corr-platform-filters");
  if (pfEl) {
    const sorted = [...platforms].sort();
    pfEl.innerHTML = sorted.length
      ? sorted.map(p => `<button class="corr-pill" data-platform="${p}">${_platformIcon(p)} ${p}</button>`).join("")
      : `<span style="color:var(--text-muted);font-size:0.75rem">—</span>`;
    pfEl.querySelectorAll(".corr-pill").forEach(btn => {
      btn.addEventListener("click", () => {
        const p = btn.dataset.platform;
        _activeFilters.platforms.has(p) ? _activeFilters.platforms.delete(p) : _activeFilters.platforms.add(p);
        btn.classList.toggle("active", _activeFilters.platforms.has(p));
        _applyFilters();
      });
    });
  }

  const riskOrder = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
  const rkEl = document.getElementById("corr-risk-filters");
  if (rkEl) {
    const filtered = riskOrder.filter(r => risks.has(r));
    rkEl.innerHTML = filtered.length
      ? filtered.map(r => `<button class="corr-pill" data-risk="${r}">${r}</button>`).join("")
      : `<span style="color:var(--text-muted);font-size:0.75rem">—</span>`;
    rkEl.querySelectorAll(".corr-pill").forEach(btn => {
      btn.addEventListener("click", () => {
        const r = btn.dataset.risk;
        _activeFilters.risks.has(r) ? _activeFilters.risks.delete(r) : _activeFilters.risks.add(r);
        btn.classList.toggle("active", _activeFilters.risks.has(r));
        _applyFilters();
      });
    });
  }
}

// ── D3 Force Graph ────────────────────────────────────────────────────────────

function _nodeRadius(node) {
  if (node.is_device_owner) return 18;
  return Math.max(8, Math.min(28, 8 + Math.sqrt(node.msg_count + node.call_count * 2)));
}

function _riskColor(level) {
  const map = { CRITICAL: "#f85149", HIGH: "#f97316", MEDIUM: "#d29922", LOW: "#3fb950", NONE: "#8b949e" };
  return map[level] || map.NONE;
}

function _platformIcon(platform) {
  const icons = { sms: "📱", whatsapp: "💬", telegram: "✈️", signal: "🔒", phone: "📞", imessage: "💬", email: "📧" };
  return icons[(platform || "").toLowerCase()] || "💬";
}

function _renderGraph(nodes, links) {
  const wrap = document.querySelector(".corr-graph-wrap");
  const svgEl = document.getElementById("corr-graph");
  if (!wrap || !svgEl) return;

  const width  = wrap.clientWidth  || 700;
  const height = wrap.clientHeight || 500;

  svgEl.setAttribute("width",  width);
  svgEl.setAttribute("height", height);
  while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);

  _svg = d3.select(svgEl);

  // Tooltip
  let tooltip = wrap.querySelector(".corr-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "corr-tooltip";
    wrap.appendChild(tooltip);
  }

  // Zoom layer
  const g = _svg.append("g");
  _zoomBehavior = d3.zoom()
    .scaleExtent([0.15, 5])
    .on("zoom", (event) => g.attr("transform", event.transform));
  _svg.call(_zoomBehavior);

  // Clone data for simulation
  _simNodes = nodes.map(n => ({ ...n }));
  const nodeById = Object.fromEntries(_simNodes.map(n => [n.id, n]));
  const simLinks = links.map(l => ({
    ...l,
    source: nodeById[l.source] ?? l.source,
    target: nodeById[l.target] ?? l.target,
  }));

  // Links
  _linkSel = g.append("g").attr("class", "corr-links")
    .selectAll("line")
    .data(simLinks)
    .enter()
    .append("line")
    .attr("class", "corr-link")
    .attr("stroke", d => _riskColor(d.risk_level))
    .attr("stroke-width", d => Math.max(1, Math.sqrt(d.weight)));

  // Node groups with drag
  _nodeSel = g.append("g").attr("class", "corr-nodes")
    .selectAll("g")
    .data(_simNodes)
    .enter()
    .append("g")
    .attr("class", "corr-node-group")
    .call(
      d3.drag()
        .on("start", (event, d) => {
          if (!event.active) _simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => {
          if (!event.active) _simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
    );

  _nodeSel.append("circle")
    .attr("class", "corr-node")
    .attr("r", d => _nodeRadius(d))
    .attr("fill", d => d.is_device_owner ? "var(--accent)" : _riskColor(d.risk_level))
    .on("mouseenter", (event, d) => {
      const plat = (d.platforms || []).map(_platformIcon).join(" ");
      tooltip.innerHTML = `<strong>${_esc(d.label || d.id)}</strong><br>
        Msgs: ${d.msg_count} &middot; Calls: ${d.call_count}<br>
        ${plat} &middot; Risk: ${d.risk_level}`;
      tooltip.style.display = "block";
      tooltip.style.left = (event.offsetX + 14) + "px";
      tooltip.style.top  = (event.offsetY - 10) + "px";
    })
    .on("mousemove", (event) => {
      tooltip.style.left = (event.offsetX + 14) + "px";
      tooltip.style.top  = (event.offsetY - 10) + "px";
    })
    .on("mouseleave", () => { tooltip.style.display = "none"; })
    .on("click", (event, d) => {
      event.stopPropagation();
      _selectedNode = d.id;
      _nodeSel.select("circle").classed("selected", nd => nd.id === d.id);
      _showInspector(d);
    });

  // Labels for top contacts + DEVICE
  const sorted = [..._simNodes].sort((a, b) =>
    (b.msg_count + b.call_count * 2) - (a.msg_count + a.call_count * 2)
  );
  const topIds = new Set(sorted.slice(0, Math.min(12, sorted.length)).map(n => n.id));
  topIds.add("DEVICE");

  _nodeSel.filter(d => topIds.has(d.id))
    .append("text")
    .attr("class", "corr-node-label")
    .attr("dy", d => _nodeRadius(d) + 12)
    .text(d => (d.label || d.id).slice(0, 18));

  // Simulation
  _simulation = d3.forceSimulation(_simNodes)
    .force("link", d3.forceLink(simLinks).id(d => d.id).distance(d => 80 + 120 / Math.max(1, d.weight)))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collide", d3.forceCollide(d => _nodeRadius(d) + 8));

  _simulation.on("tick", () => {
    _linkSel
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);
    _nodeSel.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  // Click background → deselect
  _svg.on("click", () => {
    _selectedNode = null;
    _nodeSel?.select("circle").classed("selected", false);
    _clearInspector();
    _applyFilters();
  });
}

// ── Filter application ────────────────────────────────────────────────────────

function _applyFilters() {
  if (!_nodeSel || !_linkSel || !_simNodes) return;
  const { platforms, risks } = _activeFilters;
  const hasPlatform = platforms.size > 0;
  const hasRisk     = risks.size > 0;

  const visibleIds = new Set();
  _simNodes.forEach(n => {
    const pOk = !hasPlatform || (n.platforms || []).some(p => platforms.has(p));
    const rOk = !hasRisk || risks.has(n.risk_level);
    if ((pOk && rOk) || n.is_device_owner) visibleIds.add(n.id);
  });

  _nodeSel.select("circle").classed("dimmed", d => !visibleIds.has(d.id));
  _nodeSel.select("text").attr("opacity", d => visibleIds.has(d.id) ? 1 : 0);
  _linkSel.classed("dimmed", d => {
    const sId = typeof d.source === "object" ? d.source.id : d.source;
    const tId = typeof d.target === "object" ? d.target.id : d.target;
    if (!visibleIds.has(sId) || !visibleIds.has(tId)) return true;
    const pOk = !hasPlatform || (d.platforms || []).some(p => platforms.has(p));
    return !pOk;
  });
}

// ── Inspector panel ───────────────────────────────────────────────────────────

function _showInspector(node) {
  const el = document.getElementById("corr-inspector");
  if (!el) return;

  const events = (_data.timeline || [])
    .filter(e => e.contact_id === node.id)
    .slice(-30)
    .reverse();

  const plats = (node.platforms || []).map(p => `${_platformIcon(p)} ${p}`).join("  ");
  const cats  = node.categories || [];

  el.innerHTML = `
    <div class="corr-inspector-contact">
      <div class="corr-inspector-name">${_esc(node.label || node.id)}</div>
      <div class="corr-inspector-meta">
        <span class="corr-risk-badge ${node.risk_level}">${node.risk_level}</span>
        <span style="font-size:0.75rem;color:var(--text-muted)">${plats}</span>
      </div>
      <div class="corr-inspector-stats">
        <span>Msgs <strong>${node.msg_count}</strong></span>
        <span>Calls <strong>${node.call_count}</strong></span>
        ${node.duration_s > 0 ? `<span>Duration <strong>${Math.round(node.duration_s / 60)}m</strong></span>` : ""}
      </div>
      ${cats.length ? `<div class="corr-categories">${cats.map(c => `<span class="corr-category-tag">${_esc(c)}</span>`).join("")}</div>` : ""}
    </div>
    ${events.length > 0 ? `
      <div class="corr-timeline-title">Recent Activity</div>
      ${events.map(e => `
        <div class="corr-timeline-item ${e.type === "call" ? "call" : "msg"}">
          <div class="corr-timeline-ts">${_fmtTs(e.ts)}</div>
          <div class="corr-timeline-body">
            ${e.type === "call" ? "📞 " : ""}${_esc(e.summary)}
            <span style="color:var(--text-muted);font-size:0.68rem">${_esc(e.platform)}</span>
          </div>
        </div>
      `).join("")}
    ` : `<p style="color:var(--text-muted);font-size:0.8rem;margin-top:8px">No timeline events.</p>`}
  `;
}

function _clearInspector() {
  const el = document.getElementById("corr-inspector");
  if (el) el.innerHTML = `<div class="corr-inspector-placeholder"><p>Click a contact node to inspect</p></div>`;
}

// ── Heatmaps ──────────────────────────────────────────────────────────────────

function _renderHeatmaps(heatmap) {
  const hours = (heatmap.by_hour    || []).concat(new Array(24).fill(0)).slice(0, 24);
  const days  = (heatmap.by_weekday || []).concat(new Array(7).fill(0)).slice(0, 7);
  const maxHr = Math.max(1, ...hours);
  const maxDy = Math.max(1, ...days);

  const hourLabels = Array.from({ length: 24 }, (_, i) => i % 6 === 0 ? String(i) : "");
  const dayLabels  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  const hourEl = document.getElementById("corr-heatmap-hour");
  if (hourEl) {
    hourEl.innerHTML = hours.map((v, i) => `
      <div class="corr-bar-wrap" title="${i}:00 — ${v} events">
        <div class="corr-bar-track">
          <div class="corr-bar" style="height:${Math.max(2, Math.round((v / maxHr) * 100))}%"></div>
        </div>
        <div class="corr-bar-label">${hourLabels[i]}</div>
      </div>
    `).join("");
  }

  const dowEl = document.getElementById("corr-heatmap-dow");
  if (dowEl) {
    dowEl.innerHTML = days.map((v, i) => `
      <div class="corr-bar-wrap" title="${dayLabels[i]} — ${v} events">
        <div class="corr-bar-track">
          <div class="corr-bar" style="height:${Math.max(2, Math.round((v / maxDy) * 100))}%"></div>
        </div>
        <div class="corr-bar-label">${dayLabels[i]}</div>
      </div>
    `).join("");
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _fmtTs(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts.replace("Z", ""));
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return ts.slice(0, 16) || ""; }
}

function _esc(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
