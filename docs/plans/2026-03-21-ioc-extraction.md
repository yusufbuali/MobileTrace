# IOC Extraction — Intelligence Tab Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an "Intelligence" tab per case that extracts phone numbers, emails, URLs, crypto addresses, IPs, and coordinates from all messages/contacts using regex, showing a deduplicated, copyable, filterable table with source jump links.

**Architecture:** New `app/ioc_extractor.py` module does a single-pass regex scan over DB rows and returns grouped IOC dicts. New `app/routes/ioc.py` blueprint exposes `GET /api/cases/<id>/ioc`. New `static/js/ioc.js` renders the Intelligence tab with summary chips, filter pills, expandable source accordions, copy buttons, and CSV export.

**Tech Stack:** Python 3.12 re stdlib, Flask blueprint, vanilla JS ES modules, existing conftest.py fixture pattern

---

## Task 1 — IOC extractor module (`app/ioc_extractor.py`)

**Context:** The extractor is a pure Python module — no Flask, no DB. It accepts a list of `{"id", "body", "platform", "thread_id", "timestamp"}` dicts (from messages) and a list of `{"phone", "email"}` dicts (from contacts), runs all regex patterns, deduplicates by `(type, normalised_value)`, and returns a structured result dict. Keeping it DB-free makes it trivially unit-testable.

**Files:**
- Create: `app/ioc_extractor.py`
- Create: `tests/test_ioc_extractor.py`

---

### Step 1: Write the failing tests

Create `tests/test_ioc_extractor.py`:

```python
"""Unit tests for app.ioc_extractor — regex patterns and deduplication."""
import pytest
from app.ioc_extractor import extract_iocs, _normalise_phone


# ── Phone ────────────────────────────────────────────────────────────────────

def test_phone_e164():
    msgs = [{"id": "1", "body": "Call me at +97312345678", "platform": "sms",
              "thread_id": "t1", "timestamp": "2024-01-01T00:00:00"}]
    result = extract_iocs(msgs, [])
    phones = [i for i in result["iocs"] if i["type"] == "phone"]
    assert len(phones) == 1
    assert "+97312345678" in phones[0]["value"]


def test_phone_deduplication():
    body = "+97312345678"
    msgs = [
        {"id": "1", "body": body, "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"},
        {"id": "2", "body": body, "platform": "whatsapp", "thread_id": "t2", "timestamp": "2024-01-02"},
    ]
    result = extract_iocs(msgs, [])
    phones = [i for i in result["iocs"] if i["type"] == "phone"]
    assert len(phones) == 1
    assert phones[0]["occurrences"] == 2


def test_phone_normalise():
    assert _normalise_phone("+973 1234 5678") == "+97312345678"
    assert _normalise_phone("+973-1234-5678") == "+97312345678"


# ── Email ────────────────────────────────────────────────────────────────────

def test_email_extracted():
    msgs = [{"id": "1", "body": "Send to suspect@gmail.com please",
              "platform": "telegram", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    emails = [i for i in result["iocs"] if i["type"] == "email"]
    assert len(emails) == 1
    assert emails[0]["value"] == "suspect@gmail.com"


# ── URL ──────────────────────────────────────────────────────────────────────

def test_url_https():
    msgs = [{"id": "1", "body": "Check https://example.com/path?x=1",
              "platform": "whatsapp", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    urls = [i for i in result["iocs"] if i["type"] == "url"]
    assert len(urls) == 1
    assert "example.com" in urls[0]["value"]


def test_url_http():
    msgs = [{"id": "1", "body": "go to http://shady.ru",
              "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    urls = [i for i in result["iocs"] if i["type"] == "url"]
    assert any("shady.ru" in u["value"] for u in urls)


# ── Crypto ───────────────────────────────────────────────────────────────────

def test_btc_address():
    msgs = [{"id": "1", "body": "Send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf",
              "platform": "telegram", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    crypto = [i for i in result["iocs"] if i["type"] == "crypto"]
    assert len(crypto) == 1
    assert crypto[0]["value"] == "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf"


def test_eth_address():
    msgs = [{"id": "1", "body": "ETH wallet: 0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe",
              "platform": "whatsapp", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    crypto = [i for i in result["iocs"] if i["type"] == "crypto"]
    assert len(crypto) == 1


# ── IP ───────────────────────────────────────────────────────────────────────

def test_public_ip_extracted():
    msgs = [{"id": "1", "body": "Server at 185.220.101.5",
              "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    ips = [i for i in result["iocs"] if i["type"] == "ip"]
    assert len(ips) == 1
    assert ips[0]["value"] == "185.220.101.5"


def test_private_ip_excluded():
    msgs = [{"id": "1", "body": "LAN at 192.168.1.1 and 10.0.0.1",
              "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    ips = [i for i in result["iocs"] if i["type"] == "ip"]
    assert len(ips) == 0


# ── Coords ───────────────────────────────────────────────────────────────────

def test_coords_extracted():
    msgs = [{"id": "1", "body": "Meet at 26.2285, 50.5860",
              "platform": "whatsapp", "thread_id": "t1", "timestamp": "2024-01-01"}]
    result = extract_iocs(msgs, [])
    coords = [i for i in result["iocs"] if i["type"] == "coords"]
    assert len(coords) == 1


# ── Summary ──────────────────────────────────────────────────────────────────

def test_summary_by_type():
    msgs = [
        {"id": "1", "body": "+97312345678 and suspect@evil.com",
         "platform": "sms", "thread_id": "t1", "timestamp": "2024-01-01"},
    ]
    result = extract_iocs(msgs, [])
    assert result["summary"]["total"] >= 2
    assert result["summary"]["by_type"]["phone"] >= 1
    assert result["summary"]["by_type"]["email"] >= 1


# ── Contact sources ───────────────────────────────────────────────────────────

def test_contacts_scanned():
    contacts = [{"phone": "+97312345678", "email": "dealer@evil.com"}]
    result = extract_iocs([], contacts)
    phones = [i for i in result["iocs"] if i["type"] == "phone"]
    emails = [i for i in result["iocs"] if i["type"] == "email"]
    assert len(phones) == 1
    assert len(emails) == 1


# ── Source snippets ───────────────────────────────────────────────────────────

def test_sources_capped_at_5():
    msgs = [
        {"id": str(i), "body": "+97312345678", "platform": "sms",
         "thread_id": "t1", "timestamp": f"2024-01-0{i+1}"}
        for i in range(8)
    ]
    result = extract_iocs(msgs, [])
    phones = [i for i in result["iocs"] if i["type"] == "phone"]
    assert phones[0]["occurrences"] == 8
    assert len(phones[0]["sources"]) <= 5


# ── Empty input ───────────────────────────────────────────────────────────────

def test_empty_input():
    result = extract_iocs([], [])
    assert result["iocs"] == []
    assert result["summary"]["total"] == 0
```

