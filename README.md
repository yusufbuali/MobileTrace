# MobileTrace

**AI-powered mobile forensics analysis platform for law enforcement**

MobileTrace parses forensic extractions from seized mobile devices, normalizes evidence into a structured database, runs LLM-driven crime-indicator analysis, and produces court-ready reports — all from a self-hosted web interface.

---

## Features

### Evidence Import
- **Cellebrite UFDR**, XRY, Oxygen Forensics, Android TAR/ZIP, iOS filesystem images
- Auto-format detection — drop any supported archive and the parser figures it out
- Folder scanning to bulk-import multiple evidence files at once
- Extracts SMS/MMS, WhatsApp, Telegram, Signal (detected), call logs, contacts, and media

### AI-Powered Analysis
- Pluggable AI providers: **Claude** (Anthropic), **OpenAI**, **OpenRouter**, or a local **Ollama** model
- Structured JSON analysis output with a strict schema per artifact type
- **12-category crime taxonomy**: drug trafficking, CSAM, terrorism, human trafficking, money laundering, fraud, cyber crime, organised crime, weapons, domestic violence, stalking, sexual offences
- Anti-hallucination prompts — citations, timestamps, and direct quotes required; no inference beyond the data
- Risk scoring: CRITICAL (9–10) · HIGH (7–8) · MEDIUM (5–6) · LOW (3–4) · MINIMAL (1–2)
- Parallel multi-model runs with per-run result tracking
- Real-time progress via SSE with per-artifact completion status and cancel support

### Investigation Workflow
- **Case management** — create, track status (open / in review / on hold / closed), assign officer and case number
- **Conversations tab** — searchable message threads across all platforms with sender avatars and platform badges
- **Timeline** — chronological cross-platform event feed with risk-level filtering
- **Chat** — per-case investigator chatbot backed by FTS5 full-text search over messages and contacts
- **Annotations** — tag messages as key evidence and add investigator notes
- **IOC extraction** — deduplicated phone numbers, emails, URLs, and crypto addresses across all data
- **Correlation** — entity linkage graph connecting numbers, names, and handles across conversations

### Reporting
- **HTML report** — executive summary, device info, conversation excerpts, analysis results, evidence timeline
- **PDF export** — WeasyPrint-rendered, print-styled, page-break-aware document suitable for court submission
- **Linkage graph** — JSON graph data for entity-relationship visualisation

### UI
- Single-page application — no page reloads, instant tab switching
- Quick-create modal — title + optional evidence drop zone in one overlay, no multi-step wizard
- Light / dark theme with localStorage persistence
- RTL support for Arabic and Hebrew content
- Fully keyboard-navigable with ARIA labels

---

## Quick Start

### Docker Compose (recommended)

```bash
git clone https://github.com/yusufbuali/MobileTrace.git
cd MobileTrace

# Configure your AI provider (see Configuration below)
cp config.yaml.example config.yaml   # or edit config.yaml directly

docker-compose up --build
```

Open **http://localhost:5001** in your browser.

> The `docker-compose.yml` bind-mounts `./app`, `./templates`, and `./static` into the container, so code changes take effect immediately without a rebuild.

### Local Development

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m flask run --host=0.0.0.0 --port=5001
```

---

## Configuration

Edit `config.yaml` before starting:

```yaml
ai:
  provider: openrouter     # claude | openai | openrouter | local

  claude:
    api_key: "sk-ant-..."
    model: "claude-sonnet-4-6"

  openai:
    api_key: "sk-..."
    model: "gpt-4o"

  openrouter:
    api_key: "sk-or-v1-..."
    base_url: "https://openrouter.ai/api/v1"
    model: "anthropic/claude-sonnet-4-5"

  local:
    base_url: "http://localhost:11434/v1"
    model: "llama3.1:8b"
    api_key: "not-needed"

server:
  port: 5001
  host: "0.0.0.0"
  max_upload_mb: 2048
  database_path: "data/mobiletrace.db"
  cases_dir: "data/cases"
