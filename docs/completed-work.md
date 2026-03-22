# MobileTrace — Completed Work Log

> Summary of all implementation phases, for review.

---

## Phase 1: UI Foundation (completed)

**Plan:** `docs/plans/2026-03-08-ui-phase1-foundation.md`
**Commits:** `dfbfdcb` → `ff09516`

| Task | Description | Files Changed |
|------|-------------|---------------|
| Light/Dark Mode | Theme toggle with `[data-theme]` CSS vars, persisted in localStorage | `style.css`, `cases.js`, HTML |
| Responsive Layout | Mobile sidebar toggle, grid breakpoints at 1024/768px | `style.css`, `cases.js`, HTML |
| Accessibility | Semantic HTML (`<nav>`, `<main>`, `<section>`), ARIA labels, roles | HTML templates, JS |
| Toast Notifications | Replaced all `alert()` calls with styled slide-in toasts | `cases.js`, `style.css` |
| SVG Brand Icon | Sidebar brand icon, active case state polish | `cases.js`, `style.css` |
| Typography & Micro-animations | Font sizing, transitions on hover/focus, subtle motion | `style.css` |

---

## Phase 2: Upload Feedback (completed)

**Plan:** `docs/plans/2026-03-08-ui-phase2-upload-feedback.md`
**Commits:** `6ba1d61` → `cb18589` + `af15c2e`

| Task | Description | Files Changed |
|------|-------------|---------------|
| Drag-and-Drop Upload | Drop zone with visual feedback, toast on success/error | `cases.js`, `style.css` |
| File Type Icons | SVG icons per evidence format (XML, JSON, CSV, etc.) | `cases.js`, `style.css` |
| Upload Progress Bar | XHR-based progress tracking with animated fill bar | `cases.js`, `style.css` |

---

## Analysis Tab Upgrade (completed)

**Plan:** `docs/plans/2026-03-08-analysis-tab-aift-upgrade.md`
**Commits:** `3d6d019` → `126fed9`

| Task | Description | Files Changed |
|------|-------------|---------------|
| Radar Progress Header | Animated radar icon with sweep, shimmer bar, state transitions | `chat.js`, `style.css` |
| AIFT Results View | Executive summary + collapsible per-artifact details panels | `chat.js`, `style.css`, HTML |
| JSON Normalizer | Maps inconsistent LLM field names to canonical schema | `chat.js` |
| Risk Cards | Thread cards with risk bars, scores, key indicators | `chat.js`, `style.css` |
| Key Findings | Finding blocks with jump links to conversation threads | `chat.js`, `conversations.js` |
| Analysis Preview Panel | Artifact selection checkboxes, start/cancel flow | `chat.js`, `style.css`, HTML |
| Preview API | `/analysis/preview` endpoint with per-artifact record counts | `routes/analysis.py` |
| Artifact Filter + Cancel | POST artifacts array filter, SSE cancel event | `routes/analysis.py` |
| Code Cleanup | Removed dead code, fixed listener leak, consolidated queries | `chat.js` |

---

## Analysis Quality (completed)

**Plans:** `2026-03-08-analysis-human-readable.md`, `2026-03-08-analysis-rtl-arabic.md`
**Commits:** `5491f4c` → `f638eef`

| Task | Description | Files Changed |
|------|-------------|---------------|
| Strict JSON Schema | Enforced structured output in all analysis LLM prompts | prompt templates |
| JSON Normalization | Schema aliasing and fallback for inconsistent LLM responses | `chat.js` |
| RTL Arabic Support | Auto-detects RTL text (Hebrew/Arabic), applies `dir="rtl"` | `chat.js` |

---

## Phase 3: Content Enhancement (completed)

**Plan:** `docs/plans/2026-03-08-ui-phase3-content-enhancement.md`
**Commits:** `86e2b84`, `db67528`

| # | Task | Description | Files Changed |
|---|------|-------------|---------------|
| 1 | Search Highlighting | `<mark>` tags wrap query matches in message bubbles with gold background | `conversations.js`, `style.css` |
| 2 | User Avatars | Colored initials circles (deterministic hash) next to each message | `conversations.js`, `style.css` |
| 3 | Stats Icons & Device Card | SVG icons on stat cards, device info card header redesign | `cases.js`, `style.css` *(done in prior session)* |
| 4 | AI Typing Indicator | Three bouncing dots animation replaces static "Analysing…" text | `chat.js`, `style.css` |
| 5 | Rich Citations | Numbered `[1]` badges, platform labels, truncated message snippets | `chat.js`, `style.css` |
| 6 | Top Insights Summary | Insights bar with artifact count, thread count, risk badge, platforms | `chat.js`, `style.css` |