Run: `python -m pytest tests/test_ioc_extractor.py -v`
Expected: **FAIL** — `ModuleNotFoundError: No module named 'app.ioc_extractor'`

---

### Step 2: Create `app/ioc_extractor.py`

```python
"""IOC Extractor — deterministic regex scan over MobileTrace message/contact data.

Returns a structured dict ready for JSON serialisation.
No Flask, no DB — accepts plain Python lists for easy unit testing.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


# ── Regex patterns ────────────────────────────────────────────────────────────

_RE_PHONE = re.compile(
    r"(?<!\w)(\+?[0-9][\d\s\-().]{7,15}[0-9])(?!\w)"
)
_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
_RE_URL = re.compile(
    r"https?://[^\s\"'<>]+"
)
_RE_BTC = re.compile(
    r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b"
)
_RE_ETH = re.compile(
    r"\b0x[a-fA-F0-9]{40}\b"
)
_RE_IP = re.compile(
    r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"
)
_RE_COORDS = re.compile(
    r"-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}"
)

_PRIVATE_IP_PREFIXES = (
    ("10.",),
    ("192.168.",),
    ("172.16.", "172.17.", "172.18.", "172.19.",
     "172.20.", "172.21.", "172.22.", "172.23.",
     "172.24.", "172.25.", "172.26.", "172.27.",
     "172.28.", "172.29.", "172.30.", "172.31."),
    ("127.",),
    ("169.254.",),
)

_MAX_SOURCES = 5


# ── Normalisation helpers ────────────────────────────────────────────────────

def _normalise_phone(raw: str) -> str:
    """Strip whitespace, dashes, dots, parentheses from a phone match."""
    return re.sub(r"[\s\-().]+", "", raw)


def _is_private_ip(ip: str) -> bool:
    for group in _PRIVATE_IP_PREFIXES:
        if any(ip.startswith(p) for p in group):
            return True
    return False


# ── Core extractor ────────────────────────────────────────────────────────────

def _scan_text(
    text: str,
    source: dict[str, str],
    hits: dict[tuple, dict],
) -> None:
    """Scan *text* for all IOC types; accumulate results into *hits*."""
    if not text:
        return

    # Phone
    for m in _RE_PHONE.finditer(text):
        raw = m.group(1)
        norm = _normalise_phone(raw)
        if len(norm.lstrip("+")) < 7:
            continue
        key = ("phone", norm)
        _add_hit(hits, key, "phone", norm, source, text)

    # Email
    for m in _RE_EMAIL.finditer(text):
        val = m.group(0).lower()
        key = ("email", val)
        _add_hit(hits, key, "email", val, source, text)

    # URL
    for m in _RE_URL.finditer(text):
        val = m.group(0).rstrip(".,;)")
        key = ("url", val)
        _add_hit(hits, key, "url", val, source, text)

    # BTC
    for m in _RE_BTC.finditer(text):
        val = m.group(0)
        key = ("crypto", val)
        _add_hit(hits, key, "crypto", val, source, text)

    # ETH
    for m in _RE_ETH.finditer(text):
        val = m.group(0).lower()
        key = ("crypto", val)
        _add_hit(hits, key, "crypto", val, source, text)

    # IP
    for m in _RE_IP.finditer(text):
        val = m.group(0)
        if not _is_private_ip(val):
            key = ("ip", val)
            _add_hit(hits, key, "ip", val, source, text)

    # Coords
    for m in _RE_COORDS.finditer(text):
        val = m.group(0)
        key = ("coords", val)
        _add_hit(hits, key, "coords", val, source, text)


def _add_hit(
    hits: dict,
    key: tuple,
    ioc_type: str,
    value: str,
    source: dict,
    text: str,
) -> None:
    if key not in hits:
        hits[key] = {
            "type": ioc_type,
            "value": value,
            "occurrences": 0,
            "first_seen": source.get("timestamp", ""),
            "last_seen": source.get("timestamp", ""),
            "sources": [],
        }
    entry = hits[key]
    entry["occurrences"] += 1
    ts = source.get("timestamp", "")
    if ts and (not entry["first_seen"] or ts < entry["first_seen"]):
        entry["first_seen"] = ts
    if ts and ts > entry["last_seen"]:
        entry["last_seen"] = ts
    if len(entry["sources"]) < _MAX_SOURCES:
        snippet = text[:120].replace("\n", " ")
        entry["sources"].append({
            "platform": source.get("platform", ""),
            "thread_id": source.get("thread_id", ""),
            "message_id": source.get("id", ""),
            "timestamp": ts,
            "snippet": snippet,
        })


# ── Public API ────────────────────────────────────────────────────────────────

def extract_iocs(
    messages: list[dict[str, Any]],
    contacts: list[dict[str, Any]],
    ioc_type_filter: str = "",
) -> dict[str, Any]:
    """Extract and deduplicate IOCs from message bodies and contact records.

    Args:
        messages: list of dicts with keys id, body, platform, thread_id, timestamp
        contacts: list of dicts with keys phone, email
        ioc_type_filter: if set, return only IOCs of this type

    Returns:
        { "iocs": [...], "summary": { "total": N, "by_type": {...} } }
    """
    hits: dict[tuple, dict] = {}

    for msg in messages:
        source = {
            "id": msg.get("id", ""),
            "platform": msg.get("platform", ""),
            "thread_id": msg.get("thread_id", ""),
            "timestamp": msg.get("timestamp", ""),
        }
        _scan_text(msg.get("body") or "", source, hits)

    for contact in contacts:
        source = {"id": "", "platform": "contacts", "thread_id": "", "timestamp": ""}
        _scan_text(contact.get("phone") or "", source, hits)
        _scan_text(contact.get("email") or "", source, hits)

    iocs = list(hits.values())
    if ioc_type_filter:
        iocs = [i for i in iocs if i["type"] == ioc_type_filter]

    by_type: dict[str, int] = {}
    for ioc in iocs:
        by_type[ioc["type"]] = by_type.get(ioc["type"], 0) + 1

    return {
        "iocs": iocs,
        "summary": {"total": len(iocs), "by_type": by_type},
    }
```

