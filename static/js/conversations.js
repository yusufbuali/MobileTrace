/**
 * conversations.js — Conversations tab for MobileTrace.
 * Browse all messages grouped by platform/thread, with search.
 */
import { apiFetch, fmtBytes } from "./api.js";

let _caseId = null;
let _threads = [];
let _activePlatform = null;  // null = all platforms
let _searchTimer = null;
let _annotations = new Map(); // message_id (number) → annotation object
let _lazyObserver = null;

function dom(id) { return document.getElementById(id); }

// ── Public API ────────────────────────────────────────────────────────────────

export async function initConversations(caseId) {
  clearTimeout(_searchTimer);
  if (!caseId) {
    _showNoCaseState();
    return;
  }
  _caseId = caseId;
  _activePlatform = null;
  _annotations = new Map(); // reset on case switch
  await _loadAnnotations(caseId);
  _loadThreads();
  _wireSearch();
  _wireDateJump();
}

// Listen for IOC jump-to-thread events dispatched by ioc.js via cases.js
window.addEventListener("mt:open-thread", (e) => {
  const { platform, thread } = e.detail;
  _openThread(platform, thread);
}, { once: false });

/**
 * Jump to a specific thread and optionally highlight a message.
 */
export async function selectThread(platform, threadId, messageId = null) {
  if (!_caseId) return;

  // 1. Filter by platform if needed
  if (platform && _activePlatform !== platform) {
    _activePlatform = platform;
    _renderPlatformPills();
    _renderThreadList(_threads.filter(t => t.platform === platform));
  }

  // 2. Open the thread
  const threadData = _threads.find(t => t.platform === platform && t.thread === threadId);
  await _openThread(platform, threadId, threadData?.message_count);

  // 3. Highlight message if ID provided
  if (messageId) {
    const msgs = dom("conv-messages");
    const bubble = msgs.querySelector(`[data-msg-id="${messageId}"]`);
    if (bubble) {
      bubble.scrollIntoView({ behavior: "smooth", block: "center" });
      bubble.classList.add("highlight-pulse");
      setTimeout(() => bubble.classList.remove("highlight-pulse"), 3000);
    }
  }

  // 4. Update sidebar selection
  const list = dom("conv-thread-list");
  list.querySelectorAll(".conv-thread-item").forEach(el => {
    const isTarget = el.dataset.platform === platform && el.querySelector(".conv-thread-name").textContent === threadId;
    el.classList.toggle("active", isTarget);
    if (isTarget) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

async function _loadAnnotations(caseId) {
  try {
    const res = await fetch(`/api/cases/${caseId}/annotations`);
    if (!res.ok) return;
    const list = await res.json();
    _annotations = new Map(list.map(a => [a.message_id, a]));
  } catch (_) { /* non-critical */ }
}

function _showNoCaseState() {
  const header = dom("conv-header");
  const msgs = dom("conv-messages");
  const pills = dom("conv-platform-pills");
  const list = dom("conv-thread-list");
  if (header) header.innerHTML = '<span class="conv-header-title" style="color:var(--text-muted);font-weight:400">No case open</span>';
  if (msgs) msgs.innerHTML = "";
  if (pills) pills.innerHTML = "";
  if (list) list.innerHTML = '<p class="muted" style="padding:10px 12px">Open a case first.</p>';
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
  _showEmptyMain();
}

function _showEmptyMain() {
  const header = dom("conv-header");
  const msgs = dom("conv-messages");
  if (header) header.innerHTML = '<span class="conv-header-title" style="color:var(--text-muted);font-weight:400">Select a thread to view messages</span>';
  if (msgs) {
    msgs.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "conv-empty-state";
    empty.innerHTML = '<div class="conv-empty-state-icon">&#128172;</div><div class="conv-empty-state-text">Select a thread from the sidebar</div>';
    msgs.appendChild(empty);
  }
}

function _renderPlatformPills() {
  const container = dom("conv-platform-pills");
  if (!container) return;
  const platforms = [...new Set(_threads.map(t => t.platform).filter(Boolean))];
  container.innerHTML = "";

  const allPill = _makePill("All", _activePlatform === null, null);
  allPill.addEventListener("click", () => {
    _activePlatform = null;
    _renderPlatformPills();
    _renderThreadList(_threads);
  });
  container.appendChild(allPill);

  platforms.forEach(p => {
    const pill = _makePill(p, _activePlatform === p, p);
    pill.addEventListener("click", () => {
      _activePlatform = p;
      _renderPlatformPills();
      _renderThreadList(_threads.filter(t => t.platform === p));
    });
    container.appendChild(pill);
  });
}

function _makePill(label, active, platform) {
  const span = document.createElement("span");
  span.className = `platform-pill${active ? " active" : ""}`;
  if (platform) span.dataset.platform = platform;
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
    if (t.platform) item.dataset.platform = t.platform;
    item.innerHTML = `
      <div class="conv-thread-platform">${_escHtml(t.platform || "")}</div>
      <div class="conv-thread-name">${_escHtml(t.thread || "(unknown)")}</div>
      <div class="conv-thread-meta">
        ${_fmtDate(t.last_ts)}
        ${t.message_count != null ? `<span class="conv-thread-count">${t.message_count}</span>` : ""}
      </div>
    `;
    item.addEventListener("click", () => {
      container.querySelectorAll(".conv-thread-item").forEach(el => el.classList.remove("active"));
      item.classList.add("active");
      _openThread(t.platform, t.thread, t.message_count);
    });
    container.appendChild(item);
  });
}

// ── Thread view ───────────────────────────────────────────────────────────────

async function _openThread(platform, thread, messageCount) {
  _activeQuery = "";
  const header = dom("conv-header");
  const msgs = dom("conv-messages");
  if (!header || !msgs) return;

  // Build styled header
  header.innerHTML = "";
  if (platform) {
    const badge = document.createElement("span");
    badge.className = `conv-header-platform ${platform.toLowerCase()}`;
    badge.textContent = platform.toUpperCase();
    header.appendChild(badge);
  }
  const title = document.createElement("span");
  title.className = "conv-header-title";
  title.textContent = thread || "(unknown)";
  header.appendChild(title);
  if (messageCount != null) {
    const count = document.createElement("span");
    count.className = "conv-header-count";
    count.textContent = `${messageCount} messages`;
    header.appendChild(count);
  }

  msgs.innerHTML = '<p class="muted" style="padding:8px">Loading…</p>';

  try {
    const params = new URLSearchParams({ limit: 200 });
    if (platform) params.set("platform", platform);
    if (thread) params.set("thread", thread);
    const rows = await apiFetch(`/api/cases/${_caseId}/messages?${params}`);
    _renderMessages(rows, msgs, false);
  } catch (err) {
    msgs.innerHTML = `<p class="muted" style="padding:8px">Error: ${_escHtml(err.message)}</p>`;
  }
}

function _extractDate(ts) {
  if (!ts) return null;
  try { return new Date(ts).toDateString(); } catch (_) { return null; }
}

function _fmtDateLabel(dateStr) {
  const d = new Date(dateStr);
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 86400000).toDateString();
  if (dateStr === today) return "Today";
  if (dateStr === yesterday) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

function _renderMessages(rows, container, showOrigin) {
  container.innerHTML = "";
  if (!rows.length) {
    container.innerHTML = '<p class="muted" style="padding:8px">No messages found.</p>';
    return;
  }
  let lastDate = null;
  rows.forEach(msg => {
    const msgDate = _extractDate(msg.timestamp);
    if (msgDate && msgDate !== lastDate) {
      const sep = document.createElement("div");
      sep.className = "conv-date-sep";
      sep.textContent = _fmtDateLabel(msgDate);
      container.appendChild(sep);
      lastDate = msgDate;
    }
    container.appendChild(_renderBubble(msg, showOrigin));
  });
  container.scrollTop = container.scrollHeight;
  _lazyLoadImages(container);
}

function _renderBubble(msg, showOrigin) {
  const isSent = msg.direction === "outgoing";
  const wrap = document.createElement("div");
  wrap.className = `msg-wrap ${isSent ? "sent" : "received"}`;
  if (msg.id) wrap.dataset.msgId = msg.id;

  // Show platform/thread context in search results
  if (showOrigin) {
    const origin = document.createElement("div");
    origin.className = "msg-search-origin";
    origin.textContent = `${msg.platform || ""} · ${msg.thread_id || msg.sender || ""}`;
    wrap.appendChild(origin);
  }

  // Avatar
  const senderName = msg.sender || (isSent ? "Me" : "?");
  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.style.background = _avatarColor(senderName);
  avatar.textContent = _initials(senderName);
  wrap.appendChild(avatar);

  const content = document.createElement("div");
  content.className = "msg-content";

  const bubble = document.createElement("div");
  bubble.className = `msg-bubble ${isSent ? "msg-sent" : "msg-received"}`;

  const body = msg.body ? msg.body.trim() : "";
  if (body) {
    if (_activeQuery) {
      bubble.innerHTML = _highlightText(body, _activeQuery);
    } else {
      bubble.textContent = body;
    }
  } else {
    const em = document.createElement("em");
    em.className = "msg-empty-media";
    em.textContent = "[media / attachment]";
    bubble.appendChild(em);
  }

  const ts = document.createElement("div");
  ts.className = "msg-ts";
  // For received messages show sender; for sent show nothing (it's the device owner)
  const senderLabel = !isSent && msg.sender ? msg.sender + " · " : "";
  ts.textContent = `${senderLabel}${_fmtDate(msg.timestamp)}`;

  content.appendChild(bubble);
  _renderMediaThumb(msg, _caseId, bubble);
  content.appendChild(ts);
  wrap.appendChild(content);

  // Annotation flag button (only for messages with a DB id)
  if (msg.id) {
    const ann = _annotations.get(msg.id);
    const flagBtn = document.createElement("button");
    flagBtn.className = "ann-flag-btn" + (ann ? " has-ann" : "");
    flagBtn.title = ann ? `${ann.tag}${ann.note ? ": " + ann.note : ""}` : "Annotate";
    flagBtn.textContent = ann ? "★" : "☆";
    flagBtn.dataset.msgId = msg.id;
    flagBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      _openAnnotationPanel(flagBtn, msg, _caseId);
    });
    wrap.appendChild(flagBtn);

    // If annotated, add tag badge
    if (ann) {
      const badge = document.createElement("span");
      badge.className = `ann-tag-badge ann-tag-${ann.tag.toLowerCase()}`;
      badge.textContent = ann.tag.replace(/_/g, " ");
      wrap.appendChild(badge);
    }
  }

  return wrap;
}

