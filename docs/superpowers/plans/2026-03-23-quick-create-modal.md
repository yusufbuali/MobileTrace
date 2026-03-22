# Quick-Create Case Modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the full-page new-case form with a modal overlay that lets users create a case and optionally upload evidence in one step.

**Architecture:** Pure frontend change — three coordinated edits to `index.html` (markup), `style.css` (drop zone + chip styles), and `cases.js` (modal open/close/submit logic). No backend API changes needed; existing `POST /api/cases` and `POST /api/cases/<id>/evidence` endpoints are used as-is.

**Tech Stack:** Vanilla JS ES modules, Flask/Jinja2 templates, plain CSS custom properties (already defined in `style.css`).

---

## File Map

| File | What changes |
|---|---|
| `templates/index.html` | Remove `#view-new-case` div (lines 151–161); add `#modal-new-case` overlay following the existing `#settings-modal` pattern |
| `static/style.css` | Add `.drop-zone`, `.drop-zone--over`, `.file-chip`, and `#modal-new-case` width override (the `.modal-overlay` and `.modal-box` base styles already exist at lines 600–609) |
| `static/js/cases.js` | Remove stale `btnCancel`/`formNewCase` consts and their handlers (lines 14–15, 909–910, 914–929); add `openNewCaseModal()`, `closeNewCaseModal()`, drag-and-drop wiring, new submit handler |

---

## Task 1 — HTML: swap the full-page form for a modal

**Files:**
- Modify: `templates/index.html:151–161` (remove), insert new modal before `</div><!-- #app -->` closing or right after `#settings-modal`

- [ ] **Step 1: Remove the `#view-new-case` div**

In `templates/index.html`, delete lines 151–161 (the entire `<div id="view-new-case" class="view">…</div>` block):

```html
<!-- DELETE THIS ENTIRE BLOCK -->
<div id="view-new-case" class="view">
  <h2>New Case</h2>
  <p class="muted" style="margin-bottom:16px">Create the case first, then upload evidence from the Evidence tab.</p>
  <form id="form-new-case">
    <label>Case Number <input name="case_number" type="text" /></label>
    <label>Officer Name <input name="officer" type="text" /></label>
    <label>Title * <input name="title" type="text" required /></label>
    <button type="submit" class="btn-primary">Create Case</button>
    <button type="button" id="btn-cancel-case">Cancel</button>
  </form>
</div>
```

- [ ] **Step 2: Add `#modal-new-case` after the existing `#settings-modal` closing tag (after line 92)**

Insert immediately after `</div><!-- /settings-modal -->`:

```html
<!-- New case modal -->
<div id="modal-new-case" class="modal-overlay" style="display:none" role="dialog" aria-modal="true" aria-label="New Case">
  <div class="modal-box" id="modal-new-case-box">
    <div class="modal-header">
      <h3>New Case</h3>
      <button id="btn-new-case-close" class="modal-close" aria-label="Close">&times;</button>
    </div>
    <form id="form-new-case">
      <label>Case Title *
        <input id="new-case-title" name="title" type="text" required
               placeholder="e.g. Ahmad Khaled — iPhone 14" autocomplete="off" />
      </label>

      <div class="form-field">
        <div class="form-label">Evidence File
          <span class="form-label-hint">(optional — add later from the Evidence tab)</span>
        </div>
        <div id="new-case-drop-zone" class="drop-zone" role="button" tabindex="0"
             aria-label="Drop evidence file or click to browse">
          <div class="drop-zone-icon">&#128194;</div>
          <div class="drop-zone-main">Drop evidence here</div>
          <div class="drop-zone-browse">or <span class="link">click to browse</span></div>
          <div class="drop-zone-hint">.ufdr &middot; .zip &middot; .ofb &middot; .xrep &middot; .tar</div>
          <input id="new-case-file-input" type="file"
                 accept=".ufdr,.xrep,.zip,.ofb,.tar"
                 style="display:none" />
        </div>
        <div id="new-case-file-chip" class="file-chip" style="display:none">
          <span class="file-chip-icon">&#128196;</span>
          <span id="new-case-file-name" class="file-chip-name"></span>
          <span id="new-case-file-size" class="file-chip-size"></span>
          <button type="button" id="btn-new-case-remove-file" class="file-chip-remove" aria-label="Remove file">&times;</button>
        </div>
      </div>

      <details id="new-case-details">
        <summary class="form-details-toggle">&#9656; More details (case number, officer)</summary>
        <div class="form-details-body">
          <label>Case Number <input name="case_number" type="text" /></label>
          <label>Officer Name <input name="officer" type="text" /></label>
        </div>
      </details>

      <div id="new-case-error" class="form-error" style="display:none"></div>

      <div class="modal-actions">
        <button type="button" id="btn-new-case-cancel" class="btn-secondary">Cancel</button>
        <button type="submit" id="btn-new-case-submit" class="btn-primary">Create Case</button>
      </div>
    </form>
  </div>
</div>
```