```

**Environment variable overrides** (useful in Docker):

| Variable | Description |
|---|---|
| `MOBILETRACE_DB_PATH` | Path to the SQLite database |
| `MOBILETRACE_CASES_DIR` | Directory for parsed case data |
| `FLASK_DEBUG` | Set to `1` for hot-reload |

AI provider and API keys can also be changed at runtime from the **Settings** panel in the UI — no restart required.

---

## Supported Evidence Formats

| Extension | Source |
|---|---|
| `.ufdr` | Cellebrite UFDR (Universal Forensic Data Report) |
| `.tar` | Android data partition (`data/data/` structure) |
| `.zip` | Magnet Acquire or similar container |
| `.xrep` | XRY report |
| `.ofb` | Oxygen Forensics backup |

**Extracted artifacts:** SMS/MMS · WhatsApp messages & contacts · Telegram messages · Call logs · Contacts · iOS iMessage · Media file references

---

## Architecture

```
MobileTrace/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── database.py          # SQLite layer (FTS5, schema, migrations)
│   ├── analyzer.py          # Parallel LLM analysis engine
│   ├── ai_providers.py      # Pluggable AI provider abstraction
│   ├── retriever.py         # FTS5 context retrieval for chat
│   ├── ioc_extractor.py     # IOC detection and deduplication
│   ├── parsers/             # Format-specific evidence parsers
│   │   ├── dispatcher.py    # Auto-format detection
│   │   ├── android_parser.py
│   │   ├── ios_parser.py
│   │   ├── ufdr_parser.py
│   │   └── ...
│   ├── extractors/          # Per-app data extractors (SMS, WhatsApp, …)
│   └── routes/              # Flask blueprints (cases, analysis, chat, reports, …)
├── templates/
│   ├── index.html           # SPA shell
│   └── report.html          # Court-ready HTML/PDF report template
├── static/
│   ├── style.css
│   └── js/
│       ├── cases.js         # Case management, evidence upload, modal
│       ├── chat.js          # Analysis tab and AIFT results renderer
│       ├── conversations.js # Message thread browser
│       ├── dashboard.js     # KPI dashboard
│       ├── timeline.js      # Cross-platform event timeline
│       └── ...
├── prompts/                 # LLM system prompt + per-artifact analysis prompts
├── tests/                   # pytest test suite (~200 tests)
├── config.yaml              # Runtime configuration
└── docker-compose.yml
```

**Key patterns:**
- Parser dispatcher auto-selects the correct parser from the file signature and internal structure
- All message/contact/call data is normalised to a common schema regardless of source platform
- Analysis runs in a background thread pool; SSE streams per-artifact progress to the browser
- FTS5 virtual tables on `messages` and `contacts` power sub-second full-text retrieval for the chat endpoint

---

## API Reference

All endpoints are prefixed with `/api`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serve the SPA |
| `GET/POST` | `/cases` | List / create cases |
| `GET/PATCH/DELETE` | `/cases/<id>` | Get / update / delete a case |
| `POST` | `/cases/<id>/evidence` | Upload an evidence file |
| `POST` | `/cases/<id>/evidence/scan` | Scan a filesystem path for evidence |
| `GET` | `/cases/<id>/messages` | Query messages (paginated, filtered) |
| `GET` | `/cases/<id>/threads` | Conversation threads grouped by platform |
| `GET` | `/cases/<id>/contacts` | Contact list |
| `GET` | `/cases/<id>/calls` | Call log |
| `POST` | `/cases/<id>/analyze` | Trigger background LLM analysis |
| `GET` | `/cases/<id>/analysis/stream` | SSE progress stream |
| `GET` | `/cases/<id>/analysis` | Completed analysis results |
| `POST` | `/cases/<id>/analysis/cancel` | Cancel in-flight analysis |
| `POST` | `/cases/<id>/chat` | Ask a question (FTS-backed chatbot) |
| `GET` | `/cases/<id>/report` | Render HTML case report |
| `GET` | `/cases/<id>/report/pdf` | Download PDF report |
| `GET` | `/cases/<id>/timeline` | Chronological cross-platform event feed |
| `GET` | `/cases/<id>/ioc` | Extract indicators of compromise |
| `GET` | `/cases/<id>/graph` | Entity linkage graph (JSON) |
| `GET/POST` | `/cases/<id>/annotations` | List / create message annotations |
| `GET/POST` | `/settings` | Read / update AI configuration |
| `GET` | `/dashboard/stats` | Aggregate KPIs across all cases |
| `GET` | `/health` | Health check |

---

## Development

### Running tests

```bash
pytest tests/ -q
```

Tests use isolated in-memory / temp SQLite databases via `conftest.py` fixtures and do not touch `data/`.

### Project structure conventions

- **One blueprint per feature area** — `routes/cases.py`, `routes/analysis.py`, `routes/chat.py`, etc.
- **No ORM** — raw `sqlite3` with named-column `Row` factory for transparency and performance
- **No build step** — the frontend is plain ES-module JavaScript; no bundler required
- **Config layering** — defaults → `config.yaml` → environment variables (later layers win)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3.0+ |
| Database | SQLite 3 + FTS5 |
| AI integration | Anthropic SDK, OpenAI SDK, HTTP (OpenRouter / Ollama) |
| PDF generation | WeasyPrint 60+ |
| Containerisation | Docker + Compose |
| Frontend | Vanilla ES6, CSS custom properties |
| Testing | pytest 8+ |

---

## License

This project is intended for authorised law enforcement and forensic use only.