---

### Step 3: Run tests to verify they pass

```bash
python -m pytest tests/test_ioc_extractor.py -v
```

Expected: **all pass**

---

### Step 4: Run full suite (no regressions)

```bash
python -m pytest tests/ -q
```

Expected: all existing tests still pass.

---

### Step 5: Commit

```bash
git add app/ioc_extractor.py tests/test_ioc_extractor.py
git commit -m "feat(ioc): IOC extractor module — phone, email, URL, crypto, IP, coords"
```

---

## Task 2 — IOC route (`app/routes/ioc.py`)

**Context:** A single `GET /api/cases/<case_id>/ioc` endpoint. It queries all messages and contacts for the case, passes them to `extract_iocs()`, and returns the result as JSON. Optional `?type=` query param filters by IOC type.

**Files:**
- Create: `app/routes/ioc.py`
- Create: `tests/test_ioc_routes.py`

---

### Step 1: Write the failing tests

Create `tests/test_ioc_routes.py`:

```python
"""Smoke tests for GET /api/cases/<id>/ioc."""
import pytest
from app import create_app
from app.database import init_db, close_db, get_db


@pytest.fixture
def client(tmp_path):
    app = create_app(testing=True)
    db_path = str(tmp_path / "test.db")
    app.config["MT_CONFIG"]["server"]["database_path"] = db_path
    app.config["MT_CONFIG"]["server"]["cases_dir"] = str(tmp_path / "cases")
    init_db(db_path)
    with app.test_client() as c:
        yield c
    close_db()


def _make_case(client):
    r = client.post("/api/cases", json={"title": "IOC Test", "officer": "Det. Test"})
    assert r.status_code == 201
    return r.get_json()["id"]


def _seed_messages(case_id):
    db = get_db()
    db.executemany(
        "INSERT INTO messages (case_id, platform, direction, sender, recipient, body, timestamp, thread_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [
            (case_id, "whatsapp", "incoming", "Alice", "device",
             "My email is suspect@evil.com and BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf",
             "2024-01-01T10:00:00", "thread1"),
            (case_id, "sms", "incoming", "+97312345678", "device",
             "Call me at +97312345678 or visit https://darkweb.onion",
             "2024-01-02T10:00:00", "thread2"),
        ],
    )
    db.commit()


def test_ioc_404_for_missing_case(client):
    r = client.get("/api/cases/nonexistent/ioc")
    assert r.status_code == 404


def test_ioc_empty_case(client):
    case_id = _make_case(client)
    r = client.get(f"/api/cases/{case_id}/ioc")
    assert r.status_code == 200
    data = r.get_json()
    assert data["iocs"] == []
    assert data["summary"]["total"] == 0


def test_ioc_returns_expected_types(client):
    case_id = _make_case(client)
    _seed_messages(case_id)
    r = client.get(f"/api/cases/{case_id}/ioc")
    assert r.status_code == 200
    data = r.get_json()
    types = {i["type"] for i in data["iocs"]}
    assert "phone" in types
    assert "email" in types
    assert "url" in types
    assert "crypto" in types


def test_ioc_type_filter(client):
    case_id = _make_case(client)
    _seed_messages(case_id)
    r = client.get(f"/api/cases/{case_id}/ioc?type=phone")
    assert r.status_code == 200
    data = r.get_json()
    assert all(i["type"] == "phone" for i in data["iocs"])


def test_ioc_response_shape(client):
    case_id = _make_case(client)
    _seed_messages(case_id)
    r = client.get(f"/api/cases/{case_id}/ioc")
    data = r.get_json()
    assert "case_id" in data
    assert "summary" in data
    assert "by_type" in data["summary"]
    assert "iocs" in data
    for ioc in data["iocs"]:
        for field in ("type", "value", "occurrences", "first_seen", "last_seen", "sources"):
            assert field in ioc
```