- [ ] **Step 3: Verify HTML renders without errors**

Start the Flask dev server (if not running):
```bash
cd "C:/claudecode projects/AIFT-final-1/MobileTrace"
python -m flask run --port 5000
```

Open `http://localhost:5000` — the page should load with no console errors. The sidebar "+ New Case" button exists. The old new-case view is gone.

- [ ] **Step 4: Commit**

```bash
cd "C:/claudecode projects/AIFT-final-1/MobileTrace"
git add templates/index.html
git commit -m "feat(ui): replace view-new-case page with quick-create modal HTML"
```

---

## Task 2 — CSS: drop zone + file chip styles

**Files:**
- Modify: `static/style.css` — append new rules at end of file

The existing `.modal-overlay` and `.modal-box` at lines 600–609 already handle the overlay and box. We only need the new inner components.

- [ ] **Step 1: Append new CSS rules to `static/style.css`**

Add at the very end of `static/style.css`:

```css
/* ── Quick-create modal ─────────────────────────────────────────────────── */

#modal-new-case .modal-box { width: 480px; }

.form-field { display: flex; flex-direction: column; gap: 6px; }
.form-label { font-size: 0.8rem; font-weight: 600; color: var(--text-muted); }
.form-label-hint { font-weight: 400; font-size: 0.75rem; color: var(--text-muted); opacity: 0.7; }

.drop-zone {
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  color: var(--text-muted);
}
.drop-zone:hover,
.drop-zone:focus { border-color: var(--accent); outline: none; }
.drop-zone--over { border-color: var(--accent); background: rgba(59,130,246,0.06); }
.drop-zone-icon { font-size: 1.6rem; margin-bottom: 4px; }
.drop-zone-main { font-size: 0.85rem; }
.drop-zone-browse { font-size: 0.78rem; margin-top: 3px; }
.drop-zone-browse .link { color: var(--accent); text-decoration: underline; cursor: pointer; }
.drop-zone-hint { font-size: 0.7rem; margin-top: 6px; opacity: 0.55; }

.file-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(34,197,94,0.08);
  border: 1px solid rgba(34,197,94,0.25);
  border-radius: var(--radius);
  padding: 8px 12px;
}
.file-chip-icon { font-size: 1rem; flex-shrink: 0; }
.file-chip-name { font-size: 0.82rem; color: #86efac; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.file-chip-size { font-size: 0.72rem; color: var(--text-muted); flex-shrink: 0; }
.file-chip-remove { background: none; border: none; color: var(--text-muted); font-size: 1.1rem; cursor: pointer; padding: 0 2px; line-height: 1; flex-shrink: 0; }
.file-chip-remove:hover { color: var(--text); }

#new-case-details { margin-top: 4px; }
#new-case-details summary.form-details-toggle {
  cursor: pointer;
  font-size: 0.78rem;
  color: var(--text-muted);
  list-style: none;
  user-select: none;
}
#new-case-details summary.form-details-toggle::-webkit-details-marker { display: none; }
.form-details-body { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }

.form-error { color: #f87171; font-size: 0.8rem; padding: 6px 0; }
```