### Phase 3 — Technical Details

**Search Highlighting (Task 1)**
- `_activeQuery` tracks current search term globally
- `_highlightText()` escapes HTML then wraps regex matches in `<mark>`
- Query cleared on thread open or search input clear
- Uses `innerHTML` only when highlighting is active; `textContent` otherwise

**User Avatars (Task 2)**
- `_avatarColor()` — deterministic color from 8-color palette via hash
- `_initials()` — first+last initials for multi-word names, first two chars for single
- Layout changed: `msg-wrap` now uses `flex-direction: row` with avatar + content wrapper
- Sent messages use `row-reverse` to keep avatar on the right

**AI Typing Indicator (Task 4)**
- CSS-only animation: `typing-bounce` keyframes with staggered delays (0, 0.15s, 0.3s)
- Three 6px dots with `translateY(-6px)` bounce

**Rich Citations (Task 5)**
- `_renderCitations()` now accepts optional `citations` array from API response
- Each citation shows `[n]` badge (absolute positioned), platform, and body snippet (120 chars max)
- Falls back to count-only text when no citations array is provided

**Analysis Insights Bar (Task 6)**
- Prepended to `analysis-results-view` as `.analysis-insights-bar`
- Aggregates: artifact count, total threads across all artifacts, highest risk level, detected platforms
- Platform detection from thread_id substring matching (whatsapp/telegram/signal/sms)

---

## Phase 4: Advanced Features (completed)

**Plan:** `docs/plans/2026-03-08-ui-phase4-advanced-features.md`
**Commits:** `96529cc`, `1881311`, `019097a`

| # | Task | Description | Files Changed |
|---|------|-------------|---------------|
| 1 | Interactive Citations / Jump | Clickable thread IDs in analysis jump to conversations tab | `chat.js`, `conversations.js`, `cases.js` *(done in prior session)* |
| 2 | Date Jump | HTML5 date input in conversations sidebar, scrolls to first message on/after selected date | `index.html`, `conversations.js`, `style.css` |
| 3 | Timeline Sparkline | SVG polyline showing message volume by day on the overview tab | `cases.js`, `style.css` |
| 4 | Export Analysis | "Export Markdown" button generates a `.md` file with risk tables, findings, and key messages via Blob download | `chat.js`, `index.html` |
| 5 | Case Grouping | Sidebar cases grouped by status (open/in_review/on_hold/closed) in collapsible `<details>` sections | `cases.js`, `style.css` |

### Phase 4 — Technical Details

**Date Jump (Task 2)**
- `_wireDateJump()` clones input to remove stale listeners, adds `change` handler
- Iterates `.msg-wrap` elements, parses `.msg-ts` text, scrolls to first match >= target date
- Blue outline highlight for 2 seconds on matched message

**Timeline Sparkline (Task 3)**
- `_loadSparkline()` fetches up to 500 messages, groups by day (`timestamp.slice(0,10)`)
- Generates SVG `<polyline>` with normalized coordinates (200x40 viewBox)
- Appended as a `stat-card-spark` spanning 2 grid columns

**Export Analysis (Task 4)**
- Iterates analysis rows, builds Markdown with risk summary, CRA table, key findings + quoted messages
- Creates Blob with `type: "text/markdown"`, triggers download via temporary anchor element

**Case Grouping (Task 5)**
- `renderCases()` now groups by status using predefined order: open > in_review > on_hold > closed
- Each group is a `<details open>` with status badge and count in the summary
- Preserved ARIA attributes (`role="button"`, `aria-pressed`, `tabindex`) and keyboard navigation

---

## Folder Auto-Discovery & Import (completed)

**Commit:** `8ec3f2b`