Run: `python -m pytest tests/test_ioc_routes.py -v`
Expected: **FAIL** — `404` on the IOC endpoint (blueprint not registered yet)

---

### Step 2: Create `app/routes/ioc.py`

```python
"""IOC extraction route for MobileTrace."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.database import get_db
from app.ioc_extractor import extract_iocs

bp_ioc = Blueprint("ioc", __name__, url_prefix="/api")


@bp_ioc.get("/cases/<case_id>/ioc")
def get_ioc(case_id: str):
    db = get_db()
    if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
        return jsonify({"error": "case not found"}), 404

    ioc_type = request.args.get("type", "").strip().lower()
    limit = min(int(request.args.get("limit", 500)), 2000)

    msg_rows = db.execute(
        "SELECT id, body, platform, thread_id, timestamp "
        "FROM messages WHERE case_id=? AND body IS NOT NULL AND body != '' "
        "ORDER BY timestamp ASC LIMIT ?",
        (case_id, limit),
    ).fetchall()
    messages = [dict(r) for r in msg_rows]

    contact_rows = db.execute(
        "SELECT phone, email FROM contacts WHERE case_id=?",
        (case_id,),
    ).fetchall()
    contacts = [dict(r) for r in contact_rows]

    result = extract_iocs(messages, contacts, ioc_type_filter=ioc_type)
    result["case_id"] = case_id
    return jsonify(result)
```