- [ ] **Step 2: Verify styles render correctly**

Reload `http://localhost:5000`, click "+ New Case" — the modal should appear (even without JS wired yet) since the overlay exists in the DOM. Inspect that `.drop-zone` looks right. (The modal won't open yet — that's Task 3.)

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat(ui): add drop-zone and file-chip CSS for new-case modal"
```

---

## Task 3 — JS: modal open/close/submit logic

**Files:**
- Modify: `static/js/cases.js:13–15` (remove stale consts), `:909–929` (remove old handlers, add new ones)

- [ ] **Step 1: Remove stale `btnCancel` and `formNewCase` consts**

In `static/js/cases.js`, delete lines 14–15:

```js
// DELETE THESE TWO LINES:
const btnCancel = document.getElementById("btn-cancel-case");
const formNewCase = document.getElementById("form-new-case");
```

- [ ] **Step 2: Remove old new-case event listeners**

Delete lines 909–929 (the old `btnNewCase` click, `btnCancel` click, and `formNewCase` submit handlers):

```js
// DELETE ALL OF THIS:
btnNewCase?.addEventListener("click", () => showView("view-new-case"));
btnCancel?.addEventListener("click", () => showView("view-dashboard"));
// ...
formNewCase?.addEventListener("submit", async (e) => {
  // ...
});
```

- [ ] **Step 3: Add the new modal logic in place of the deleted block**

At the same location (after the `filterStatus` change listener, before the sidebar toggle section), insert:

```js
// ── New case modal ────────────────────────────────────────────────────────────

const modalNewCase   = document.getElementById("modal-new-case");
const formNewCase    = document.getElementById("form-new-case");
const dropZone       = document.getElementById("new-case-drop-zone");
const fileInput      = document.getElementById("new-case-file-input");
const fileChip       = document.getElementById("new-case-file-chip");
const fileChipName   = document.getElementById("new-case-file-name");
const fileChipSize   = document.getElementById("new-case-file-size");
const btnRemoveFile  = document.getElementById("btn-new-case-remove-file");
const btnSubmitNew   = document.getElementById("btn-new-case-submit");
const newCaseError   = document.getElementById("new-case-error");

let _pendingFile = null;

function _setFile(file) {
  _pendingFile = file;
  fileChipName.textContent = file.name;
  fileChipSize.textContent = fmtBytes(file.size);
  fileChip.style.display = "flex";
  dropZone.style.display = "none";
  btnSubmitNew.textContent = "Create & Start Parsing \u2192";
}

function _clearFile() {
  _pendingFile = null;
  fileInput.value = "";
  fileChip.style.display = "none";
  dropZone.style.display = "";
  btnSubmitNew.textContent = "Create Case";
}

function openNewCaseModal() {
  formNewCase.reset();
  _clearFile();
  newCaseError.style.display = "none";
  newCaseError.textContent = "";
  document.getElementById("new-case-details").removeAttribute("open");
  modalNewCase.style.display = "flex";
  document.getElementById("new-case-title").focus();
  document.addEventListener("keydown", _onEscape);
}

function closeNewCaseModal() {
  modalNewCase.style.display = "none";
  document.removeEventListener("keydown", _onEscape);
}

function _onEscape(e) {
  if (e.key === "Escape") closeNewCaseModal();
}

// Backdrop click closes modal
modalNewCase?.addEventListener("click", (e) => {
  if (e.target === modalNewCase) closeNewCaseModal();
});

document.getElementById("btn-new-case-close")?.addEventListener("click", closeNewCaseModal);
document.getElementById("btn-new-case-cancel")?.addEventListener("click", closeNewCaseModal);

btnNewCase?.addEventListener("click", openNewCaseModal);

// Drop zone — click to browse
dropZone?.addEventListener("click", () => fileInput.click());
dropZone?.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") fileInput.click(); });
fileInput?.addEventListener("change", () => { if (fileInput.files[0]) _setFile(fileInput.files[0]); });
btnRemoveFile?.addEventListener("click", _clearFile);

