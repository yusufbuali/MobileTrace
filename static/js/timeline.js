/**
 * timeline.js — Cross-platform chronological timeline tab (A1).
 */
import { apiFetch } from "./api.js";

let _caseId = null;
let _nextCursor = null;
let _activePlatforms = new Set(); // empty = All

const _PLATFORM_COLORS = {
  sms:      "var(--info)",
  whatsapp: "#25d366",
  telegram: "#0088cc",
  signal:   "#3a76f0",
  calls:    "var(--text-muted)",
  phone:    "var(--text-muted)",
};

export async function initTimeline(caseId) {
  _caseId = caseId;
  _nextCursor = null;
  _activePlatforms = new Set();
  document.getElementById("tl-feed").innerHTML = "";
  _fetchAndRender(true).catch(console.error);
}

function _wirePills() {
  document.querySelectorAll("#tl-platform-pills .tl-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      const plat = btn.dataset.platform;
      if (!plat) {
        _activePlatforms.clear();
        document.querySelectorAll("#tl-platform-pills .tl-pill")
          .forEach(b => b.classList.toggle("active", !b.dataset.platform));
      } else {
        document.querySelector("#tl-platform-pills .tl-pill[data-platform='']")
          .classList.remove("active");
        btn.classList.toggle("active");
        if (btn.classList.contains("active")) {
          _activePlatforms.add(plat);
        } else {
          _activePlatforms.delete(plat);
          if (!_activePlatforms.size) {
            document.querySelector("#tl-platform-pills .tl-pill[data-platform='']")
              .classList.add("active");
          }
        }
      }
      _nextCursor = null;
      document.getElementById("tl-feed").innerHTML = "";
      _fetchAndRender(true).catch(console.error);
    });
  });
}

function _wireDateJump() {
  document.getElementById("tl-date-jump").addEventListener("change", e => {
    const date = e.target.value;
    if (!date) return;
    _nextCursor = { ts: `${date}T00:00:00`, key: "" };
    document.getElementById("tl-feed").innerHTML = "";
    _fetchAndRender(false).catch(console.error);
  });
}

function _wireLoadMore() {
  document.getElementById("tl-load-more").addEventListener("click", () => {
    _fetchAndRender(false).catch(console.error);
  });
}

async function _fetchAndRender(reset) {
  if (!_caseId) return;
  const params = new URLSearchParams({ limit: 100 });
  if (_activePlatforms.size) params.set("platforms", [..._activePlatforms].join(","));
  if (_nextCursor) {
    params.set("cursor_ts",  _nextCursor.ts);
    params.set("cursor_key", _nextCursor.key || "");
  }
  try {
    const data = await apiFetch(`/api/cases/${_caseId}/timeline?${params}`);
    _nextCursor = data.next_cursor || null;
    _renderItems(data.items, reset);
    document.getElementById("tl-load-more-wrap").style.display = _nextCursor ? "" : "none";
  } catch (err) {
    document.getElementById("tl-feed").innerHTML =
      `<div class="tl-empty">Failed to load timeline: ${_esc(err.message)}</div>`;
  }
}

function _renderItems(items, reset) {
  const feed = document.getElementById("tl-feed");
  if (reset) {
    feed.innerHTML = "";
    delete feed.dataset.lastDate;
  }

  if (!items.length && reset) {
    feed.innerHTML = `<div class="tl-empty">No messages in this case yet</div>`;
    return;
  }

  let lastDate = feed.dataset.lastDate || null;

  items.forEach(item => {
    const dateStr = (item.timestamp || "").slice(0, 10);
    if (dateStr !== lastDate) {
      lastDate = dateStr;
      const sep = document.createElement("div");
      sep.className = "tl-date-sep";
      sep.textContent = _formatDateSep(dateStr);
      feed.appendChild(sep);
    }

    const row = document.createElement("div");
    row.className = "tl-row";
    if (item.risk_level) row.classList.add(`tl-risk-${item.risk_level.toLowerCase()}`);

    const color = _PLATFORM_COLORS[item.platform] || "var(--accent)";
    const time  = (item.timestamp || "").slice(11, 16);
    const dir   = item.direction === "incoming" ? "←" : "→";
    const sender = _esc(item.sender || item.recipient || "—");
    const isTruncated = item.type !== "call" && (item.body || "").length > 120;
    const bodyText = item.type === "call"
      ? `📞 Call · ${_fmtDuration(item.duration_seconds)}`
      : _esc((item.body || "").slice(0, 120));

    const badge    = document.createElement("span");
    badge.className = "tl-badge";
    badge.style.cssText = `background:${color}22;color:${color};border-color:${color}44`;
    badge.textContent = item.platform;

    const timeEl  = document.createElement("span");
    timeEl.className = "tl-time";
    timeEl.textContent = time;

    const dirEl   = document.createElement("span");
    dirEl.className = "tl-dir";
    dirEl.textContent = dir;

    const senderEl = document.createElement("span");
    senderEl.className = "tl-sender";
    senderEl.textContent = sender;

    const bodyEl  = document.createElement("span");
    bodyEl.className = "tl-body" + (isTruncated ? " tl-body--truncated" : "");
    bodyEl.textContent = bodyText + (isTruncated ? "…" : "");

    row.append(badge, timeEl, dirEl, senderEl, bodyEl);

    if (item.risk_level) {
      const rb = document.createElement("span");
      rb.className = `tl-risk-badge risk-${item.risk_level.toLowerCase()}`;
      rb.textContent = item.risk_level;
      row.appendChild(rb);
    }

    if (isTruncated) {
      bodyEl.addEventListener("click", e => {
        e.stopPropagation();
        bodyEl.textContent = item.body;
        bodyEl.classList.remove("tl-body--truncated");
      });
    }

    if (item.thread_id && item.type === "message") {
      row.style.cursor = "pointer";
      row.addEventListener("click", () => {
        // Dispatch with bubbles:true so window listener in conversations.js fires
        window.dispatchEvent(new CustomEvent("mt:open-thread", {
          detail: { platform: item.platform, thread: item.thread_id },
          bubbles: true,
        }));
        const convBtn = document.querySelector('.tab-btn[data-tab="tab-conversations"]');
        if (convBtn) convBtn.click();
      });
    }

    feed.appendChild(row);
  });

  feed.dataset.lastDate = lastDate || "";
}

function _formatDateSep(dateStr) {
  try {
    const d = new Date(dateStr + "T12:00:00");
    return d.toLocaleDateString("en-GB", {
      weekday: "long", year: "numeric", month: "long", day: "numeric"
    });
  } catch { return dateStr; }
}

function _fmtDuration(secs) {
  if (!secs) return "—";
  const m = Math.floor(secs / 60), s = secs % 60;
  return m ? `${m}m ${s}s` : `${s}s`;
}

function _esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Wire once at module load — type="module" scripts execute after DOM is ready.
_wirePills();
_wireDateJump();
_wireLoadMore();