---

### Step 3: Register blueprint in `app/__init__.py`

In `create_app()`, add after the correlation import/register block:

```python
from .routes.ioc import bp_ioc
app.register_blueprint(bp_ioc)
```

---

### Step 4: Run tests

```bash
python -m pytest tests/test_ioc_routes.py -v
```

Expected: **all pass**

---

### Step 5: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all pass.

---

### Step 6: Commit

```bash
git add app/routes/ioc.py app/__init__.py tests/test_ioc_routes.py
git commit -m "feat(ioc): IOC route GET /api/cases/<id>/ioc with type filter"
```

---

## Task 3 — Intelligence tab frontend

**Context:** A new "Intelligence" tab panel in `templates/index.html`, wired up via a new `static/js/ioc.js` ES module. The tab is inserted between Correlation and Analysis in the tab bar. CSS classes follow the `.gdb-*` / `.corr-*` naming conventions already in `static/style.css`.

**Files:**
- Create: `static/js/ioc.js`
- Modify: `templates/index.html`
- Modify: `static/style.css`
- Modify: `static/js/cases.js`

---

### Step 1: Add tab button and panel HTML to `templates/index.html`

**Tab button** — add after the Correlation tab button and before the Analysis tab button in the tab bar (`<div class="tab-bar">`):

```html
<button class="tab-btn" data-tab="tab-intel">Intelligence</button>
```

**Tab panel** — add after `<div id="tab-correlation" ...>` and before `<div id="tab-analysis" ...>`:

```html
<!-- ── Intelligence / IOC Tab ─────────────────────────────────────────── -->
<div id="tab-intel" class="tab-panel" style="display:none">
  <div class="intel-header">
    <h2 class="intel-title">Intelligence — Indicators of Compromise</h2>
    <button id="btn-ioc-export-csv" class="btn-secondary" style="display:none">&#128196; Export CSV</button>
  </div>
  <div id="ioc-summary-bar" class="ioc-summary-bar"></div>
  <div id="ioc-filter-pills" class="ioc-filter-pills"></div>
  <div id="ioc-table-wrap" class="ioc-table-wrap">
    <div class="ioc-empty-state">Open a case to view indicators.</div>
  </div>
</div>
```

**Script tag** — add near the bottom of `<body>` alongside the other module scripts:

```html
<script type="module" src="/static/js/ioc.js"></script>
```

---

### Step 2: Create `static/js/ioc.js`

