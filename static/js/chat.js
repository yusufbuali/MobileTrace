/**
 * MobileTrace chat panel — per-case forensics chatbot.
 * Handles message sending, history rendering, and citations display.
 */
import { apiFetch } from "./api.js";
import { markdownToFragment, highlightConfidenceTokens } from "./markdown.js";
import { selectThread } from "./conversations.js";

let _activeCaseId = null;
let _currentEs = null; // active EventSource for cancel

// DOM refs (resolved lazily when the chat tab is first opened)
function dom(id) { return document.getElementById(id); }

// ── Public API exposed to cases.js ─────────────────────────────────────────

export function initChat(caseId) {
  _activeCaseId = caseId;
  _loadHistory();
}

// ── Analysis Preview ─────────────────────────────────────────────────────────

export async function loadAnalysisPreview(caseId) {
  const previewEl = dom("analysis-preview");
  if (!previewEl) return;

  // Hide results and stream, show preview
  const resultsView = dom("analysis-results-view");
  const streamEl = dom("analysis-stream");
  const header = dom("analysis-progress-header");
  if (resultsView) resultsView.classList.add("aph-hidden");
  if (streamEl) streamEl.style.display = "none";
  if (header) header.classList.add("aph-hidden");

  let data;
  try {
    data = await apiFetch(`/api/cases/${caseId}/analysis/preview`);
  } catch (err) {
    previewEl.innerHTML = '<div class="ap-empty-state"><div class="ap-empty-state-icon">&#128269;</div><div class="ap-empty-state-text">Could not load analysis preview.</div></div>';
    previewEl.style.display = "";
    return;
  }

  // Evidence section
  const evEl = dom("ap-evidence");
  if (evEl) {
    if (data.evidence && data.evidence.length) {
      evEl.innerHTML = data.evidence.map(e =>
        `<div class="ap-ev-row">
          <span class="ap-ev-format">${e.format || "unknown"}</span>
          <span class="ap-ev-path">${e.source_path || "uploaded file"}</span>
          <span class="ap-ev-status ${e.parse_status === "done" ? "done" : "error"}">${e.parse_status}</span>
        </div>`
      ).join("");
    } else {
      evEl.innerHTML = '<div class="ap-empty-state"><div class="ap-empty-state-icon">&#128193;</div><div class="ap-empty-state-text">No evidence uploaded. Upload evidence first to run analysis.</div></div>';
      const footer = previewEl.querySelector(".ap-footer");
      const artHeader = previewEl.querySelector(".ap-artifacts-header");
      const artList = dom("ap-artifact-list");
      if (footer) footer.style.display = "none";
      if (artHeader) artHeader.style.display = "none";
      if (artList) artList.style.display = "none";
      previewEl.style.display = "";
      return;
    }
  }

  // Artifact checkboxes
  const listEl = dom("ap-artifact-list");
  if (listEl) {
    listEl.innerHTML = data.artifacts.map(a => {
      const empty = a.count === 0;
      const unit = a.type === "messages" ? "messages" : "records";
      return `<label class="ap-artifact ${empty ? "empty" : "selected"}" data-key="${a.key}">
        <input type="checkbox" value="${a.key}" ${empty ? "" : "checked"} />
        <div class="ap-artifact-info">
          <span class="ap-artifact-label">${a.label}</span>
          <span>
            <span class="ap-artifact-count">${a.count.toLocaleString()} ${unit}</span>
            ${empty ? '<span class="ap-artifact-warn">&#9888; empty</span>' : ""}
          </span>
        </div>
      </label>`;
    }).join("");

    // Wire checkbox changes
    listEl.querySelectorAll("input[type=checkbox]").forEach(cb => {
      cb.addEventListener("change", () => {
        const label = cb.closest(".ap-artifact");
        if (cb.checked) label.classList.add("selected");
        else label.classList.remove("selected");
        _updateSelectionCount(data.artifacts.length);
      });
    });
  }

  // Toggle all button (onclick to avoid listener accumulation on re-calls)
  const toggleBtn = dom("ap-toggle-all");
  if (toggleBtn) {
    toggleBtn.onclick = () => {
      const cbs = listEl.querySelectorAll("input[type=checkbox]");
      const allChecked = [...cbs].filter(c => c.checked).length === cbs.length;
      cbs.forEach(cb => {
        cb.checked = !allChecked;
        const label = cb.closest(".ap-artifact");
        if (cb.checked) label.classList.add("selected");
        else label.classList.remove("selected");
      });
      toggleBtn.textContent = allChecked ? "Select All" : "Deselect All";
      _updateSelectionCount(data.artifacts.length);
    };
  }

  // Start button
  const startBtn = dom("ap-start-btn");
  if (startBtn) {
    startBtn.disabled = false;
    startBtn.onclick = () => {
      const selected = [...listEl.querySelectorAll("input[type=checkbox]:checked")].map(c => c.value);
      if (!selected.length) return;
      previewEl.style.display = "none";
      _triggerWithArtifacts(caseId, selected);
    };
  }

  // Wire multi-model button in preview footer
  _wireMultiModelButtons(caseId);

  _updateSelectionCount(data.artifacts.length);

  // Show footer/header in case they were hidden
  const footer = previewEl.querySelector(".ap-footer");
  const artHeader = previewEl.querySelector(".ap-artifacts-header");
  if (footer) footer.style.display = "";
  if (artHeader) artHeader.style.display = "";
  if (listEl) listEl.style.display = "";

  previewEl.style.display = "";
}