// Drop zone — drag and drop
dropZone?.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("drop-zone--over"); });
dropZone?.addEventListener("dragleave", () => dropZone.classList.remove("drop-zone--over"));
dropZone?.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drop-zone--over");
  const file = e.dataTransfer.files[0];
  if (file) _setFile(file);
});

// Submit
formNewCase?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(formNewCase);
  const body = {
    title: fd.get("title").trim(),
    officer: (fd.get("officer") || "").trim() || undefined,
    case_number: (fd.get("case_number") || "").trim() || undefined,
  };

  newCaseError.style.display = "none";
  btnSubmitNew.disabled = true;
  const origLabel = btnSubmitNew.textContent;
  btnSubmitNew.textContent = "Creating\u2026";

  let newCase;
  try {
    newCase = await api.createCase(body);
  } catch (err) {
    newCaseError.textContent = "Failed to create case: " + err.message;
    newCaseError.style.display = "block";
    btnSubmitNew.disabled = false;
    btnSubmitNew.textContent = origLabel;
    return;
  }

  if (_pendingFile) {
    btnSubmitNew.textContent = "Uploading\u2026";
    try {
      const uploadFd = new FormData();
      uploadFd.append("file", _pendingFile);
      await fetch(`/api/cases/${newCase.id}/evidence`, { method: "POST", body: uploadFd });
    } catch (_) {
      // Case created — navigate in, show toast about upload failure
      allCases.unshift(newCase);
      activeCaseId = newCase.id;
      filterCases();
      closeNewCaseModal();
      openCase(newCase.id);
      showToast("Case created. Evidence upload failed — try again from the Evidence tab.", "error");
      btnSubmitNew.disabled = false;
      btnSubmitNew.textContent = origLabel;
      return;
    }
  }

  allCases.unshift(newCase);
  activeCaseId = newCase.id;
  filterCases();
  closeNewCaseModal();
  openCase(newCase.id);
  btnSubmitNew.disabled = false;
  btnSubmitNew.textContent = origLabel;
});
```

- [ ] **Step 4: Verify modal works end-to-end**

1. Reload `http://localhost:5000`
2. Click **+ New Case** — modal opens, title field is focused
3. Press **Escape** — modal closes
4. Open modal again, type a title, click **Cancel** — modal closes, no case created
5. Open modal, type a title, click **Create Case** — modal closes, new case opens in the sidebar
6. Open modal, type a title, drop a `.zip` or `.ufdr` file — drop zone becomes file chip, button reads "Create & Start Parsing →"
7. Click the × on the chip — file removed, drop zone returns
8. Submit with file — modal shows "Creating…" then "Uploading…", then closes and navigates into the new case

- [ ] **Step 5: Run the backend test suite to check for regressions**

```bash
cd "C:/claudecode projects/AIFT-final-1/MobileTrace"
python -m pytest tests/test_cases_routes.py tests/test_evidence_upload.py tests/test_app.py -v
```

Expected: all tests pass. These tests exercise the Flask API endpoints; no frontend test changes are needed since the API surface is unchanged.

- [ ] **Step 6: Commit**

```bash
git add static/js/cases.js
git commit -m "feat(ui): wire quick-create modal — open/close/drop-zone/submit"
```

---

## Final Verification Checklist

Run these manually against `http://localhost:5000` once all three tasks are complete:

- [ ] `+ New Case` opens modal (not a full-page view)
- [ ] Escape and Cancel both close modal without creating a case
- [ ] Title-only submit creates case and navigates to it
- [ ] File drop updates chip + button label
- [ ] File chip × removes the file
- [ ] Submit with file: creates case + uploads (check Network tab: two POST requests)
- [ ] Case number + officer in "More details" are sent when filled
- [ ] Existing cases in sidebar open correctly (no regression)
- [ ] Evidence tab upload on an existing case still works
- [ ] `python -m pytest tests/ -x -q` passes