```javascript
/**
 * ioc.js — Intelligence tab: IOC extraction results renderer.
 * Exports initIoc(caseId) called by cases.js on tab switch.
 */

const _TYPE_LABELS = {
  phone: "Phone",
  email: "Email",
  url: "URL",
  crypto: "Crypto",
  ip: "IP Address",
  coords: "Coordinates",
};

const _TYPE_COLORS = {
  phone:  "var(--success)",
  email:  "var(--info)",
  url:    "var(--accent)",
  crypto: "#f59e0b",
  ip:     "#a78bfa",
  coords: "#34d399",
};

let _allIocs = [];
let _activeFilter = "all";
let _caseId = null;

function dom(id) { return document.getElementById(id); }

function _esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Public entry point ───────────────────────────────────────────────────────

export async function initIoc(caseId) {
  if (!caseId) return;
  _caseId = caseId;
  _activeFilter = "all";

  const wrap = dom("ioc-table-wrap");
  wrap.innerHTML = '<div class="ioc-loading">Scanning evidence…</div>';
  dom("ioc-summary-bar").innerHTML = "";
  dom("ioc-filter-pills").innerHTML = "";
  dom("btn-ioc-export-csv").style.display = "none";

  try {
    const res = await fetch(`/api/cases/${caseId}/ioc`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _allIocs = data.iocs || [];
    _renderSummary(data.summary || {});
    _renderFilterPills(data.summary?.by_type || {});
    _renderTable(_allIocs);
    if (_allIocs.length) dom("btn-ioc-export-csv").style.display = "";
  } catch (err) {
    wrap.innerHTML = `<div class="ioc-empty-state">Failed to load IOCs: ${_esc(err.message)}</div>`;
  }
}

// ── Summary bar ──────────────────────────────────────────────────────────────

function _renderSummary(summary) {
  const bar = dom("ioc-summary-bar");
  if (!summary.total) {
    bar.innerHTML = '<span class="ioc-summary-chip">No indicators found in this case.</span>';
    return;
  }
  const chips = Object.entries(summary.by_type || {}).map(([type, count]) => {
    const label = _TYPE_LABELS[type] || type;
    const color = _TYPE_COLORS[type] || "var(--muted)";
    return `<span class="ioc-summary-chip" style="border-color:${color};color:${color}">${label} <strong>${count}</strong></span>`;
  });
  bar.innerHTML = `<span class="ioc-total-chip">Total <strong>${summary.total}</strong></span> ` + chips.join(" ");
}

// ── Filter pills ─────────────────────────────────────────────────────────────

function _renderFilterPills(byType) {
  const wrap = dom("ioc-filter-pills");
  const types = ["all", ...Object.keys(byType)];
  wrap.innerHTML = types.map(t => {
    const label = t === "all" ? "All" : (_TYPE_LABELS[t] || t);
    const active = t === _activeFilter ? " active" : "";
    return `<button class="ioc-filter-pill${active}" data-type="${_esc(t)}">${_esc(label)}</button>`;
  }).join("");

  wrap.querySelectorAll(".ioc-filter-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      _activeFilter = btn.dataset.type;
      wrap.querySelectorAll(".ioc-filter-pill").forEach(b =>
        b.classList.toggle("active", b.dataset.type === _activeFilter));
      const filtered = _activeFilter === "all"
        ? _allIocs
        : _allIocs.filter(i => i.type === _activeFilter);
      _renderTable(filtered);
    });
  });
}

// ── Table ────────────────────────────────────────────────────────────────────

function _renderTable(iocs) {
  const wrap = dom("ioc-table-wrap");
  if (!iocs.length) {
    wrap.innerHTML = '<div class="ioc-empty-state">No indicators match the current filter.</div>';
    return;
  }

  const rows = iocs.map((ioc, idx) => {
    const color = _TYPE_COLORS[ioc.type] || "var(--muted)";
    const typeBadge = `<span class="ioc-type-badge" style="background:${color}20;color:${color};border-color:${color}40">${_esc(_TYPE_LABELS[ioc.type] || ioc.type)}</span>`;
    const srcCount = ioc.sources?.length || 0;
    const hasMore = ioc.occurrences > srcCount;
    const srcLabel = hasMore
      ? `${ioc.occurrences} (showing ${srcCount})`
      : ioc.occurrences;

    const firstThread = ioc.sources?.[0]?.thread_id || "";
    const firstPlatform = ioc.sources?.[0]?.platform || "";
    const jumpBtn = firstThread
      ? `<button class="ioc-jump-btn" data-thread="${_esc(firstThread)}" data-platform="${_esc(firstPlatform)}" title="Jump to conversation">&#8599;</button>`
      : "";

    return `
      <tr class="ioc-row" data-idx="${idx}">
        <td class="ioc-val-cell"><span class="ioc-value">${_esc(ioc.value)}</span></td>
        <td>${typeBadge}</td>
        <td class="ioc-num">${srcLabel}</td>
        <td class="ioc-ts">${(ioc.first_seen || "").slice(0, 10)}</td>
        <td class="ioc-ts">${(ioc.last_seen || "").slice(0, 10)}</td>
        <td class="ioc-actions">
          <button class="ioc-copy-btn" data-value="${_esc(ioc.value)}" title="Copy">&#128203;</button>
          ${jumpBtn}
          ${srcCount ? `<button class="ioc-src-btn" data-idx="${idx}" title="Show sources">&#128270; Sources</button>` : ""}
        </td>
      </tr>
      <tr class="ioc-src-row" id="ioc-src-${idx}" style="display:none">
        <td colspan="6">${_renderSources(ioc.sources || [])}</td>
      </tr>`;
  }).join("");

  wrap.innerHTML = `
    <table class="ioc-table">
      <thead>
        <tr>
          <th>Value</th><th>Type</th><th>Occurrences</th>
          <th>First Seen</th><th>Last Seen</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;

  // Wire copy buttons
  wrap.querySelectorAll(".ioc-copy-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(btn.dataset.value).then(() => {
        btn.textContent = "✓";
        setTimeout(() => { btn.innerHTML = "&#128203;"; }, 1200);
      });
    });
  });

  // Wire jump buttons
  wrap.querySelectorAll(".ioc-jump-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("mt:jump-to-thread", {
        detail: { platform: btn.dataset.platform, thread: btn.dataset.thread }
      }));
    });
  });

  // Wire source toggle buttons
  wrap.querySelectorAll(".ioc-src-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const srcRow = dom(`ioc-src-${btn.dataset.idx}`);
      const open = srcRow.style.display !== "none";
      srcRow.style.display = open ? "none" : "";
      btn.innerHTML = open ? "&#128270; Sources" : "&#9650; Sources";
    });
  });

  // Wire CSV export button
  dom("btn-ioc-export-csv").onclick = () => _exportCsv(iocs);
}