| Component | Description | Files Changed |
|-----------|-------------|---------------|
| FolderParser | New parser that scans directories for forensic databases and archives | `app/parsers/folder_parser.py` (new) |
| Scan API | `POST /api/cases/<id>/evidence/scan` — walks folder, returns discovered files | `app/routes/cases.py` |
| Import API | `POST /api/cases/<id>/evidence/import-folder` — imports selected archives and platform DBs | `app/routes/cases.py` |
| Folder Scan UI | "Folder Scan" tab in evidence upload panel with scan form, results list, checkboxes, and import button | `templates/index.html`, `static/js/cases.js`, `static/style.css` |
| Path Security | `_allowed_evidence_path()` shared helper validates paths against whitelist | `app/routes/cases.py` |

### Folder Auto-Discovery — Technical Details

**FolderParser (`app/parsers/folder_parser.py`)**
- `scan_folder(folder)` — single `os.walk` pass with filename-keyed dict lookups for performance on large (30GB+) directories
- Detects archive files by extension: `.ufdr`, `.tar`, `.zip`, `.xrep`, `.ofb`
- Matches Android databases by filename + path pattern (e.g., `mmssms.db` in `com.android.providers.telephony`)
- Matches iOS databases by filename + path pattern (e.g., `sms.db` in `HomeDomain/Library/SMS`)
- iOS suffix targets handle app container UUID paths (WhatsApp, Telegram)
- Returns structured dict: `{ archives: [...], platforms: { android: { databases: [...] }, ios: { databases: [...] } } }`

**Parser Reuse (no code duplication)**
- `_parse_android()` instantiates `AndroidParser`, calls its `_read_sms()`, `_read_whatsapp()`, `_read_contacts()`, `_read_telegram()`, `_read_signal()`, `_read_calls()`
- `_parse_ios()` instantiates `iOSParser`, calls its `_read_sms()`, `_read_contacts()`, `_read_calls()`, `_read_whatsapp()`, `_read_telegram_ios()`
- Returns `ParsedCase` objects compatible with existing `_store_parsed()` pipeline

**API Endpoints**
- Scan endpoint validates folder path against whitelist (`_allowed_evidence_path`), returns discoveries
- Import endpoint accepts `{ folder_path, archives: [paths], platforms: [names], signal_key }`, processes archives via `dispatch()` and platforms via `FolderParser.parse()`
- Both endpoints enforce path security: `/opt/mobiletrace/evidence`, `/opt/aift/evidence`, or `cases_dir/../evidence`

**UI Flow**
- "Folder Scan" tab appears alongside "File Upload" and "Local Path" modes
- User enters folder path → clicks Scan → results shown with checkboxes grouped by archives and platforms (Android/iOS)
- Each item shows file name, size (human-readable), and format/label
- Select All checkbox in header toggles all items
- Selection count updates dynamically: "N items selected"
- Import button sends selected items to import-folder endpoint
- Success/error feedback via toast notifications, evidence list reloads on completion

---

## Analysis Prompts: Crime Detection Tags + Anti-Hallucination (completed)

**Plan:** `docs/plans/2026-03-07-analysis-llm-integration.md`

| # | Task | Description | Files Changed |
|---|------|-------------|---------------|
| 1 | System Prompt Rewrite | Added anti-hallucination evidence standards, 12-category crime taxonomy, expanded risk scale with crime-type examples, data coverage awareness | `prompts/system_prompt.md` |
| 2 | Data Coverage Metadata | Each artifact now prepends a `## Data Coverage` header with records provided vs total count and percentage | `app/analyzer.py` |
| 3 | Artifact Prompt Updates | All 6 prompts updated with `crime_indicators` schema, `confidence` field on key_findings, `data_coverage` in JSON output, crime indicator detection section | `prompts/sms_analysis.md`, `prompts/whatsapp_analysis.md`, `prompts/telegram_analysis.md`, `prompts/signal_analysis.md`, `prompts/call_log_analysis.md`, `prompts/contacts_analysis.md` |
| 4 | Chat System Prompt | Enhanced with anti-hallucination rules, observed/inferred distinction, crime category references | `app/routes/chat.py` |

### Anti-Hallucination — Evidence Standards (7 rules)
1. Report ONLY what is literally present — never invent, embellish, or assume
2. Every claim must cite exact timestamp, sender/recipient, and direct quote
3. Classify findings as `observed` (directly visible) or `inferred` (pattern-based)
4. State "Insufficient data to determine [X]" when data is insufficient
5. Do not assume investigation context or suspect identity
6. For media messages (empty body), report only that media was exchanged
7. Do not paraphrase in ways that change meaning — quote verbatim

