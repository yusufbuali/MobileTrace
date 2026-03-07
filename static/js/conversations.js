/**
 * conversations.js — Conversations tab for MobileTrace.
 * Browse all messages grouped by platform/thread, with search.
 */
import { apiFetch } from "./api.js";

let _caseId = null;
let _threads = [];
let _activePlatform = null;  // null = all platforms
let _searchTimer = null;

function dom(id) { return document.getElementById(id); }

// ── Public API ────────────────────────────────────────────────────────────────

export function initConversations(caseId) {
  _caseId = caseId;
  _activePlatform = null;
  _loadThreads();
  _wireSearch();
}

// ── Threads ───────────────────────────────────────────────────────────────────

async function _loadThreads() {
  if (!_caseId) return;
  try {
    _threads = await apiFetch(`/api/cases/${_caseId}/threads`);
  } catch (_) {
    _threads = [];
  }
  _renderPlatformPills();
  _renderThreadList(_threads);
  // Clear message view
  const header = dom("conv-header");
  const msgs = dom("conv-messages");
  if (header) header.textContent = "Select a thread";
  if (msgs) msgs.innerHTML = '<p class="muted" style="padding:8px">Select a thread to view messages.</p>';
}

function _renderPlatformPills() {
  const container = dom("conv-platform-pills");
  if (!container) return;
  const platforms = [...new Set(_threads.map(t => t.platform).filter(Boolean))];
  container.innerHTML = "";

  const allPill = _makePill("All", _activePlatform === null);
  allPill.addEventListener("click", () => {
    _activePlatform = null;
    _renderPlatformPills();
    _renderThreadList(_threads);
  });
  container.appendChild(allPill);

  platforms.forEach(p => {
    const pill = _makePill(p, _activePlatform === p);
    pill.addEventListener("click", () => {
      _activePlatform = p;
      _renderPlatformPills();
      _renderThreadList(_threads.filter(t => t.platform === p));
    });
    container.appendChild(pill);
  });
}

function _makePill(label, active) {
  const span = document.createElement("span");
  span.className = `platform-pill${active ? " active" : ""}`;
  span.textContent = label;
  return span;
}

function _renderThreadList(threads) {
  const container = dom("conv-thread-list");
  if (!container) return;
  container.innerHTML = "";

  if (!threads.length) {
    container.innerHTML = '<p class="muted" style="padding:10px 12px">No threads found.</p>';
    return;
  }

  threads.forEach(t => {
    const item = document.createElement("div");
    item.className = "conv-thread-item";
    item.innerHTML = `
      <div class="conv-thread-platform">${_escHtml(t.platform || "")}</div>
      <div class="conv-thread-name">${_escHtml(t.thread || "(unknown)")}</div>
      <div class="conv-thread-meta">${t.message_count} msg${t.message_count !== 1 ? "s" : ""} · ${_fmtDate(t.last_ts)}</div>
    `;
    item.addEventListener("click", () => {
      container.querySelectorAll(".conv-thread-item").forEach(el => el.classList.remove("active"));
      item.classList.add("active");
      _openThread(t.platform, t.thread);
    });
    container.appendChild(item);
  });
}

// ── Thread view ───────────────────────────────────────────────────────────────

async function _openThread(platform, thread) {
  const header = dom("conv-header");
  const msgs = dom("conv-messages");
  if (!header || !msgs) return;

  header.textContent = `${platform ? platform.toUpperCase() + " · " : ""}${thread || ""}`;
  msgs.innerHTML = '<p class="muted" style="padding:8px">Loading…</p>';

  try {
    const params = new URLSearchParams({ limit: 200 });
    if (platform) params.set("platform", platform);
    if (thread) params.set("thread", thread);
    const rows = await apiFetch(`/api/cases/${_caseId}/messages?${params}`);
    _renderMessages(rows, msgs);
  } catch (err) {
    msgs.innerHTML = `<p class="muted" style="padding:8px">Error: ${_escHtml(err.message)}</p>`;
  }
}

function _renderMessages(rows, container) {
  container.innerHTML = "";
  if (!rows.length) {
    container.innerHTML = '<p class="muted" style="padding:8px">No messages in this thread.</p>';
    return;
  }
  rows.forEach(msg => container.appendChild(_renderBubble(msg)));
  container.scrollTop = container.scrollHeight;
}

function _renderBubble(msg) {
  const isSent = msg.direction === "outgoing";
  const wrap = document.createElement("div");
  wrap.style.display = "flex";
  wrap.style.flexDirection = "column";
  wrap.style.alignItems = isSent ? "flex-end" : "flex-start";

  const bubble = document.createElement("div");
  bubble.className = `msg-bubble ${isSent ? "msg-sent" : "msg-received"}`;

  const body = msg.body ? msg.body.trim() : "";
  if (body) {
    bubble.textContent = body;
  } else {
    const em = document.createElement("em");
    em.className = "msg-empty-media";
    em.textContent = "[media / attachment]";
    bubble.appendChild(em);
  }

  const ts = document.createElement("div");
  ts.className = "msg-ts";
  const sender = isSent ? (msg.sender || "") : (msg.sender || "");
  ts.textContent = `${sender ? sender + " · " : ""}${_fmtDate(msg.timestamp)}`;

  wrap.appendChild(bubble);
  wrap.appendChild(ts);
  return wrap;
}

// ── Search ────────────────────────────────────────────────────────────────────

function _wireSearch() {
  const input = dom("conv-search");
  if (!input) return;
  input.value = "";
  input.removeEventListener("input", _onSearchInput);
  input.addEventListener("input", _onSearchInput);
}

function _onSearchInput(e) {
  clearTimeout(_searchTimer);
  const q = e.target.value.trim();
  if (!q) {
    // Return to thread list
    _renderPlatformPills();
    _renderThreadList(_activePlatform ? _threads.filter(t => t.platform === _activePlatform) : _threads);
    const header = dom("conv-header");
    const msgs = dom("conv-messages");
    if (header) header.textContent = "Select a thread";
    if (msgs) msgs.innerHTML = '<p class="muted" style="padding:8px">Select a thread to view messages.</p>';
    return;
  }
  _searchTimer = setTimeout(() => _search(q), 400);
}

async function _search(q) {
  const msgs = dom("conv-messages");
  const header = dom("conv-header");
  if (!msgs || !header) return;
  header.textContent = `Search: "${q}"`;
  msgs.innerHTML = '<p class="muted" style="padding:8px">Searching…</p>';
  try {
    const rows = await apiFetch(`/api/cases/${_caseId}/messages?q=${encodeURIComponent(q)}&limit=100`);
    _renderMessages(rows, msgs);
  } catch (err) {
    msgs.innerHTML = `<p class="muted" style="padding:8px">Search error: ${_escHtml(err.message)}</p>`;
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function _escHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _fmtDate(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (isNaN(d)) return ts;
    return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch (_) {
    return ts;
  }
}
