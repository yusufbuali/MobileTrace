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

      const header = document.createElement("div");
      header.className = "analysis-card-header open";
      header.addEventListener("click", () => {
        body.classList.toggle("collapsed");
        header.classList.toggle("open");
      });

      const title = document.createElement("h3");
      title.textContent = r.artifact_key;

      const conf = _extractConfidence(r.result || "");
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
      body.className = "analysis-card-body markdown-output";
      body.appendChild(markdownToFragment(r.result || "(no result)"));

      card.appendChild(header);
      card.appendChild(body);
      resultsEl.appendChild(card);
    });
  } catch (_) {
    resultsEl.innerHTML = '<p class="muted">Could not load analysis results.</p>';
  }
}

function _extractConfidence(text) {
  const m = String(text || "").match(/\b(CRITICAL|HIGH|MEDIUM|LOW)\b/i);
  return m ? m[1].toUpperCase() : null;
}

function _confidenceClass(level) {
  return { CRITICAL: "confidence-critical", HIGH: "confidence-high", MEDIUM: "confidence-medium", LOW: "confidence-low" }[level] || "";
}
