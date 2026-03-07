# UI/UX Review: Conversations Tab + Analysis Cards

**Date:** 2026-03-08
**Status:** Complete
**Commits:** `1f06f27` (fixes), `1a470e0` (original feature)
**Tests:** 131 passing

---

## Review Findings

### Bugs Fixed

| # | Bug | Root Cause | Fix |
|---|---|---|---|
| 1 | Conversations tab in wrong position | `old_string` in HTML edit matched Evidence→Analysis gap, not Overview→Evidence | Moved tab button to second position (Overview → **Conversations** → Evidence) |
| 2 | Markdown analysis cards still rendered as pre-wrap text | `.analysis-card-body { white-space: pre-wrap }` (line 94) and `.markdown-output { white-space: normal }` have equal specificity — first rule won | Added `.analysis-card-body.markdown-output { white-space: normal }` (higher specificity wins) |
| 3 | Bubble timestamp showed sender name on outgoing messages | Both branches of `isSent ? sender : sender` were identical | Outgoing bubbles show no sender (it's the device owner); incoming shows `msg.sender` |
| 4 | `initConversations` called with null caseId and silently did nothing | `activeCaseId` guard removed from tab click but null check not added inside the function | Added early-return guard in `initConversations(caseId)` that shows "Open a case first" state |
| 5 | Conversations tab not refreshed when switching cases while tab already active | `initConversations` only called on tab click, never on `openCase` | Added call to `initConversations(id)` inside `openCase` when conversations tab is already `.active` |
| 6 | Stale event listener on search input | `removeEventListener` on anonymous function never removes anything | Replaced with `input.cloneNode(true)` + `replaceChild` to guarantee clean listener on each `initConversations` call |

---

### UX Improvements

#### Platform Identity Colors
All platform pills and thread labels were the same grey/blue, making visual triage slow.

Now each platform has a distinct color applied via `data-platform` attribute CSS selectors — no JS needed:

| Platform | Color | Usage |
|---|---|---|
| WhatsApp | `#25d366` (green) | Pill border/text, thread label, active left-border |
| Telegram | `#29b6f6` (cyan) | Pill border/text, thread label, active left-border |
| Signal | `#9575cd` (purple) | Pill border/text, thread label, active left-border |
| SMS | `#58a6ff` (blue) | Pill border/text, thread label |

#### Thread Active Indicator
Previously: background color change only — subtle, easy to miss.
Now: 3px left border in platform color + background change. The active thread is immediately obvious.

#### Conv-Header Redesign
Previously: plain text string `"WHATSAPP · +97312345678"`.

Now: flex row with three semantic parts:
- **Platform badge** — colored pill (`.conv-header-platform.whatsapp` etc.)
- **Thread name** — flex:1 with text-overflow ellipsis
- **Message count** — muted right-aligned `"N messages"`

#### Search Results Context
Previously: search results showed bubbles with no indication of which thread they came from.

Now: `showOrigin=true` in search mode renders a `.msg-search-origin` line above each bubble showing `platform · thread_id` — essential for a forensics tool where an examiner needs to cite the source.

Search header also updates post-fetch: `"query" — N results`.

#### Analysis Card Collapse Indicator
Previously: clicking the card header toggled collapse but no visual signal indicated the card was collapsible.

Now: `▾` chevron rotates 180° via CSS transition when collapsed:
```css
.analysis-card-chevron { transition: transform 0.2s; }
.analysis-card-header.open .analysis-card-chevron { transform: rotate(180deg); }
```

#### Bubble Wrapper
Previously: inline `style="display:flex; flex-direction:column; align-items:..."` on each bubble wrapper div.

Now: `.msg-wrap.sent` / `.msg-wrap.received` CSS classes — cleaner DOM, easier to override.

#### Empty State
Previously: bare `<p class="muted">` tag with padding inline style.

Now: `.conv-empty-state` with centered layout, large icon (opacity 0.3), and descriptive copy. Separate `_showNoCaseState()` function for when no case is open.

---

## Files Changed

| File | Changes |
|---|---|
| `templates/index.html` | Conversations tab moved to position 2 (after Overview) |
| `static/style.css` | `analysis-card-body.markdown-output` specificity fix; platform color CSS; `msg-wrap` classes; `conv-header` flex layout; `conv-empty-state`; chevron transition |
| `static/js/conversations.js` | null-case guard; `_showNoCaseState()`; `data-platform` on pills/items; styled header builder; `showOrigin` in search; `cloneNode` search listener fix; sender bug fix |
| `static/js/chat.js` | Chevron element added; `open` class toggled on collapse |
| `static/js/cases.js` | Conversations tab click no longer guards on `activeCaseId`; `openCase` refreshes conversations if tab already active |
