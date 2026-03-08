/**
 * Settings modal — configure AI provider, API key, and model.
 * For OpenRouter: fetches model list with pricing from the backend.
 */
import { apiFetch } from "./api.js";

function dom(id) { return document.getElementById(id); }

const DEFAULT_MODELS = {
  claude:     "claude-sonnet-4-6",
  openai:     "gpt-4o",
  openrouter: "anthropic/claude-sonnet-4-5",
  local:      "llama3.1:8b",
};

const MODEL_HINTS = {
  claude:     "e.g. claude-sonnet-4-6, claude-opus-4-6",
  openai:     "e.g. gpt-4o, gpt-4o-mini",
  local:      "e.g. llama3.1:8b, mistral:7b",
};

let _cfg = null;          // cached config from server
let _creditsSnapshot = null; // { remaining, usage } captured before analysis
let _lastCredits = null;     // { remaining, usage } from last fetch

// ── Sidebar credits widget ────────────────────────────────────────────────────

export function snapshotCredits() {
  _creditsSnapshot = _lastCredits;
}

export async function refreshCredits() {
  const widget = document.getElementById("sidebar-credits");
  if (!widget || widget.style.display === "none") return;

  try {
    const data = await apiFetch("/api/settings/openrouter-credits");
    if (data.error) return;

    _lastCredits = { remaining: data.remaining, usage: data.usage };

    const remainEl = document.getElementById("credits-remaining");
    if (remainEl) {
      remainEl.textContent = data.remaining == null
        ? "Unlimited"
        : `$${Number(data.remaining).toFixed(4)}`;
    }

    // Show session cost delta if a snapshot was taken before analysis
    if (_creditsSnapshot != null && data.remaining != null && _creditsSnapshot.remaining != null) {
      const delta = _creditsSnapshot.remaining - data.remaining;
      if (delta > 0) {
        const costEl = document.getElementById("credits-session-cost");
        const costValue = document.getElementById("credits-cost-value");
        if (costEl) costEl.style.display = "";
        if (costValue) costValue.textContent = `$${delta.toFixed(4)}`;
      }
    }
  } catch (_) {
    // silently fail — sidebar widget is non-critical
  }
}

// ── Status ────────────────────────────────────────────────────────────────────

function setStatus(msg, color = "") {
  const el = dom("settings-status");
  if (!el) return;
  el.textContent = msg;
  el.style.color = color || "var(--text)";
}

// ── Model field: text vs dropdown ─────────────────────────────────────────────

function _showTextModel(provider) {
  dom("settings-model-select").style.display = "none";
  dom("settings-model").style.display = "";
  dom("btn-load-models").style.display = "none";
  dom("settings-model-hint").textContent = MODEL_HINTS[provider] || "";
}

function _showDropdownModel() {
  dom("settings-model-select").style.display = "";
  dom("settings-model").style.display = "none";
  dom("btn-load-models").style.display = "";
  dom("settings-model-hint").textContent = "";
}

// ── OpenRouter model list ─────────────────────────────────────────────────────

function _fmtPrice(p) {
  if (p === 0) return "free";
  if (p < 0.01) return `$${p.toFixed(4)}/M`;
  return `$${p.toFixed(3)}/M`;
}

function _fmtCtx(n) {
  if (!n) return "";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ctx`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K ctx`;
  return `${n} ctx`;
}

