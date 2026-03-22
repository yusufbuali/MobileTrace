# Quick-Create Case Modal — Design Spec

## Problem

The current "new case" flow navigates away to a full-page form (`view-new-case`), then the user must navigate again to the Evidence tab to upload a file. Two navigation hops before any real work begins. The form also surfaces optional fields (Case Number, Officer Name) at the same level as the required Title, adding visual noise.

## Solution

Replace the full-page new-case view with a **modal overlay** that:
1. Requires only a case title to proceed
2. Includes an optional evidence drop zone — file upload and case creation happen in one click
3. Collapses non-essential metadata under "More details"
4. After creation, navigates directly into the new case

---

## Scope

**In scope:**
- Replace `view-new-case` full-page view with a modal
- Add optional file drop zone to the modal
- "More details" collapsible for Case Number and Officer Name
- Dynamic submit button label: "Create & Start Parsing →" vs "Create Case"
- Post-creation navigation: jump directly to new case Overview tab

**Out of scope:**
- Changes to evidence parsing logic
- Multi-file upload
- Auto-naming from filename (can be a follow-up)
- Drag-to-dashboard global drop zone

---

## UI Behaviour

### Opening the modal
- Clicking `+ New Case` opens the modal as an overlay on the dashboard (backdrop blur + dark scrim)
- Clicking Cancel or pressing Escape closes it without creating a case
- The existing `view-new-case` `<div>` is removed from the DOM

### Required field
- **Case Title** — `<input type="text" required>`, auto-focused on open
- Placeholder: `e.g. Ahmad Khaled — iPhone 14`

### Evidence drop zone (optional)
- Appears below the Title field
- Label: `Evidence File` with a muted inline note `(optional — add later)`
- Empty state: dashed border, drop icon, "Drop evidence here / or click to browse", accepted formats hint (`.ufdr · .zip · .ofb · .xrep · .tar`)
- Filled state: replace drop zone with a file-attached chip showing filename + size, with an ✕ to remove
- Accepts same formats as the existing evidence upload: `.ufdr`, `.zip`, `.ofb`, `.xrep`, `.tar`

### "More details" collapsible
- Collapsed by default — shows a `▶ More details (case number, officer)` toggle link
- When expanded, reveals: `Case Number` text input + `Officer Name` text input
- These are purely optional; form submits fine without them

### Submit button
- **No file selected:** `Create Case`
- **File selected:** `Create & Start Parsing →`
- On submit: POST `/api/cases` with title/officer/case_number, then if a file was selected, immediately POST to `/api/cases/<new_id>/evidence` with the file
- Both requests are triggered before the modal closes

### After creation
- Modal closes
- App navigates to the new case (`openCase(newCaseId)`)
- If a file was uploaded, the Overview tab shows parsing progress — no need to visit the Evidence tab

### Error handling
- If case creation fails: show an inline error message inside the modal (do not close it)
- If file upload fails: case was already created — navigate to it and show a toast: "Case created. Evidence upload failed — try again from the Evidence tab."

---

## Implementation Notes

### Files to change
| File | Change |
|---|---|
| `templates/index.html` | Remove `#view-new-case` div; add `#modal-new-case` overlay |
| `static/style.css` | Add modal styles: backdrop, box, drop zone states |
| `static/js/cases.js` | Replace `showView("view-new-case")` with `openNewCaseModal()`; add drag-and-drop handler + file state; update submit logic |

### Key JS changes
- Remove the `formNewCase` const (currently `document.getElementById("form-new-case")`) and its `submit` event listener (lines ~914–929 in `cases.js`) — the old form is gone.
- Remove the `btnCancel` const (`#btn-cancel-case`) and its `click` handler that calls `showView("view-dashboard")` — the modal handles its own cancel.
- `btnNewCase` click → `openNewCaseModal()` instead of `showView("view-new-case")`.
- `openNewCaseModal()` shows `#modal-new-case`, sets focus on title input, wires up drag-and-drop, binds Escape key to `closeNewCaseModal()`.
- The cancel button inside the new modal must close it via `closeNewCaseModal()` (use any element ID, but update the JS to match).
- Submit handler:
  1. Disable submit button, show spinner / "Creating…" text.
  2. `POST /api/cases` → get `newId`.
  3. If file selected: `POST /api/cases/<newId>/evidence` (multipart). Keep button disabled + show "Uploading…" during this step.
  4. Re-enable button and close modal only after both requests complete (or on error — see error handling above).
- `closeNewCaseModal()` hides modal, resets form state (clears title, drops file, collapses "More details").

### CSS requirements
- `.modal-backdrop`: fixed, full-screen, `background: rgba(0,0,0,0.7)`, `backdrop-filter: blur(4px)`
- `.modal-box`: centred, max-width 480px, `background: #1e293b`, border-radius 12px
- `.drop-zone`: dashed border, transitions to solid blue on drag-over
- `.file-chip`: green-tinted background, filename + size + remove button

---

## Acceptance Criteria

1. Clicking `+ New Case` opens the modal — no full-page navigation
2. Pressing Escape or clicking Cancel closes the modal; no case is created
3. Submitting with only a title creates a case and opens it
4. Dropping a file updates the drop zone to the file chip; the submit button reads "Create & Start Parsing →"
5. Submitting with a file creates the case AND starts the upload before the modal closes
6. "More details" toggle expands/collapses the extra fields; their values are sent on submit if filled
7. If creation fails, an error appears inside the modal (it stays open)
8. Post-creation navigation lands on the new case's Overview tab
9. No regression checklist:
   - Existing cases open correctly from the sidebar and dashboard table
   - Evidence tab upload (file form, path import, folder scan) still functions on open cases
   - Back-navigation to the dashboard still works
