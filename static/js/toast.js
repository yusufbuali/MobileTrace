/**
 * toast.js — Lightweight toast notification system for MobileTrace.
 */

let _container = null;

function _getContainer() {
  if (_container) return _container;
  _container = document.createElement("div");
  _container.id = "toast-container";
  document.body.appendChild(_container);
  return _container;
}

/**
 * Show a toast notification.
 * @param {string} message - Text to display
 * @param {"success"|"error"|"info"|"warning"} [type="info"] - Toast type
 * @param {number} [duration=4000] - Auto-dismiss time in ms
 */
export function showToast(message, type = "info", duration = 4000) {
  const container = _getContainer();
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  const close = document.createElement("button");
  close.className = "toast-close";
  close.innerHTML = "&times;";
  close.addEventListener("click", () => _dismiss(toast));
  toast.appendChild(close);

  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast-visible"));

  if (duration > 0) {
    setTimeout(() => _dismiss(toast), duration);
  }
}

function _dismiss(toast) {
  if (!toast || toast.dataset.dismissing) return;
  toast.dataset.dismissing = "1";
  toast.classList.remove("toast-visible");
  toast.addEventListener("transitionend", () => toast.remove(), { once: true });
  setTimeout(() => toast.remove(), 400);
}