function _updateSelectionCount(total) {
  const listEl = dom("ap-artifact-list");
  const countEl = dom("ap-selection-count");
  const startBtn = dom("ap-start-btn");
  const toggleBtn = dom("ap-toggle-all");
  if (!listEl) return;
  const checked = listEl.querySelectorAll("input[type=checkbox]:checked").length;
  if (countEl) countEl.textContent = `${checked} of ${total} artifacts selected`;
  if (startBtn) startBtn.disabled = checked === 0;
  if (toggleBtn) toggleBtn.textContent = checked === total ? "Deselect All" : "Select All";
}

// ── History ─────────────────────────────────────────────────────────────────

async function _loadHistory() {
  if (!_activeCaseId) return;
  try {
    const rows = await apiFetch(`/api/cases/${_activeCaseId}/chat/history`);
    const container = dom("chat-messages");
    if (!container) return;
    container.innerHTML = "";
    rows.forEach(r => _appendBubble(r.role, r.content));
    _scrollToBottom();
  } catch (_) {
    // No history yet — that's fine
  }
}

// ── Rendering ────────────────────────────────────────────────────────────────

function _appendBubble(role, text) {
  const container = dom("chat-messages");
  if (!container) return;
  const div = document.createElement("div");
  div.className = `chat-bubble ${role}`;
  div.textContent = text;
  container.appendChild(div);
}

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

function _scrollToBottom() {
  const container = dom("chat-messages");
  if (container) container.scrollTop = container.scrollHeight;
}

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

// ── Submit ────────────────────────────────────────────────────────────────────