### Crime Category Taxonomy (12 categories)
`DRUG_TRAFFICKING`, `CSAM_GROOMING`, `TERRORISM`, `HUMAN_TRAFFICKING`, `MONEY_LAUNDERING`, `FRAUD`, `CYBER_CRIME`, `ORGANIZED_CRIME`, `WEAPONS`, `DOMESTIC_VIOLENCE`, `STALKING`, `SEXUAL_OFFENSE`

Each category includes detection heuristics (coded language examples, behavioral patterns). Tags require at least one specific message citation with timestamp and quote.

### New JSON Schema Fields (additive — no breaking changes)
- `crime_indicators[]` — array of `{ category, confidence, severity, evidence_refs[], summary }`
- `key_findings[].confidence` — `"observed"` or `"inferred"`
- `data_coverage` — `{ records_analyzed, total_records, coverage_percent, note }`

### Platform-Specific Notes
- **WhatsApp/Telegram/Signal**: "Encrypted platform choice alone is NOT an indicator"
- **Call Logs**: "Call metadata alone cannot confirm content. Mark all call-derived indicators as `inferred`"
- **Contacts**: "Contact records alone rarely establish crime. Only tag explicitly criminal references. Mark as `inferred`"

### Data Coverage in analyzer.py
- Added `SELECT COUNT(*)` queries for messages (per platform), call_logs, and contacts
- Prepends `## Data Coverage\nRecords provided: N of M total (X.Y%)` to each artifact's formatted data string
- LLM sees the coverage header and can populate the `data_coverage` JSON field accordingly

---

## Forensic Intelligence Dashboard — Overview Tab (completed 2026-03-08)

**Plan:** `docs/plans/` (inline plan, implemented in single session)

Surfaces AI analysis intelligence directly on the Overview tab so investigators get an immediate risk picture without navigating to the Analysis tab.

| Task | Description | Files Changed |
|------|-------------|---------------|
| Backend summary endpoint | `GET /api/cases/<id>/analysis/summary` — aggregates all analysis_results rows into overall risk level, crime categories, top risk threads, data coverage, artifact list | `app/routes/analysis.py` |
| HTML containers | 4 new `div`s in `#tab-overview`: `#dash-intel-banner`, `#dash-crime-cats`, `#dash-top-threads`, `#dash-coverage` | `templates/index.html` |
| CSS widget styles | Risk-level color classes, crime category chips (severity backgrounds), thread cards with platform badges, coverage progress bars | `static/style.css` |
| JavaScript renderer | `_loadAnalysisSummary()` + `_artifactLabel()` + `_crimeCatLabel()` helpers; fire-and-forget call added to `_loadStats()` | `static/js/cases.js` |

### Widget Behaviour
- **Intel Banner** — always visible; shows `—` placeholder if no analysis run yet, otherwise shows `CRITICAL / HIGH / MEDIUM / LOW / NONE` with color-coded border and summary chips (artifacts analyzed, crime categories, high-risk threads ≥ 7)
- **Crime Categories** — hidden until data; chips sorted by severity descending with confidence badge
- **High-Risk Threads** — hidden until data; shows threads with `risk_score ≥ 5`, risk bar, platform badge, up to 2 key indicators
- **Data Coverage** — hidden until data; progress bars per artifact showing records analyzed vs total

### Backend Logic (`_RISK_RANK`)
- `CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1` — overall risk is the max rank across all artifacts
- Crime categories deduplicated by `category` key; highest-confidence entry wins per category
- `top_risk_threads` sorted by `risk_score` descending, capped at 5; sourced from `conversation_risk_assessment[]` in each artifact's JSON result
- `_safe_json_parse` reused from same file — no new imports needed

---

## Global Forensic Dashboard (completed 2026-03-08)

**New files:** `app/routes/dashboard.py`, `static/js/dashboard.js`
**Modified:** `app/__init__.py`, `templates/index.html`, `static/style.css`, `static/js/cases.js`

