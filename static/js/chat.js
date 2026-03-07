/**
 * MobileTrace chat panel — per-case forensics chatbot.
 * Handles message sending, history rendering, and citations display.
 */
import { apiFetch } from "./api.js";
import { markdownToFragment, highlightConfidenceTokens } from "./markdown.js";

let _activeCaseId = null;

// DOM refs (resolved lazily when the chat tab is first opened)
function dom(id) { return document.getElementById(id); }

// ── Public API exposed to cases.js ─────────────────────────────────────────

export function initChat(caseId) {
  _activeCaseId = caseId;
  _loadHistory();
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
  div.textContent = "Analysing…";
  container.appendChild(div);
  _scrollToBottom();
  return div;
}

function _scrollToBottom() {
  const container = dom("chat-messages");
  if (container) container.scrollTop = container.scrollHeight;
}

function _renderCitations(contextCount) {
  const panel = dom("chat-citations");
  if (!panel) return;
  if (!contextCount) {
    panel.innerHTML = '<p class="muted">No matching evidence found for this query.</p>';
    return;
  }
  panel.innerHTML = `<p class="muted">${contextCount} evidence record${contextCount !== 1 ? "s" : ""} used as context.</p>`;
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
    _renderCitations(data.context_count || 0);
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

export async function triggerAnalysis(caseId) {
  const progressEl = dom("analysis-progress");
  const resultsEl = dom("analysis-results");
  if (!progressEl || !resultsEl) return;

  progressEl.textContent = "Starting analysis…";
  resultsEl.innerHTML = "";

  try {
    await apiFetch(`/api/cases/${caseId}/analyze`, { method: "POST" });
  } catch (err) {
    progressEl.textContent = `Failed to start: ${err.message}`;
    return;
  }

  // Listen to SSE stream
  const es = new EventSource(`/api/cases/${caseId}/analysis/stream`);
  const done = new Set();

  es.addEventListener("artifact_done", (e) => {
    const d = JSON.parse(e.data);
    done.add(d.artifact_key);
    progressEl.textContent = `Analysed: ${[...done].join(", ")}…`;
  });

  es.addEventListener("complete", () => {
    progressEl.textContent = "Analysis complete.";
    es.close();
    loadAnalysisResults(caseId);
  });

  // Named "error" event from server (e.g. missing API key)
  es.addEventListener("error", (e) => {
    if (e.data) {
      try {
        const d = JSON.parse(e.data);
        progressEl.textContent = `Analysis failed: ${d.message || "Unknown error"}`;
        progressEl.style.color = "var(--danger)";
      } catch (_) {
        progressEl.textContent = "Analysis failed.";
        progressEl.style.color = "var(--danger)";
      }
    } else {
      // Native EventSource connection error
      progressEl.textContent = "Connection lost.";
    }
    es.close();
  });
}

export async function loadAnalysisResults(caseId) {
  const resultsEl = dom("analysis-results");
  if (!resultsEl) return;
  try {
    const rows = await apiFetch(`/api/cases/${caseId}/analysis`);
    if (!rows.length) {
      resultsEl.innerHTML = '<p class="muted">No analysis results yet. Click "Run Analysis" to start.</p>';
      return;
    }
    resultsEl.innerHTML = "";
    rows.forEach(r => {
      const card = document.createElement("div");
      card.className = "analysis-card";

      // Use server-parsed result if available, otherwise try client-side parse
      let parsed = r.result_parsed || null;
      if (!parsed) {
        try { parsed = JSON.parse((r.result || "").trim()); } catch (_) {}
      }

      const conf = parsed
        ? _jsonRiskLevel(parsed)
        : _extractConfidence(r.result || "");

      const header = document.createElement("div");
      header.className = "analysis-card-header open";
      header.addEventListener("click", () => {
        body.classList.toggle("collapsed");
        header.classList.toggle("open");
      });

      const title = document.createElement("h3");
      title.textContent = r.artifact_key;

      const meta = document.createElement("span");
      meta.style.cssText = "font-size:0.75rem;color:var(--text-muted);display:flex;align-items:center;gap:6px";
      meta.innerHTML = `${conf ? `<span class="confidence-inline ${_confidenceClass(conf)}">${conf}</span>` : ""}${r.provider || ""} · ${r.created_at ? r.created_at.slice(0, 16) : ""}`;

      const chevron = document.createElement("span");
      chevron.className = "analysis-card-chevron";
      chevron.textContent = "▾";

      header.appendChild(title);
      header.appendChild(meta);
      header.appendChild(chevron);

      const body = document.createElement("div");
      body.className = "analysis-card-body";

      if (parsed) {
        _renderJsonAnalysis(parsed, body);
      } else {
        body.classList.add("markdown-output");
        body.appendChild(markdownToFragment(r.result || "(no result)"));
      }

      card.appendChild(header);
      card.appendChild(body);
      resultsEl.appendChild(card);
    });
  } catch (_) {
    resultsEl.innerHTML = '<p class="muted">Could not load analysis results.</p>';
  }
}

function _renderJsonAnalysis(p, container) {
  const esc = s => String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

  // Risk summary banner
  const rsum = p.risk_level_summary || p.summary || "";
  if (rsum) {
    const banner = document.createElement("div");
    banner.className = "analysis-risk-banner";
    banner.innerHTML = `<p>${esc(rsum)}</p>`;
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
          <span class="atc-thread-id">${esc(t.thread_id || "—")}</span>
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
        ${(t.key_indicators||[]).length ? `<ul class="atc-indicators">${(t.key_indicators||[]).map(i=>`<li>${esc(i)}</li>`).join("")}</ul>` : ""}
      `;
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
      let inner = `<div class="afb-thread">${esc(tc.thread_id||"")}</div>
                   <div class="afb-summary">${esc(tc.summary||"")}</div>`;
      (tc.key_messages||[]).forEach(km => {
        inner += `<div class="afb-msg"><div class="afb-msg-meta">${esc(km.timestamp||"")} · ${esc(km.direction||"")}</div><div>${esc(km.body||"")}</div></div>`;
      });
      block.innerHTML = inner;
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
  const shown = new Set(["conversation_risk_assessment","key_findings","risk_level_summary","summary","risk_level","confidence_level"]);
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
      val.textContent = typeof v === "object" ? JSON.stringify(v) : String(v);
      grid.appendChild(key);
      grid.appendChild(val);
    });
    container.appendChild(grid);
  }
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