function _renderSources(sources) {
  if (!sources.length) return "";
  const rows = sources.map(s => `
    <div class="ioc-source-item">
      <span class="ioc-src-badge ioc-src-${_esc(s.platform)}">${_esc(s.platform)}</span>
      <span class="ioc-src-ts">${(s.timestamp || "").slice(0, 16)}</span>
      <span class="ioc-src-snippet">${_esc(s.snippet)}</span>
    </div>`).join("");
  return `<div class="ioc-sources-panel">${rows}</div>`;
}

// ── CSV export ────────────────────────────────────────────────────────────────

function _exportCsv(iocs) {
  const header = "Type,Value,Occurrences,First Seen,Last Seen,Platform,Thread\n";
  const rows = iocs.flatMap(ioc => {
    if (!ioc.sources?.length) {
      return [`${ioc.type},${ioc.value},${ioc.occurrences},${ioc.first_seen},${ioc.last_seen},,`];
    }
    return ioc.sources.map(s =>
      [ioc.type, ioc.value, ioc.occurrences, ioc.first_seen, ioc.last_seen, s.platform, s.thread_id]
        .map(v => `"${String(v ?? "").replace(/"/g, '""')}"`)
        .join(",")
    );
  });
  const blob = new Blob([header + rows.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `ioc-case-${_caseId}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}
```

---

### Step 3: Add CSS to `static/style.css`

Append at the end of the file:

```css
/* ══ Intelligence / IOC Tab ═════════════════════════════════════════════════ */

.intel-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 14px;
}
.intel-title { font-size: 1.05rem; font-weight: 700; margin: 0; }

/* Summary bar */
.ioc-summary-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.ioc-total-chip {
  padding: 4px 10px; border-radius: 20px; font-size: 0.78rem;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(159,177,199,0.25);
  color: var(--text);
}
.ioc-summary-chip {
  padding: 4px 10px; border-radius: 20px; font-size: 0.78rem;
  background: rgba(255,255,255,0.04); border: 1px solid;
}

/* Filter pills */
.ioc-filter-pills { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
.ioc-filter-pill {
  padding: 4px 12px; border-radius: 20px; font-size: 0.78rem; cursor: pointer;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(159,177,199,0.25);
  color: var(--text-muted); transition: all 0.15s;
}
.ioc-filter-pill:hover { border-color: var(--accent); color: var(--accent); }
.ioc-filter-pill.active {
  background: rgba(87,179,255,0.12); border-color: var(--accent); color: var(--accent);
}

/* Table */
.ioc-table-wrap { overflow-x: auto; }
.ioc-table {
  width: 100%; border-collapse: collapse; font-size: 0.82rem;
}
.ioc-table th {
  text-align: left; padding: 8px 10px; font-size: 0.72rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted);
  border-bottom: 1px solid rgba(159,177,199,0.18);
}
.ioc-table td { padding: 9px 10px; border-bottom: 1px solid rgba(159,177,199,0.08); }
.ioc-row:hover td { background: rgba(255,255,255,0.02); }
.ioc-val-cell { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ioc-value { font-family: 'Consolas', monospace; font-size: 0.82rem; }
.ioc-num { text-align: center; color: var(--text-muted); }
.ioc-ts { color: var(--text-muted); white-space: nowrap; font-size: 0.78rem; }
.ioc-actions { display: flex; gap: 4px; align-items: center; white-space: nowrap; }

/* Type badge */
.ioc-type-badge {
  padding: 2px 8px; border-radius: 10px; font-size: 0.72rem; font-weight: 600;
  border: 1px solid;
}

/* Action buttons */
.ioc-copy-btn, .ioc-jump-btn, .ioc-src-btn {
  padding: 3px 7px; border-radius: 5px; font-size: 0.75rem; cursor: pointer;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(159,177,199,0.2);
  color: var(--text-muted); transition: all 0.15s;
}
.ioc-copy-btn:hover, .ioc-jump-btn:hover, .ioc-src-btn:hover {
  border-color: var(--accent); color: var(--accent);
}

/* Sources panel */
.ioc-src-row td { padding: 0 10px 10px 20px; background: rgba(0,0,0,0.15); }
.ioc-sources-panel { display: flex; flex-direction: column; gap: 6px; padding-top: 8px; }
.ioc-source-item {
  display: flex; gap: 10px; align-items: flex-start;
  font-size: 0.78rem; padding: 6px 10px;
  background: rgba(255,255,255,0.02); border-radius: 6px;
  border: 1px solid rgba(159,177,199,0.1);
}
.ioc-src-badge {
  padding: 1px 6px; border-radius: 8px; font-size: 0.68rem; font-weight: 700;
  white-space: nowrap; flex-shrink: 0;
  background: rgba(255,255,255,0.08); color: var(--text-muted);
}
.ioc-src-ts { white-space: nowrap; color: var(--text-muted); flex-shrink: 0; }
.ioc-src-snippet { color: var(--text); word-break: break-word; }

/* Empty / loading states */
.ioc-empty-state, .ioc-loading {
  text-align: center; padding: 40px 20px; color: var(--text-muted); font-size: 0.88rem;
}
```

---

### Step 4: Wire tab in `static/js/cases.js`

In `cases.js`, find the tab-click handler (the section that checks `btn.dataset.tab`) and add a case for the Intelligence tab — follow the same pattern as Correlation:

```javascript
// Find the block that handles tab switching and add:
import { initIoc } from "./ioc.js";

// In the tab-click handler, alongside the other tab checks:
if (btn.dataset.tab === "tab-intel" && activeCaseId) {
  initIoc(activeCaseId);
}

// In openCase() where the active tab is refreshed, add:
if (document.querySelector('[data-tab="tab-intel"]')?.classList.contains("active")) {
  initIoc(id);
}
```

Also listen for the jump event dispatched by `ioc.js`:

```javascript
// Near the bottom of cases.js DOMContentLoaded, add once:
window.addEventListener("mt:jump-to-thread", (e) => {
  const { platform, thread } = e.detail;
  // Switch to conversations tab and open thread
  document.querySelector('[data-tab="tab-conversations"]')?.click();
  setTimeout(() => {
    window.dispatchEvent(new CustomEvent("mt:open-thread", { detail: { platform, thread } }));
  }, 100);
});
```

In `conversations.js`, listen for `mt:open-thread` to auto-open the correct thread (add to `initConversations`):

```javascript
window.addEventListener("mt:open-thread", (e) => {
  const { platform, thread } = e.detail;
  _openThread(platform, thread);
}, { once: false });
```

---

### Step 5: Manual smoke test

```bash
# Start the app
flask run

# Open browser → create a case → upload evidence → open Intelligence tab
# Verify: summary chips show counts, filter pills work, copy button works,
#         sources expand, export CSV downloads a valid file
```

---

### Step 6: Run full test suite

```bash
python -m pytest tests/ -q
```

Expected: all 144+ tests pass (frontend is not covered by automated tests).

---

### Step 7: Commit

```bash
git add static/js/ioc.js static/style.css templates/index.html static/js/cases.js static/js/conversations.js
git commit -m "feat(ioc): Intelligence tab — IOC table with filter, copy, source expand, CSV export"
```

---

## Files Changed Summary

| File | Task |
|---|---|
| `app/ioc_extractor.py` | Task 1 (new) |
| `tests/test_ioc_extractor.py` | Task 1 (new) |
| `app/routes/ioc.py` | Task 2 (new) |
| `app/__init__.py` | Task 2 (register blueprint) |
| `tests/test_ioc_routes.py` | Task 2 (new) |
| `static/js/ioc.js` | Task 3 (new) |
| `templates/index.html` | Task 3 (tab button + panel + script tag) |
| `static/style.css` | Task 3 (IOC styles) |
| `static/js/cases.js` | Task 3 (tab wire + jump handler) |
| `static/js/conversations.js` | Task 3 (mt:open-thread listener) |