| Component | Description |
|-----------|-------------|
| `GET /api/dashboard/stats` | Aggregates KPIs, risk distribution, status pipeline, crime categories, recent activity, cases table — all from DB in one call |
| KPI cards | 4-up grid: Total Cases, High-Risk Cases, Crime Indicators, Total Artifacts — reuse existing `.stat-card` classes |
| Risk doughnut chart | Chart.js 4 doughnut, 5 levels (CRITICAL→NOT_ANALYZED), reads CSS vars for colors/grid |
| Status pipeline bar | Horizontal bar chart: Open / In Review / On Hold / Closed |
| Crime categories bar | Horizontal bar, top 12 categories; empty-state text if no analysis yet |
| Recent activity feed | Union of evidence imports, analysis completions, case creations; relative timestamps ("2h ago") |
| Sortable cases table | Click-to-open rows, sortable headers (all columns), sticky header, risk badges |
| Home button | Sidebar button returns to dashboard from any view, re-fetches stats |
| Boot behaviour | App now opens to dashboard instead of blank welcome screen |
| Cancel → dashboard | New-case form Cancel returns to dashboard, not welcome screen |
| CSS | ~170 lines `.gdb-*` classes + `.btn-home`; responsive (stacks to 1-col at ≤900px) |
| Theme support | Chart colors read from `getComputedStyle` CSS vars; adapts to light/dark toggle |

---

## IOC Extraction — Intelligence Tab (completed 2026-03-21)

**Plan:** `docs/plans/2026-03-21-ioc-extraction.md`
**New files:** `app/ioc_extractor.py`, `app/routes/ioc.py`, `static/js/ioc.js`, `tests/test_ioc_extractor.py`, `tests/test_ioc_routes.py`
**Modified:** `app/__init__.py`, `templates/index.html`, `static/js/cases.js`, `static/style.css`

| Component | Description |
|-----------|-------------|
| `app/ioc_extractor.py` | Pure Python regex IOC extractor; `extract_iocs(messages, contacts, ioc_type_filter)` → `{summary, iocs}` |
| IOC types | phone, email, url, crypto (BTC/ETH addresses), ip (public only), gps |
| `_is_private_ip()` | Full 4-octet integer validation for RFC1918 ranges; filters 10/8, 172.16-31/12, 192.168/16, 127/8, 169.254/16 |
| Deduplication | `(type, value)` keyed dict; first 5 source messages stored per IOC |
| `by_type` summary | Computed from all IOCs before type filter; filter only affects `iocs` list and `total` |
| `GET /api/cases/<id>/ioc?type=` | Queries messages + contacts, returns extractor result + `case_id` |
| Intelligence tab | New tab in SPA; summary bar with type counts, filter pills, sortable table |
| Cross-tab jump | IOC row "Jump" button dispatches `mt:jump-to-thread` → cases.js → conversations.js opens thread |
| CSV export | Downloads all IOCs as RFC-4180 CSV with quoted values |
| Tests | 19 extractor unit tests + 6 route tests |

---

## Evidence Annotations (completed 2026-03-21)

**Plan:** `docs/plans/2026-03-21-evidence-annotations.md`
**New files:** `app/routes/annotations.py`, `tests/test_annotations_routes.py`
**Modified:** `app/database.py`, `app/__init__.py`, `templates/index.html`, `static/js/conversations.js`, `static/style.css`

| Component | Description |
|-----------|-------------|
| `annotations` DB table | `id TEXT PK`, `case_id`, `message_id FK`, `tag`, `note`, `created_at`; CASCADE delete |
| Indexes | `idx_annotations_case`, `idx_annotations_message` |
| `POST /api/cases/<id>/annotations` | Creates annotation; validates `message_id` belongs to `case_id`; DELETE+INSERT upsert pattern |
| `GET /api/cases/<id>/annotations` | Returns all annotations with joined message fields |
| `PATCH /api/cases/<id>/annotations/<ann_id>` | Updates tag/note with single dynamic UPDATE |
| `DELETE /api/cases/<id>/annotations/<ann_id>` | Removes annotation |
| Valid tags | KEY_EVIDENCE, SUSPICIOUS, ALIBI, EXCULPATORY, NOTE |
| Conversations UI | ☆/★ flag button per message bubble; click opens annotation panel (select+textarea+Save/Delete/Cancel) |
| HTML report | "Annotated Evidence" section between conversation excerpts and AI analysis |
| Tests | 12 route tests covering all CRUD + validation + cross-case ownership |

---

## PDF Export (completed 2026-03-21)

**Plan:** `docs/plans/2026-03-21-pdf-export.md`
**Modified:** `app/routes/reports.py`, `templates/report.html`, `requirements.txt`, `Dockerfile`, `static/js/cases.js`, `templates/index.html`