// ── Annotations ───────────────────────────────────────────────────────────────

function _openAnnotationPanel(flagBtn, msg, caseId) {
  // Close any existing open panel
  document.querySelectorAll(".ann-panel").forEach(p => p.remove());

  const tpl = document.getElementById("tpl-annotation-panel");
  const panel = tpl.content.cloneNode(true).querySelector(".ann-panel");
  const ann = _annotations.get(msg.id);

  const select = panel.querySelector(".ann-tag-select");
  const noteInput = panel.querySelector(".ann-note-input");
  const saveBtn = panel.querySelector(".ann-save-btn");
  const deleteBtn = panel.querySelector(".ann-delete-btn");
  const cancelBtn = panel.querySelector(".ann-cancel-btn");

  if (ann) {
    select.value = ann.tag;
    noteInput.value = ann.note || "";
    deleteBtn.style.display = "";
  }

  saveBtn.addEventListener("click", async () => {
    const tag = select.value;
    const note = noteInput.value.trim();
    try {
      const res = await fetch(`/api/cases/${caseId}/annotations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: msg.id, tag, note }),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = await res.json();
      _annotations.set(msg.id, updated);
      _refreshBubbleAnnotation(flagBtn, updated);
      panel.remove();
    } catch (err) {
      alert(`Failed to save annotation: ${err.message}`);
    }
  });

  deleteBtn.addEventListener("click", async () => {
    const existing = _annotations.get(msg.id);
    if (!existing) { panel.remove(); return; }
    try {
      const res = await fetch(`/api/cases/${caseId}/annotations/${existing.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      _annotations.delete(msg.id);
      _refreshBubbleAnnotation(flagBtn, null);
      panel.remove();
    } catch (err) {
      alert(`Failed to delete: ${err.message}`);
    }
  });

  cancelBtn.addEventListener("click", () => panel.remove());

  // Insert panel below the flag button
  flagBtn.insertAdjacentElement("afterend", panel);
  noteInput.focus();
}

function _refreshBubbleAnnotation(flagBtn, ann) {
  flagBtn.className = "ann-flag-btn" + (ann ? " has-ann" : "");
  flagBtn.textContent = ann ? "★" : "☆";
  flagBtn.title = ann ? `${ann.tag}${ann.note ? ": " + ann.note : ""}` : "Annotate";

  // Remove old badge if present
  const oldBadge = flagBtn.parentElement?.querySelector(".ann-tag-badge");
  if (oldBadge) oldBadge.remove();

  if (ann) {
    const badge = document.createElement("span");
    badge.className = `ann-tag-badge ann-tag-${ann.tag.toLowerCase()}`;
    badge.textContent = ann.tag.replace(/_/g, " ");
    flagBtn.insertAdjacentElement("afterend", badge);
  }
}

// ── Search ────────────────────────────────────────────────────────────────────

function _wireDateJump() {
  const dateInput = dom("conv-date-jump");
  if (!dateInput) return;
  dateInput.value = "";
  const fresh = dateInput.cloneNode(true);
  dateInput.parentNode.replaceChild(fresh, dateInput);
  fresh.addEventListener("change", () => {
    const dateStr = fresh.value;
    if (!dateStr) return;
    const target = new Date(dateStr);
    const msgs = dom("conv-messages");
    if (!msgs) return;
    const bubbles = msgs.querySelectorAll(".msg-wrap");
    for (const b of bubbles) {
      const tsEl = b.querySelector(".msg-ts");
      if (!tsEl) continue;
      const ts = tsEl.textContent;
      try {
        const d = new Date(ts);
        if (d >= target) {
          b.scrollIntoView({ behavior: "smooth", block: "start" });
          b.style.outline = "2px solid var(--info)";
          setTimeout(() => b.style.outline = "", 2000);
          return;
        }
      } catch (_) {}
    }
  });
}

function _wireSearch() {
  const input = dom("conv-search");
  if (!input) return;
  input.value = "";
  // Clone to remove any previous listener
  const fresh = input.cloneNode(true);
  input.parentNode.replaceChild(fresh, input);
  fresh.addEventListener("input", _onSearchInput);
}

function _onSearchInput(e) {
  clearTimeout(_searchTimer);
  const q = e.target.value.trim();
  if (!q) {
    _activeQuery = "";
    _renderPlatformPills();
    _renderThreadList(_activePlatform ? _threads.filter(t => t.platform === _activePlatform) : _threads);
    _showEmptyMain();
    return;
  }
  _searchTimer = setTimeout(() => { _activeQuery = q; _search(q); }, 400);
}

async function _search(q) {
  const msgs = dom("conv-messages");
  const header = dom("conv-header");
  if (!msgs || !header) return;

  header.innerHTML = "";
  const title = document.createElement("span");
  title.className = "conv-header-title";
  title.style.color = "var(--text-muted)";
  title.style.fontWeight = "400";
  title.textContent = `Search results for "${q}"`;
  header.appendChild(title);

  msgs.innerHTML = '<p class="muted" style="padding:8px">Searching…</p>';
  try {
    const rows = await apiFetch(`/api/cases/${_caseId}/messages?q=${encodeURIComponent(q)}&limit=100`);
    if (!rows.length) {
      msgs.innerHTML = '<p class="muted" style="padding:8px">No messages matched.</p>';
      return;
    }
    // Update header with result count
    title.textContent = `"${q}" — ${rows.length} result${rows.length !== 1 ? "s" : ""}`;
    _renderMessages(rows, msgs, true);  // showOrigin=true for search results
  } catch (err) {
    msgs.innerHTML = `<p class="muted" style="padding:8px">Search error: ${_escHtml(err.message)}</p>`;
  }
}

// ── Media thumbnail helpers (A4) ──────────────────────────────────────────

function _renderMediaThumb(msg, caseId, container) {
  if (!msg.media_id) return;
  const url    = `/api/cases/${caseId}/media/${msg.media_id}`;
  const mime   = msg.mime_type || "";
  const fname  = msg.media_filename || "attachment";
  const size   = msg.media_size ? ` · ${fmtBytes(msg.media_size)}` : "";

  const wrap = document.createElement("div");
  wrap.className = "msg-media-wrap";

  if (mime.startsWith("image/")) {
    const img = document.createElement("img");
    img.className = "msg-media-thumb";
    img.alt = fname;
    img.dataset.src = url;        // lazy — set by IntersectionObserver
    img.dataset.mediaName = fname;
    img.dataset.mediaType = "image";
    wrap.appendChild(img);
  } else if (mime.startsWith("video/")) {
    const vid = document.createElement("div");
    vid.className = "msg-media-video";
    vid.textContent = "▶";
    vid.dataset.src = url;
    vid.dataset.mediaName = fname;
    vid.dataset.mediaType = "video";
    wrap.appendChild(vid);
  }

  const meta = document.createElement("div");
  meta.className = "msg-media-meta";
  meta.textContent = `${mime.startsWith("image/") ? "🖼" : "📹"} ${fname}${size}`;
  wrap.appendChild(meta);

  container.appendChild(wrap);
}

function _openLightbox(url, name, type) {
  const dlg     = document.getElementById("media-lightbox");
  const content = document.getElementById("media-lightbox-content");
  const metaEl  = document.getElementById("media-lightbox-meta");
  content.innerHTML = type === "video"
    ? `<video src="${url}" controls autoplay></video>`
    : `<img src="${url}" alt="" />`;
  metaEl.textContent = name;
  dlg.showModal();
}

function _initLightbox() {
  const dlg = document.getElementById("media-lightbox");
  if (!dlg) return;
  dlg.querySelector(".media-lightbox-close").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
}

function _lazyLoadImages(container) {
  const els = container.querySelectorAll("[data-src]");
  if (!els.length) return;
  if (_lazyObserver) _lazyObserver.disconnect();
  _lazyObserver = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (!e.isIntersecting) return;
      const el = e.target;
      const url  = el.dataset.src;
      const name = el.dataset.mediaName || "";
      if (el.tagName === "IMG") {
        el.src = url;
        el.addEventListener("click", () => _openLightbox(url, name, "image"));
      } else {
        el.addEventListener("click", () => _openLightbox(url, name, "video"));
      }
      el.removeAttribute("data-src");
      _lazyObserver.unobserve(el);
    });
  }, { rootMargin: "200px" });
  els.forEach(el => _lazyObserver.observe(el));
}

// ── Utilities ─────────────────────────────────────────────────────────────────

let _activeQuery = "";

const _avatarColors = ["#e06c75","#e5c07b","#98c379","#56b6c2","#61afef","#c678dd","#be5046","#d19a66"];
function _avatarColor(name) {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  return _avatarColors[Math.abs(h) % _avatarColors.length];
}
function _initials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? (parts[0][0] + parts[parts.length-1][0]) : name.slice(0, 2);
}

function _escHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _highlightText(text, query) {
  if (!query) return _escHtml(text);
  const escaped = _escHtml(text);
  const qEsc = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return escaped.replace(new RegExp(`(${qEsc})`, "gi"), "<mark>$1</mark>");
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

// Wire lightbox once at module load — type="module" scripts execute after DOM is ready.
_initLightbox();
