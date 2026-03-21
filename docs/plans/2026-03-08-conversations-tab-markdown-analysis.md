# Plan: Conversations Tab + AIFT-Style Analysis Rendering

**Date:** 2026-03-08
**Status:** Complete
**Commit:** `1a470e0`
**Tests:** 131 passing (6 new)

---

## Background

Two usability gaps existed after the AI analysis integration (2026-03-07):

1. **Messages were invisible in the UI.** The overview showed a count (e.g. 86 messages) but there was no way to browse, search, or read them — they only appeared in the HTML court report.
2. **Analysis cards rendered raw pre-wrap text.** The LLM already produced structured markdown (risk tables, severity headers, bullet findings), but `loadAnalysisResults()` called `_escapeHtml()` inside a `white-space: pre-wrap` div, throwing away all formatting.

AIFT's UI already solved both problems. This plan ports those patterns to MobileTrace.

---

## What Was Built

### Task 1 — Backend: Conversations API (`app/routes/cases.py`)

Two new routes added at the bottom of `bp_cases`:

**`GET /api/cases/<case_id>/threads`**

Returns conversation summaries grouped by platform + thread, for the sidebar.
Uses `COALESCE(thread_id, CASE WHEN direction='incoming' THEN sender ELSE recipient END)` to derive a thread key when `thread_id` is NULL.

```json
[
  {"platform": "whatsapp", "thread": "+97312345678", "message_count": 24, "last_ts": "…"},
  {"platform": "sms",      "thread": "+96655551234", "message_count": 32, "last_ts": "…"}
]
```

**`GET /api/cases/<case_id>/messages`**

Returns messages with optional query parameters:
- `?platform=whatsapp` — filter by platform
- `?thread=+97312345678` — filter by thread (matches `thread_id` or derived sender/recipient)
- `?q=Hello` — FTS5 full-text search via `messages_fts` (reuses `_sanitize_fts_query` from `app/retriever.py`)
- `?limit=200&offset=0` — pagination (max 500)

Returns fields: `id, platform, direction, sender, recipient, body, timestamp, thread_id`

---

### Task 2 — Frontend: Conversations Tab

**`templates/index.html`**

- Added `<button class="tab-btn" data-tab="tab-conversations">Conversations</button>` between Overview and Evidence tabs.
- Added tab panel with `.conv-layout` grid (260px sidebar + flexible main area):
  - Sidebar: search input, platform pills, thread list
  - Main: header + scrollable message view
- Added `<script type="module" src="/static/js/conversations.js"></script>`

**`static/js/conversations.js`** (new, ~170 lines)

Key exports: `initConversations(caseId)` — called from `cases.js` on tab click.

Key internal functions:
- `_loadThreads()` — fetches `/threads`, renders platform pills + thread list
- `_renderPlatformPills()` — "All" + one pill per platform; clicking filters the thread list
- `_openThread(platform, thread)` — fetches `/messages?platform=&thread=&limit=200`, renders chat bubbles
- `_renderBubble(msg)` — `msg-sent` (outgoing, right-aligned) vs `msg-received` (incoming, left-aligned); empty body shows `[media / attachment]` in italic
- `_search(q)` — fetches `/messages?q=`, renders flat results; debounced 400ms; clearing input returns to thread view

**`static/js/cases.js`**

- Added `import { initConversations } from "./conversations.js"`
- Added `if (btn.dataset.tab === "tab-conversations" && activeCaseId) { initConversations(activeCaseId); }` in the tab-click handler

---

### Task 3 — Markdown Renderer (`static/js/markdown.js`)

New self-contained module (~180 lines), ported from `AIFT-DEPLOYMENT-2/static/js/analysis.js`.

**Exports:**

```javascript
export function markdownToFragment(text)          // full block renderer → DocumentFragment
export function renderInlineMarkdown(text)         // inline: bold, italic, code, severity badges
export function highlightConfidenceTokens(text)   // CRITICAL/HIGH/MEDIUM/LOW → colored <span>
```

Block elements supported: headings (h1–h6), tables (with header/separator detection), ordered lists, unordered lists, fenced code blocks (` ``` `), paragraphs.

Inline elements supported: `**bold**`, `__bold__`, `*italic*`, `_italic_`, `` `code` ``, severity tokens.

No imports required — `_escapeHtml` is inlined.

---

### Task 4 — Analysis Cards Upgrade (`static/js/chat.js`)

`loadAnalysisResults()` was rewritten to use DOM construction instead of `innerHTML` template strings:

```javascript
import { markdownToFragment, highlightConfidenceTokens } from "./markdown.js";
```

Changes per card:
- **Body:** `body.className = "analysis-card-body markdown-output"` + `body.appendChild(markdownToFragment(r.result))`
- **Header:** `_extractConfidence(r.result)` scans the result text for the first severity token (CRITICAL/HIGH/MEDIUM/LOW) and renders a `confidence-inline` badge next to the provider/date metadata.

---

### Task 5 — CSS (`static/style.css`)

Appended two blocks before the gear-button styles:

**Markdown output** (`.markdown-output`):
- Overrides `white-space: pre-wrap` from `.analysis-card-body`
- Styles for h1–h4, table/th/td, ul/ol/li, p, pre, code within the card body

**Confidence badges** (`.confidence-inline`):
- `.confidence-critical` — dark red bg, `#ff6b6b` text
- `.confidence-high` — dark amber bg, `#e3b341` text
- `.confidence-medium` — dark blue bg, `var(--info)` text
- `.confidence-low` — dark green bg, `#3fb950` text

**Conversations layout** (`.conv-layout` and friends):
- 260px sidebar + fluid main using CSS grid
- Thread items, platform pills, message bubbles (`.msg-sent`, `.msg-received`)
- Height: `calc(100vh - 240px)` to fill available space below the tab bar

---

### Task 6 — Tests (`tests/test_conversations_routes.py`)

6 new smoke tests:

| Test | What it checks |
|---|---|
| `test_threads_returns_grouped` | `/threads` returns 2 groups (whatsapp + sms), correct fields |
| `test_messages_returns_all` | `/messages` returns all 3 seeded rows with expected fields |
| `test_messages_platform_filter` | `?platform=sms` returns only the 1 SMS message |
| `test_messages_search` | `?q=Hello` returns rows containing "Hello" |
| `test_threads_nonexistent_case` | Non-existent case ID → 404 |
| `test_messages_nonexistent_case` | Non-existent case ID → 404 |

---

## Files Changed

| File | Type | Summary |
|---|---|---|
| `app/routes/cases.py` | Modified | +2 routes: `/threads`, `/messages` |
| `static/js/markdown.js` | New | Self-contained markdown renderer |
| `static/js/conversations.js` | New | Conversations tab logic |
| `static/js/chat.js` | Modified | Import markdown.js; DOM-based analysis cards |
| `static/js/cases.js` | Modified | Import + wire initConversations |
| `templates/index.html` | Modified | Conversations tab button + panel + script tag |
| `static/style.css` | Modified | markdown-output, confidence badges, conv-layout |
| `tests/test_conversations_routes.py` | New | 6 smoke tests |

---

## Test Results

```
131 passed, 9 warnings in 11.11s
```

Previous baseline: 125 passing. Net new: 6 tests, zero regressions.