| Component | Description |
|-----------|-------------|
| `_build_report_context()` | Shared helper extracted from `get_report()`; used by both HTML and PDF endpoints |
| `GET /api/cases/<id>/report/pdf` | WeasyPrint server-side render; graceful 500 if WeasyPrint/GTK not available |
| Deferred import | `import weasyprint` inside handler with `try/except (ImportError, OSError)` |
| Print CSS | `@media print` block: white bg, black text, `page-break-inside: avoid` on panels |
| `@page` | A4 size, 15mm margins; `@bottom-center` page counter via WeasyPrint paged media |
| Safe filename | Alphanumeric-only sanitization of case title for `Content-Disposition` header |
| UI button | "📄 PDF" button in top bar; `href` set on `openCase()`, hidden until case loaded |
| Dockerfile | `apt-get install` block for libgobject, libcairo2, libpango, libpangoft2, etc. |
| requirements.txt | `weasyprint>=60.0` added |

---

## Correlation Tab — Contact Network Graph (completed 2026-03-09)

**New files:** `app/routes/correlation.py`, `static/js/correlation.js`
**Modified:** `app/__init__.py`, `templates/index.html`, `static/style.css`, `static/js/cases.js`

| Component | Description |
|-----------|-------------|
| `GET /api/cases/<id>/correlation` | Aggregates messages + calls + contacts + analysis results into node/link graph, timeline, heatmap, stats |
| Phone normalization | `_norm_phone()` strips WhatsApp JIDs, keeps last 10 digits for cross-platform identity merging |
| Risk coloring | LLM `conversation_risk_assessment` and `crime_indicators` propagate to nodes/links |
| D3 force graph | `d3@7.9` force-directed graph; node size ∝ interaction count; DEVICE node always centered |
| Drag + zoom/pan | Draggable nodes; scroll-to-zoom; Reset View button resets to `d3.zoomIdentity` |
| Platform filters | Pill toggles (SMS/WhatsApp/etc) dim non-matching nodes + links |
| Risk filters | Pill toggles (CRITICAL/HIGH/MEDIUM/LOW) filter by risk level |
| Inspector panel | Click node → right panel shows name, risk badge, platform icons, stats, crime categories, last 30 events |
| Hour heatmap | 24-bar CSS bar chart showing message volume by hour of day |
| Day-of-week heatmap | 7-bar CSS bar chart (Mon–Sun) |
| Stats bar | 4 KPI chips: Total Contacts, High-Risk, Cross-Platform, Total Interactions |
| Cross-platform merging | Same phone number in WhatsApp + SMS shown as one node with both platform icons |
| CSS | ~160 lines `.corr-*` classes; responsive at ≤900px |

## Feature Pack 2 (completed 2026-03-21)
- **C3** Encrypted contact recovery — iOS/Android parsers recover contacts from WhatsApp/Telegram/SMS metadata when AddressBook is empty; tagged `source='recovered'`
- **A1** Timeline tab — chronological cross-platform feed with platform filter pills, date jump, cursor pagination, cross-tab navigation
- **A4** Media thumbnails — image/video thumbnails inline in conversation bubbles with lazy loading, lightbox, and streaming media route

## Quick-Create Case Modal (completed 2026-03-23)

**Spec:** `docs/superpowers/specs/2026-03-23-quick-create-modal-design.md`
**Plan:** `docs/superpowers/plans/2026-03-23-quick-create-modal.md`
**Commits:** `b89af6f` → `7600cc3`

| Change | Description | Files |
|--------|-------------|-------|
| HTML | Replaced `#view-new-case` full-page form with `#modal-new-case` overlay; drop zone, file chip, "More details" collapsible | `templates/index.html` |
| CSS | Added `.drop-zone`, `.drop-zone--over`, `.file-chip`, `#modal-new-case .modal-box` width override | `static/style.css` |
| JS | Removed stale `btnCancel`/`formNewCase` consts and old handlers; added `openNewCaseModal()`, `closeNewCaseModal()`, drag-and-drop, two-step create+upload submit with loading states | `static/js/cases.js` |

**Behaviour:** `+ New Case` opens a modal overlay (stays on dashboard). Title is the only required field. Optional evidence drop zone — file attached changes button to "Create & Start Parsing →". Submit creates the case and optionally uploads the file before navigating directly into the new case. Escape/Cancel/backdrop click all close without creating.