async function loadOpenRouterModels(selectedId) {
  const sel = dom("settings-model-select");
  sel.innerHTML = '<option value="">Loading…</option>';
  setStatus("Fetching model list from OpenRouter…", "var(--text-muted)");

  try {
    const models = await apiFetch("/api/settings/openrouter-models");
    sel.innerHTML = "";

    // Group: free / cheap (<$1/M prompt) / mid / expensive
    const groups = [
      { label: "Free models", filter: m => m.prompt_per_m === 0 },
      { label: "Budget (< $1 / 1M tokens)", filter: m => m.prompt_per_m > 0 && m.prompt_per_m < 1 },
      { label: "Standard ($1–$5 / 1M tokens)", filter: m => m.prompt_per_m >= 1 && m.prompt_per_m < 5 },
      { label: "Premium (> $5 / 1M tokens)", filter: m => m.prompt_per_m >= 5 },
    ];

    let anyAdded = false;
    for (const grp of groups) {
      const items = models.filter(grp.filter);
      if (!items.length) continue;
      const og = document.createElement("optgroup");
      og.label = grp.label;
      for (const m of items) {
        const opt = document.createElement("option");
        opt.value = m.id;
        const ctx = _fmtCtx(m.context_length);
        const cost = `in ${_fmtPrice(m.prompt_per_m)} · out ${_fmtPrice(m.completion_per_m)}`;
        opt.textContent = `${m.name}  [${ctx}  ${cost}]`;
        if (m.id === selectedId) opt.selected = true;
        og.appendChild(opt);
        anyAdded = true;
      }
      sel.appendChild(og);
    }

    if (!anyAdded) {
      sel.innerHTML = '<option value="">No models returned</option>';
    } else if (!selectedId || !sel.value) {
      // Default selection: first anthropic model or first overall
      const anthropicOpt = [...sel.options].find(o => o.value.startsWith("anthropic/claude-sonnet"));
      if (anthropicOpt) anthropicOpt.selected = true;
    }

    setStatus("");
  } catch (err) {
    sel.innerHTML = '<option value="">Failed to load — check API key</option>';
    setStatus(`Could not fetch models: ${err.message}`, "var(--danger)");
  }
}

// ── Load settings from server ─────────────────────────────────────────────────

async function loadSettings() {
  try {
    _cfg = await apiFetch("/api/settings");
    const provider = _cfg?.ai?.provider || "claude";
    _applyProviderToForm(provider, /* fetchModels */ provider === "openrouter");
  } catch (_) {
    setStatus("Could not load settings.", "var(--danger)");
  }
}

async function _applyProviderToForm(provider, fetchModels = false) {
  dom("settings-provider").value = provider;

  const provCfg = _cfg?.ai?.[provider] || {};
  const savedModel = provCfg.model || DEFAULT_MODELS[provider] || "";

  const keyEl = dom("settings-api-key");
  if (keyEl) {
    keyEl.value = "";
    keyEl.placeholder = provCfg.api_key ? "Key set (enter new to change)" : "No key configured";
  }

  const baseUrlEl = dom("settings-base-url");
  if (baseUrlEl) baseUrlEl.value = provCfg.base_url || "";

  dom("settings-local-url-row").style.display =
    (provider === "local" || provider === "openrouter") ? "" : "none";

  // Show/hide credit check button (in modal)
  const credBtn = dom("btn-check-credits");
  if (credBtn) credBtn.style.display = provider === "openrouter" ? "" : "none";

  // Show/hide sidebar credits widget
  const sidebarCredits = document.getElementById("sidebar-credits");
  if (sidebarCredits) {
    const show = provider === "openrouter";
    sidebarCredits.style.display = show ? "" : "none";
    if (show) refreshCredits();
  }

  if (provider === "openrouter") {
    _showDropdownModel();
    if (fetchModels) {
      await loadOpenRouterModels(savedModel);
    } else {
      // Show placeholder without fetching yet
      const sel = dom("settings-model-select");
      sel.innerHTML = `<option value="${savedModel}">${savedModel} (click Load models)</option>`;
    }
  } else {
    _showTextModel(provider);
    dom("settings-model").value = savedModel;
  }
}

// ── Open / close ──────────────────────────────────────────────────────────────

function openModal() {
  dom("settings-modal").style.display = "flex";
  setStatus("");
  loadSettings();
}

function closeModal() {
  _dismissCreditsPopup();
  dom("settings-modal").style.display = "none";
}

// ── Save ──────────────────────────────────────────────────────────────────────

async function saveSettings(e) {
  e.preventDefault();
  const provider = dom("settings-provider").value;
  const apiKey = dom("settings-api-key").value;
  const baseUrl = dom("settings-base-url").value;

  // Read model from whichever control is visible
  const isOpenRouter = provider === "openrouter";
  const model = isOpenRouter
    ? dom("settings-model-select").value
    : dom("settings-model").value;

  const body = { ai: { provider, [provider]: {} } };
  if (model) body.ai[provider].model = model;
  if (baseUrl) body.ai[provider].base_url = baseUrl;
  if (apiKey.trim()) body.ai[provider].api_key = apiKey.trim();

  try {
    await apiFetch("/api/settings", { method: "POST", body: JSON.stringify(body) });
    setStatus("Settings saved.", "var(--accent-hover)");
    dom("settings-api-key").value = "";
    await loadSettings();
  } catch (err) {
    setStatus(`Save failed: ${err.message}`, "var(--danger)");
  }
}