async function _sendMessage(message) {
  if (!_activeCaseId || !message.trim()) return;

  // Show user bubble immediately
  _appendBubble("user", message);
  const thinkingBubble = _appendThinking();
  _scrollToBottom();

  try {
    const data = await apiFetch(`/api/cases/${_activeCaseId}/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });

    // Replace thinking bubble with real response
    if (thinkingBubble) thinkingBubble.remove();
    _appendBubble("assistant", data.response || "(empty response)");
    _renderCitations(data.context_count || 0, data.citations || []);
    _scrollToBottom();
  } catch (err) {
    if (thinkingBubble) thinkingBubble.remove();
    _appendBubble("assistant", `Error: ${err.message}`);
    _scrollToBottom();
  }
}

// ── Event wiring (runs after DOM is ready) ───────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  const form = dom("chat-form");
  const input = dom("chat-input");
  if (!form || !input) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = input.value.trim();
    if (!msg) return;
    input.value = "";
    await _sendMessage(msg);
  });
});

// ── Analysis controls (re-used from dashboard) ───────────────────────────────

// ── Radar progress header ─────────────────────────────────────────────────────

function _setRadar({ state = "running", label = "", count = 0, total = 0, current = "" } = {}) {
  const header = dom("analysis-progress-header");
  if (!header) return;
  header.classList.remove("aph-hidden");
  header.dataset.state = state;
  const labelEl  = dom("aph-label");
  const countEl  = dom("aph-count");
  const fillEl   = dom("aph-bar-fill");
  const currentEl = dom("aph-current");
  if (labelEl)   labelEl.textContent  = label  || (state === "complete" ? "Analysis complete" : state === "failed" ? "Analysis failed" : "Initializing…");
  if (countEl)   countEl.textContent  = `${count} / ${total} artifacts`;
  if (fillEl)    fillEl.style.width   = total > 0 ? `${Math.round((count / total) * 100)}%` : "0%";
  if (currentEl) currentEl.textContent = current ? `Currently: ${current}` : "";
}

async function _triggerWithArtifacts(caseId, artifacts) {
  // Reset UI: show radar, clear stream list, hide results view + preview
  _setRadar({ state: "running", label: "Starting analysis…", count: 0, total: artifacts.length });
  const streamList = dom("analysis-stream-list");
  const resultsView = dom("analysis-results-view");
  const previewEl = dom("analysis-preview");
  if (streamList) streamList.innerHTML = "";
  if (resultsView) resultsView.classList.add("aph-hidden");
  if (previewEl) previewEl.style.display = "none";
  const streamEl = dom("analysis-stream");
  if (streamEl) streamEl.style.display = "";

  // Show cancel button
  const cancelBtn = dom("aph-cancel-btn");
  if (cancelBtn) {
    cancelBtn.classList.remove("aph-hidden");
    cancelBtn.onclick = () => _cancelAnalysis(caseId);
  }

  try {
    await apiFetch(`/api/cases/${caseId}/analyze`, {
      method: "POST",
      body: JSON.stringify({ artifacts }),
    });
  } catch (err) {
    _setRadar({ state: "failed", label: `Failed to start: ${err.message}`, count: 0, total: 0 });
    if (cancelBtn) cancelBtn.classList.add("aph-hidden");
    return;
  }

  // Close any stale EventSource from a previous analysis
  if (_currentEs) { _currentEs.close(); _currentEs = null; }

  const es = new EventSource(`/api/cases/${caseId}/analysis/stream`);
  _currentEs = es;
  const done = [];

  es.addEventListener("artifact_done", (e) => {
    const d = JSON.parse(e.data);
    done.push(d.artifact_key);
    _setRadar({
      state: "running",
      label: `Analyzing ${d.artifact_key}…`,
      count: done.length,
      total: artifacts.length,
      current: d.artifact_key,
    });
    if (streamList) {
      const card = document.createElement("div");
      card.className = "analysis-stream-card";
      card.innerHTML = `
        <div class="asc-header">
          <span class="asc-title">${d.artifact_key}</span>
          <span class="asc-meta">${d.provider || ""}</span>
        </div>
        <div class="asc-meta">${d.error ? "Error: " + d.error : "Done"}</div>
      `;
      streamList.appendChild(card);
    }
  });

  es.addEventListener("complete", () => {
    _setRadar({ state: "complete", label: "Analysis complete", count: done.length, total: artifacts.length, current: "" });
    es.close();
    _currentEs = null;
    if (cancelBtn) cancelBtn.classList.add("aph-hidden");
    if (streamEl) streamEl.style.display = "none";
    loadAnalysisResults(caseId);
  });

  es.addEventListener("cancelled", () => {
    _setRadar({ state: "failed", label: "Analysis cancelled", count: done.length, total: artifacts.length, current: "" });
    es.close();
    _currentEs = null;
    if (cancelBtn) cancelBtn.classList.add("aph-hidden");
    // Show preview again so user can re-run
    if (previewEl) previewEl.style.display = "";
    // Still load any partial results
    if (done.length > 0) loadAnalysisResults(caseId);
  });

  es.addEventListener("error", (e) => {
    let msg = "Analysis failed.";
    if (e.data) {
      try { msg = JSON.parse(e.data).message || msg; } catch (_) {}
    }
    _setRadar({ state: "failed", label: msg, count: done.length, total: artifacts.length });
    es.close();
    _currentEs = null;
    if (cancelBtn) cancelBtn.classList.add("aph-hidden");
  });
}

async function _cancelAnalysis(caseId) {
  try {
    await apiFetch(`/api/cases/${caseId}/analysis/cancel`, { method: "POST" });
  } catch (_) {}
  if (_currentEs) {
    _currentEs.close();
    _currentEs = null;
  }
}

export async function triggerAnalysis(caseId) {
  // Called from the "Run Analysis" button in dashboard header — loads preview first
  await loadAnalysisPreview(caseId);
}

export async function loadAnalysisResults(caseId) {
  const resultsView = dom("analysis-results-view");
  const execContent = dom("analysis-exec-content");
  const findingsEl  = dom("analysis-findings");
  if (!resultsView || !execContent || !findingsEl) return;

  let rows;
  try {
    rows = await apiFetch(`/api/cases/${caseId}/analysis`);
  } catch (_) {
    return;
  }
  if (!rows || !rows.length) {
    const streamList = dom("analysis-stream-list");
    if (streamList) streamList.innerHTML = '<p class="muted" style="padding:12px 0">No analysis results yet. Click <strong>Run Analysis</strong> above to start.</p>';
    return;
  }

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
  const summaryParts = rows.map(r => {
    const p = r.result_parsed || null;
    const rsum = p && (p.risk_level_summary || p.executive_summary || p.summary);
    if (rsum) return `**${_titleCase(r.artifact_key)}:** ${rsum}`;
    if (!p && r.result) return `**${_titleCase(r.artifact_key)}:** ${String(r.result).slice(0, 200).trim()}`;
    return null;
  }).filter(Boolean);
  
  const summaryFrag = markdownToFragment(summaryParts.length ? summaryParts.join("\n\n") : "_No summary available._");
  // Enhance summary with jump links if applicable
  summaryFrag.querySelectorAll("strong").forEach(bold => {
    const text = bold.textContent.replace(":", "");
    const matchingRow = rows.find(r => _titleCase(r.artifact_key) === text);
    if (matchingRow) {
      bold.classList.add("jump-link");
      bold.onclick = () => {
        const details = Array.from(findingsEl.querySelectorAll("details")).find(d => d.querySelector("summary span").textContent === text);
        if (details) {
          details.open = true;
          details.scrollIntoView({ behavior: "smooth" });
        }
      };
    }
  });
  execContent.appendChild(summaryFrag);

  // ── Per-Artifact Details ───────────────────────────────────────
  findingsEl.innerHTML = "";
  rows.forEach((r, i) => {
    const p = r.result_parsed ? _normalizeAnalysis(r.result_parsed) : null;
    const conf = p ? _jsonRiskLevel(p) : _extractConfidence(r.result || "");

    const details = document.createElement("details");
    if (i === 0) details.open = true;

    const summary = document.createElement("summary");
    summary.innerHTML = `
      <span style="flex:1">${_titleCase(r.artifact_key)}</span>
      ${conf ? `<span class="confidence-inline ${_confidenceClass(conf)}">${conf}</span>` : ""}
      <span class="asc-meta" style="margin-left:6px">${r.provider || ""}</span>
    `;
    details.appendChild(summary);

    const body = document.createElement("div");
    if (p) {
      _renderJsonAnalysis(p, body, r.artifact_key);
    } else {
      body.classList.add("markdown-output");
      body.appendChild(markdownToFragment(r.result || "(no result)"));
    }
    details.appendChild(body);
    findingsEl.appendChild(details);
  });

  // ── Action buttons ─────────────────────────────────────────────
  const reportBtn = dom("btn-view-report");
  if (reportBtn) {
    reportBtn.onclick = () => window.open(`/api/cases/${caseId}/report`, "_blank");
  }
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

  const rerunBtn = dom("btn-rerun-analysis");
  if (rerunBtn) {
    rerunBtn.onclick = () => {
      resultsView.classList.add("aph-hidden");
      const header = dom("analysis-progress-header");
      if (header) header.classList.add("aph-hidden");
      triggerAnalysis(caseId);
    };
  }

  _wireMultiModelButtons(caseId);

  // Show the results view, hide preview
  resultsView.classList.remove("aph-hidden");
  const previewEl = dom("analysis-preview");
  if (previewEl) previewEl.style.display = "none";

  // Show radar in complete state if it's currently hidden (page reload case)
  const header = dom("analysis-progress-header");
  if (header && header.classList.contains("aph-hidden")) {
    _setRadar({ state: "complete", label: "Analysis complete", count: rows.length, total: rows.length });
  }
}

function _titleCase(str) {
  return String(str || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// ── Analysis JSON normalizer ──────────────────────────────────────────────────
// LLMs return inconsistent field names and nesting. This maps everything to the
// canonical schema before rendering.

function _normalizeAnalysis(raw) {
  let p = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};

  // 1. Unwrap "analysis" wrapper  e.g. { "analysis": { ... } }
  if (p.analysis && typeof p.analysis === "object" && !Array.isArray(p.analysis)) {
    p = { ...p.analysis, ...p };
    delete p.analysis;
  }

  // 2. Alias contact_risk_assessment → conversation_risk_assessment
  if (!p.conversation_risk_assessment && p.contact_risk_assessment) {
    p.conversation_risk_assessment = p.contact_risk_assessment;
  }

  // 3. Normalize each CRA item's field names
  if (Array.isArray(p.conversation_risk_assessment)) {
    p.conversation_risk_assessment = p.conversation_risk_assessment.map(item => ({
      ...item,
      // thread_id alias: phone_number / contact / number
      thread_id: item.thread_id || item.phone_number || item.contact || item.number || "—",
      // messages alias: calls
      messages: item.messages ?? item.calls ?? 0,
      // sent alias: outgoing
      sent: item.sent ?? item.outgoing ?? 0,
      // received alias: incoming
      received: item.received ?? item.incoming ?? 0,
      // key_indicators: string → array, or indicators alias
      key_indicators: Array.isArray(item.key_indicators)
        ? item.key_indicators
        : item.key_indicators
          ? [item.key_indicators]
          : Array.isArray(item.indicators) ? item.indicators : [],
    }));
  }

  // 4. Normalize key_findings: array → { top_significant_conversations: [...] }
  if (Array.isArray(p.key_findings)) {
    p.key_findings = {
      top_significant_conversations: p.key_findings.map(f => ({
        thread_id: f.thread_id || f.thread_number || f.category || f.contact || "",
        summary:   f.summary || f.details || f.significance || f.key_details || "",
        key_messages: Array.isArray(f.key_messages) ? f.key_messages : [],
      })),
    };
  }

  // 5. Normalize key_findings items inside dict form
  if (p.key_findings && Array.isArray(p.key_findings.top_significant_conversations)) {
    p.key_findings.top_significant_conversations = p.key_findings.top_significant_conversations.map(tc => ({
      ...tc,
      thread_id: tc.thread_id || tc.thread_number || tc.contact || "",
      summary:   tc.summary || tc.significance || tc.key_details || "",
    }));
  }

  // 6. Normalize risk_level_summary from alternate fields
  if (!p.risk_level_summary) {
    p.risk_level_summary = p.risk_classification || p.executive_summary || p.overall_assessment || "";
  }

  return p;
}

function _jumpToThread(platform, threadId) {
  // 1. Switch tab
  const convBtn = document.querySelector('.tab-btn[data-tab="tab-conversations"]');
  if (convBtn) convBtn.click();
  // 2. Select thread
  selectThread(platform, threadId);
}

function _renderJsonAnalysis(p, container, artifactKey = "") {
  const esc = s => String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  const platform = artifactKey.split("_")[0] || null; // e.g. "whatsapp" from "whatsapp_messages"

  // Risk summary banner
  const rsum = p.risk_level_summary || p.summary || "";
  if (rsum) {
    const banner = document.createElement("div");
    banner.className = "analysis-risk-banner";
    banner.innerHTML = `<p${_isRtl(rsum) ? ' dir="rtl"' : ""}>${esc(rsum)}</p>`;
    container.appendChild(banner);
  }

  // Conversation risk assessment
  const cra = Array.isArray(p.conversation_risk_assessment) ? p.conversation_risk_assessment : [];
  if (cra.length) {
    const label = document.createElement("div");
    label.className = "analysis-section-label";
    label.textContent = "Conversation Risk Assessment";
    container.appendChild(label);

    cra.forEach(t => {
      const rl = (t.risk_level || "").toUpperCase();
      const rs = parseInt(t.risk_score || 0, 10);
      const scoreClass = rs >= 7 ? "score-high" : rs >= 4 ? "score-medium" : "score-low";

      const tc = document.createElement("div");
      tc.className = "analysis-thread-card";
      tc.innerHTML = `
        <div class="atc-header">
          <span class="atc-thread-id jump-link" data-platform="${esc(platform || "")}" data-thread="${esc(t.thread_id || "")}">${esc(t.thread_id || "—")}</span>
          ${rl ? `<span class="confidence-inline ${_confidenceClass(rl)}">${rl}</span>` : ""}
        </div>
        <div class="risk-bar-wrap">
          <div class="risk-bar-track"><div class="risk-bar-fill ${scoreClass}" style="width:${Math.min(rs*10,100)}%"></div></div>
          <span class="risk-score-num">${rs}/10</span>
        </div>
        <div class="atc-stats">
          &#128172; <strong>${t.messages||0}</strong> msgs &nbsp;·&nbsp;
          ↑ <strong>${t.sent||0}</strong> sent &nbsp;·&nbsp;
          ↓ <strong>${t.received||0}</strong> recv
        </div>
        ${(t.key_indicators||[]).length ? `<ul class="atc-indicators">${(t.key_indicators||[]).map(i=>`<li${_isRtl(i) ? ' dir="rtl"' : ""}>${esc(i)}</li>`).join("")}</ul>` : ""}
      `;
      // Handle click
      tc.querySelector(".atc-thread-id").onclick = () => _jumpToThread(platform, t.thread_id);
      container.appendChild(tc);
    });
  }

  // Key findings
  const kf = p.key_findings;
  if (kf) {
    const label = document.createElement("div");
    label.className = "analysis-section-label";
    label.style.marginTop = "12px";
    label.textContent = "Key Findings";
    container.appendChild(label);

    (kf.top_significant_conversations || []).forEach(tc => {
      const block = document.createElement("div");
      block.className = "analysis-finding-block";
      const _sum = tc.summary || "";
      let inner = `<div class="afb-thread jump-link" data-platform="${esc(platform || "")}" data-thread="${esc(tc.thread_id || "")}">${esc(tc.thread_id||"")}</div>
                   <div class="afb-summary"${_isRtl(_sum) ? ' dir="rtl"' : ""}>${esc(_sum)}</div>`;
      (tc.key_messages||[]).forEach(km => {
        const _body = km.body || "";
        inner += `<div class="afb-msg"><div class="afb-msg-meta">${esc(km.timestamp||"")} · ${esc(km.direction||"")}</div><div${_isRtl(_body) ? ' dir="rtl"' : ""}>${esc(_body)}</div></div>`;
      });
      block.innerHTML = inner;
      block.querySelector(".afb-thread").onclick = () => _jumpToThread(platform, tc.thread_id);
      container.appendChild(block);
    });

    if (kf.note) {
      const note = document.createElement("div");
      note.className = "analysis-note";
      note.textContent = kf.note;
      container.appendChild(note);
    }
  }

  // Remaining keys — generic kv
  const shown = new Set([
    "conversation_risk_assessment","contact_risk_assessment",
    "key_findings","risk_level_summary","summary","risk_level",
    "confidence_level","risk_classification","executive_summary",
    "overall_assessment","analysis",
  ]);
  const extra = Object.entries(p).filter(([k]) => !shown.has(k));
  if (extra.length) {
    const grid = document.createElement("div");
    grid.className = "analysis-kv-grid";
    extra.forEach(([k, v]) => {
      const key = document.createElement("span");
      key.className = "akg-key";
      key.textContent = k.replace(/_/g, " ");
      const val = document.createElement("span");
      val.className = "akg-val";
      if (typeof v === "object" && v !== null) {
        val.classList.add("markdown-output");
        val.appendChild(markdownToFragment(
          Array.isArray(v)
            ? v.map(i => `- ${typeof i === "object" ? JSON.stringify(i) : i}`).join("\n")
            : Object.entries(v).map(([k2, v2]) => `**${k2.replace(/_/g," ")}:** ${typeof v2 === "object" ? JSON.stringify(v2) : v2}`).join("\n")
        ));
      } else {
        const _sv = String(v ?? "");
        if (_isRtl(_sv)) val.dir = "rtl";
        val.textContent = _sv;
      }
      grid.appendChild(key);
      grid.appendChild(val);
    });
    container.appendChild(grid);
  }
}

function _isRtl(text) {
  if (!text) return false;
  let alpha = 0, rtl = 0;
  for (const ch of String(text)) {
    if (/\p{L}/u.test(ch)) {
      alpha++;
      const cp = ch.codePointAt(0);
      if (
        (cp >= 0x0590 && cp <= 0x05FF) || // Hebrew
        (cp >= 0x0600 && cp <= 0x06FF) || // Arabic
        (cp >= 0x0750 && cp <= 0x077F) || // Arabic Supplement
        (cp >= 0x08A0 && cp <= 0x08FF) || // Arabic Extended-A
        (cp >= 0xFB50 && cp <= 0xFDFF) || // Arabic Presentation Forms-A
        (cp >= 0xFE70 && cp <= 0xFEFF)    // Arabic Presentation Forms-B
      ) rtl++;
    }
  }
  return alpha > 0 && (rtl / alpha) >= 0.3;
}

function _extractConfidence(text) {
  const m = String(text || "").match(/\b(CRITICAL|HIGH|MEDIUM|LOW)\b/i);
  return m ? m[1].toUpperCase() : null;
}

function _confidenceClass(level) {
  return { CRITICAL: "confidence-critical", HIGH: "confidence-high", MEDIUM: "confidence-medium", LOW: "confidence-low" }[(level||"").toUpperCase()] || "";
}

function _jsonRiskLevel(p) {
  const rsum = p.risk_level_summary || p.risk_level || p.confidence_level || "";
  const m = String(rsum).match(/\b(CRITICAL|HIGH|MEDIUM|LOW)\b/i);
  if (m) return m[1].toUpperCase();
  // Check conversation_risk_assessment for the highest level
  const cra = p.conversation_risk_assessment || [];
  const order = ["CRITICAL","HIGH","MEDIUM","LOW"];
  let top = null;
  cra.forEach(t => {
    const lvl = (t.risk_level||"").toUpperCase();
    const idx = order.indexOf(lvl);
    if (idx !== -1 && (top === null || idx < order.indexOf(top))) top = lvl;
  });
  return top;
}

// ══════════════════════════════════════════════════════════════════════════════
// Multi-Model Analysis
// ══════════════════════════════════════════════════════════════════════════════

let _mmCurrentEs = null;  // active multi-model EventSource

// Wire multi-model buttons (called from loadAnalysisResults and loadAnalysisPreview)
function _wireMultiModelButtons(caseId) {
  ["btn-multi-model", "ap-multi-model-btn"].forEach(id => {
    const btn = dom(id);
    if (btn) btn.onclick = () => openMultiModelModal(caseId);
  });
}

export function openMultiModelModal(caseId) {
  const modal = dom("multi-model-modal");
  if (!modal) return;
  modal.style.display = "flex";

  // Reset state
  dom("mm-model-search").value = "";
  dom("mm-selection-error").textContent = "";
  _updateMmSelectionCount([]);

  // Load model list
  _loadMmModels(caseId);
  // Load run history
  _loadMmRunHistory(caseId);

  // Wire close button
  dom("mm-modal-close").onclick = () => { modal.style.display = "none"; };
  modal.onclick = (e) => { if (e.target === modal) modal.style.display = "none"; };

  // Wire run button
  dom("mm-run-btn").onclick = () => _startMultiModelAnalysis(caseId);

  // Wire load run button
  dom("mm-load-run-btn").onclick = () => {
    const sel = dom("mm-run-history");
    const runId = sel?.value;
    if (!runId) return;
    modal.style.display = "none";
    _loadMultiRunResults(caseId, runId);
  };

  // Wire search
  dom("mm-model-search").oninput = (e) => _filterMmModels(e.target.value);
}

let _mmAllModels = [];

async function _loadMmModels(caseId) {
  const listEl = dom("mm-model-list");
  if (!listEl) return;
  listEl.innerHTML = '<div class="mm-loading">Loading models from OpenRouter…</div>';

  try {
    const models = await apiFetch("/api/settings/openrouter-models");
    _mmAllModels = Array.isArray(models) ? models : [];
    _renderMmModels(_mmAllModels);
  } catch (err) {
    listEl.innerHTML = `<div class="mm-error">Could not load models: ${err.message}</div>`;
  }
}

function _renderMmModels(models) {
  const listEl = dom("mm-model-list");
  if (!listEl) return;
  if (!models.length) {
    listEl.innerHTML = '<div class="mm-empty">No models found.</div>';
    return;
  }
  listEl.innerHTML = models.map(m => {
    const price = m.prompt_per_m === 0
      ? '<span class="mm-free">FREE</span>'
      : `<span class="mm-price">$${m.prompt_per_m}/M in · $${m.completion_per_m}/M out</span>`;
    const ctx = m.context_length ? `${(m.context_length/1000).toFixed(0)}k ctx` : "";
    return `<label class="mm-model-item" data-id="${m.id}">
      <input type="checkbox" value="${m.id}" class="mm-cb" />
      <div class="mm-model-info">
        <span class="mm-model-name">${m.name}</span>
        <span class="mm-model-meta">${ctx} ${price}</span>
      </div>
    </label>`;
  }).join("");

  listEl.querySelectorAll(".mm-cb").forEach(cb => {
    cb.addEventListener("change", () => {
      const selected = _getMmSelected();
      _updateMmSelectionCount(selected);
    });
  });
}

function _filterMmModels(query) {
  const q = query.toLowerCase().trim();
  const filtered = q ? _mmAllModels.filter(m =>
    m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)
  ) : _mmAllModels;
  _renderMmModels(filtered);
}

function _getMmSelected() {
  const listEl = dom("mm-model-list");
  if (!listEl) return [];
  return [...listEl.querySelectorAll(".mm-cb:checked")].map(cb => cb.value);
}

function _updateMmSelectionCount(selected) {
  const n = selected.length;
  const countEl = dom("mm-selection-count");
  const errEl = dom("mm-selection-error");
  const runBtn = dom("mm-run-btn");
  if (countEl) countEl.textContent = `${n} model${n !== 1 ? "s" : ""} selected`;
  if (errEl) {
    errEl.textContent = n > 5 ? "Maximum 5 models" : n === 1 ? "Select at least 2 models" : "";
  }
  if (runBtn) runBtn.disabled = n < 2 || n > 5;
}

async function _loadMmRunHistory(caseId) {
  const sel = dom("mm-run-history");
  if (!sel) return;
  try {
    const runs = await apiFetch(`/api/cases/${caseId}/analysis/multi`);
    if (!runs.length) return;
    sel.innerHTML = '<option value="">— select a past run —</option>' +
      runs.map(r => {
        const models = r.models.map(m => m.split("/").pop()).join(", ");
        const date = r.created_at.slice(0, 16).replace("T", " ");
        return `<option value="${r.id}">[${date}] ${models} (${r.status})</option>`;
      }).join("");
  } catch (_) {
    // No history — ok
  }
}

async function _startMultiModelAnalysis(caseId) {
  const selected = _getMmSelected();
  if (selected.length < 2 || selected.length > 5) return;

  const modal = dom("multi-model-modal");
  if (modal) modal.style.display = "none";

  // Show progress grid UI
  _showMultiModelProgress(caseId, selected);

  let runId;
  try {
    const resp = await apiFetch(`/api/cases/${caseId}/analyze/multi`, {
      method: "POST",
      body: JSON.stringify({ models: selected }),
    });
    runId = resp.run_id;
  } catch (err) {
    _setRadar({ state: "failed", label: `Failed to start: ${err.message}`, count: 0, total: 0 });
    return;
  }

  // Subscribe to SSE for this run
  if (_mmCurrentEs) { _mmCurrentEs.close(); _mmCurrentEs = null; }
  const es = new EventSource(`/api/cases/${caseId}/analysis/multi/${runId}/stream`);
  _mmCurrentEs = es;

  const totalTasks = selected.length * Object.keys(_mmGridCells).length;
  let doneTasks = 0;

  es.addEventListener("model_artifact_started", (e) => {
    const d = JSON.parse(e.data);
    _setMmCell(d.model, d.artifact_key, "running");
  });

  es.addEventListener("model_artifact_done", (e) => {
    const d = JSON.parse(e.data);
    doneTasks++;
    _setMmCell(d.model, d.artifact_key, d.error ? "error" : "done");
    _setRadar({
      state: "running",
      label: `Running ${d.model.split("/").pop()} × ${d.artifact_key}…`,
      count: doneTasks,
      total: totalTasks,
    });
  });

  es.addEventListener("consensus_computing", () => {
    _setRadar({ state: "running", label: "Computing consensus…", count: totalTasks, total: totalTasks });
  });

  es.addEventListener("complete", () => {
    _setRadar({ state: "complete", label: "Multi-model analysis complete", count: totalTasks, total: totalTasks });
    es.close();
    _mmCurrentEs = null;
    _loadMultiRunResults(caseId, runId);
  });

  es.addEventListener("error", (e) => {
    let msg = "Multi-model analysis failed.";
    if (e.data) { try { msg = JSON.parse(e.data).message || msg; } catch (_) {} }
    _setRadar({ state: "failed", label: msg, count: doneTasks, total: totalTasks });
    es.close();
    _mmCurrentEs = null;
  });
}

// ── Progress grid ─────────────────────────────────────────────────────────────

let _mmGridCells = {}; // { "model::artifact_key": <td element> }

function _showMultiModelProgress(caseId, models) {
  const resultsView = dom("analysis-results-view");
  const previewEl = dom("analysis-preview");
  const streamEl = dom("analysis-stream");
  if (resultsView) resultsView.classList.add("aph-hidden");
  if (previewEl) previewEl.style.display = "none";

  _mmGridCells = {};

  // Build grid: rows=models, cols=artifacts
  // We'll use artifact keys from the preview if loaded; fallback to known keys
  const ARTIFACT_KEYS = ["sms", "whatsapp", "telegram", "signal", "call_logs", "contacts"];

  const table = document.createElement("table");
  table.className = "mm-grid-table";
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  headerRow.innerHTML = "<th>Model</th>" + ARTIFACT_KEYS.map(k =>
    `<th>${k.replace(/_/g, " ")}</th>`
  ).join("");
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  models.forEach(model => {
    const tr = document.createElement("tr");
    const modelShort = model.split("/").pop();
    tr.innerHTML = `<td class="mm-grid-model" title="${model}">${modelShort}</td>`;
    ARTIFACT_KEYS.forEach(key => {
      const td = document.createElement("td");
      td.className = "mm-grid-cell mm-cell-pending";
      td.title = `${modelShort} × ${key}`;
      td.innerHTML = "·";
      _mmGridCells[`${model}::${key}`] = td;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);

  const streamList = dom("analysis-stream-list");
  if (streamList) {
    streamList.innerHTML = "";
    streamList.appendChild(table);
  }
  if (streamEl) streamEl.style.display = "";

  _setRadar({ state: "running", label: "Starting multi-model analysis…", count: 0, total: models.length * ARTIFACT_KEYS.length });
}

function _setMmCell(model, artifactKey, state) {
  const key = `${model}::${artifactKey}`;
  const td = _mmGridCells[key];
  if (!td) return;
  td.className = `mm-grid-cell mm-cell-${state}`;
  td.innerHTML = state === "running" ? "…" : state === "done" ? "✓" : state === "error" ? "✗" : "·";
}

// ── Load & display a completed multi-model run ─────────────────────────────────

async function _loadMultiRunResults(caseId, runId) {
  let data;
  try {
    data = await apiFetch(`/api/cases/${caseId}/analysis/multi/${runId}`);
  } catch (err) {
    return;
  }

  const resultsView = dom("analysis-results-view");
  const execContent = dom("analysis-exec-content");
  const findingsEl = dom("analysis-findings");
  const streamEl = dom("analysis-stream");
  if (!resultsView || !execContent || !findingsEl) return;

  if (streamEl) streamEl.style.display = "none";

  const artifacts = data.artifacts || [];
  const consensusRows = artifacts.map(a => ({
    artifact_key: a.artifact_key,
    result: a.consensus?.result || "",
    result_parsed: a.consensus?.result_parsed || null,
    provider: "consensus",
    models_breakdown: a.models_breakdown || [],
  })).filter(r => r.result_parsed || r.result);

  if (!consensusRows.length) {
    execContent.innerHTML = '<p class="muted">No consensus results available yet.</p>';
    resultsView.classList.remove("aph-hidden");
    return;
  }

  // Insights bar — same logic as single-model
  let existingBar = resultsView.querySelector(".analysis-insights-bar");
  if (existingBar) existingBar.remove();
  const insightsBar = document.createElement("div");
  insightsBar.className = "analysis-insights-bar";
  const totalThreads = consensusRows.reduce((s, r) =>
    s + ((r.result_parsed?.conversation_risk_assessment) || []).length, 0);
  const topRisk = consensusRows.reduce((best, r) => {
    const rl = _jsonRiskLevel(r.result_parsed || {});
    if (!best) return rl;
    const order = ["CRITICAL","HIGH","MEDIUM","LOW"];
    return order.indexOf(rl) < order.indexOf(best) ? rl : best;
  }, null);
  insightsBar.innerHTML = [
    { value: consensusRows.length, label: "Artifacts" },
    { value: totalThreads, label: "Threads" },
    topRisk ? { value: `<span class="confidence-inline ${_confidenceClass(topRisk)}">${topRisk}</span>`, label: "Risk" } : null,
    { value: `<span class="confidence-inline confidence-high">CONSENSUS</span>`, label: `${data.run.models.length} models` },
  ].filter(Boolean).map(c =>
    `<div class="insight-chip"><span class="insight-chip-value">${c.value}</span><span class="insight-chip-label">${c.label}</span></div>`
  ).join("");
  resultsView.insertBefore(insightsBar, resultsView.firstChild);

  // Executive summary
  execContent.innerHTML = "";
  const summaryParts = consensusRows.map(r => {
    const p = r.result_parsed ? _normalizeAnalysis(r.result_parsed) : null;
    const rsum = p && (p.risk_level_summary || p.executive_summary || p.summary);
    if (rsum) return `**${_titleCase(r.artifact_key)}:** ${rsum}`;
    return null;
  }).filter(Boolean);
  execContent.appendChild(markdownToFragment(summaryParts.length ? summaryParts.join("\n\n") : "_No summary available._"));

  // Per-artifact findings with consensus + breakdown
  findingsEl.innerHTML = "";
  consensusRows.forEach((r, i) => {
    const p = r.result_parsed ? _normalizeAnalysis(r.result_parsed) : null;
    const conf = p ? _jsonRiskLevel(p) : null;

    const details = document.createElement("details");
    if (i === 0) details.open = true;

    const summary = document.createElement("summary");
    summary.innerHTML = `
      <span style="flex:1">${_titleCase(r.artifact_key)}</span>
      ${conf ? `<span class="confidence-inline ${_confidenceClass(conf)}">${conf}</span>` : ""}
      <span class="confidence-inline confidence-high" style="margin-left:4px;font-size:0.7em">CONSENSUS</span>
    `;
    details.appendChild(summary);

    const body = document.createElement("div");
    if (p) {
      _renderJsonAnalysis(p, body, r.artifact_key);
    } else {
      body.classList.add("markdown-output");
      body.appendChild(markdownToFragment(r.result || "(no result)"));
    }
    details.appendChild(body);

    // Per-model breakdown
    if (r.models_breakdown && r.models_breakdown.length) {
      const breakdown = document.createElement("details");
      breakdown.className = "mm-breakdown";
      const bsummary = document.createElement("summary");
      bsummary.textContent = `Per-Model Breakdown (${r.models_breakdown.length} models)`;
      breakdown.appendChild(bsummary);

      r.models_breakdown.forEach(mb => {
        const mdetails = document.createElement("details");
        mdetails.className = "mm-model-panel";
        const msum = document.createElement("summary");
        const mbParsed = mb.result_parsed ? _normalizeAnalysis(mb.result_parsed) : null;
        const mbConf = mbParsed ? _jsonRiskLevel(mbParsed) : null;
        msum.innerHTML = `<span style="flex:1">${mb.provider}</span>${mbConf ? `<span class="confidence-inline ${_confidenceClass(mbConf)}">${mbConf}</span>` : ""}`;
        mdetails.appendChild(msum);
        const mbody = document.createElement("div");
        mbody.className = "mm-model-body";
        if (mbParsed) {
          _renderJsonAnalysis(mbParsed, mbody, r.artifact_key);
        } else {
          mbody.classList.add("markdown-output");
          mbody.appendChild(markdownToFragment(mb.result || "(no result)"));
        }
        mdetails.appendChild(mbody);
        breakdown.appendChild(mdetails);
      });

      details.appendChild(breakdown);
    }

    findingsEl.appendChild(details);
  });

  // Action buttons
  const rerunBtn = dom("btn-rerun-analysis");
  if (rerunBtn) {
    rerunBtn.onclick = () => {
      resultsView.classList.add("aph-hidden");
      const header = dom("analysis-progress-header");
      if (header) header.classList.add("aph-hidden");
      triggerAnalysis(caseId);
    };
  }
  const multiBtn = dom("btn-multi-model");
  if (multiBtn) multiBtn.onclick = () => openMultiModelModal(caseId);

  resultsView.classList.remove("aph-hidden");
  const previewEl = dom("analysis-preview");
  if (previewEl) previewEl.style.display = "none";
  _setRadar({ state: "complete", label: "Multi-model analysis complete", count: consensusRows.length, total: consensusRows.length });
}

// openMultiModelModal is available to cases.js via the module export below