// ── Test connection ────────────────────────────────────────────────────────────

async function testProvider() {
  setStatus("Testing…", "var(--text-muted)");
  try {
    const result = await apiFetch("/api/settings/test");
    if (result.status === "ok") {
      setStatus(`OK — ${result.provider} · ${result.model} · ${result.latency_ms}ms`, "var(--accent-hover)");
    } else {
      setStatus(`Error: ${result.error}`, "var(--danger)");
    }
  } catch (err) {
    setStatus(`Test failed: ${err.message}`, "var(--danger)");
  }
}

// ── Check OpenRouter credits ──────────────────────────────────────────────────

function _dismissCreditsPopup() {
  document.getElementById("credits-popup-overlay")?.remove();
}

async function checkCredits() {
  const btn = dom("btn-check-credits");
  if (!btn) return;
  const orig = btn.textContent;
  btn.textContent = "Checking…";
  btn.disabled = true;

  try {
    const data = await apiFetch("/api/settings/openrouter-credits");
    if (data.error) {
      setStatus(data.error, "var(--danger)");
      return;
    }

    const fmtDollars = (v) => v == null ? "—" : `$${Number(v).toFixed(2)}`;
    const limitStr = data.limit == null ? "Unlimited" : fmtDollars(data.limit);
    const remainStr = data.limit == null ? "Pay-as-you-go" : fmtDollars(data.remaining);

    // Build popup
    _dismissCreditsPopup();
    const overlay = document.createElement("div");
    overlay.id = "credits-popup-overlay";
    overlay.className = "credits-popup-overlay";
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) _dismissCreditsPopup();
    });

    const popup = document.createElement("div");
    popup.className = "credits-popup";
    popup.innerHTML = `
      <button class="credits-popup-close" title="Close">&times;</button>
      <h4>OpenRouter Credits</h4>
      <div class="credits-popup-row"><span class="credits-popup-label">Usage</span><span class="credits-popup-value">${fmtDollars(data.usage)}</span></div>
      <div class="credits-popup-row"><span class="credits-popup-label">Limit</span><span class="credits-popup-value">${limitStr}</span></div>
      <div class="credits-popup-row"><span class="credits-popup-label">Remaining</span><span class="credits-popup-value">${remainStr}</span></div>
      <div class="credits-popup-row"><span class="credits-popup-label">Free tier</span><span class="credits-popup-value">${data.is_free_tier ? "Yes" : "No"}</span></div>
      ${data.label ? `<div class="credits-popup-row"><span class="credits-popup-label">Key label</span><span class="credits-popup-value">${data.label}</span></div>` : ""}
    `;
    popup.querySelector(".credits-popup-close").addEventListener("click", _dismissCreditsPopup);

    overlay.appendChild(popup);
    document.querySelector(".modal-box").appendChild(overlay);
  } catch (err) {
    setStatus(`Credit check failed: ${err.message}`, "var(--danger)");
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
  }
}

// ── Wire up ───────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  dom("btn-settings")?.addEventListener("click", openModal);
  dom("btn-settings-close")?.addEventListener("click", closeModal);
  dom("settings-modal")?.addEventListener("click", (e) => {
    if (e.target === dom("settings-modal")) closeModal();
  });
  dom("form-settings")?.addEventListener("submit", saveSettings);
  dom("btn-test-provider")?.addEventListener("click", testProvider);
  dom("btn-check-credits")?.addEventListener("click", checkCredits);
  dom("btn-credits-refresh")?.addEventListener("click", refreshCredits);
  dom("btn-load-models")?.addEventListener("click", () => {
    const sel = dom("settings-model-select");
    const current = sel.value;
    loadOpenRouterModels(current);
  });
  dom("settings-provider")?.addEventListener("change", (e) => {
    setStatus("");
    _applyProviderToForm(e.target.value, e.target.value === "openrouter");
  });
});
