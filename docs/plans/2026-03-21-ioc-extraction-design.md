# IOC Extraction — Intelligence Tab Design

**Date:** 2026-03-21
**Status:** Approved

---

## Overview

A dedicated "Intelligence" tab per case that automatically extracts Indicators of Compromise (IOCs) from all stored messages, contacts, and call logs using deterministic regex patterns. Investigators get a structured, deduplicated, copyable IOC table without running LLM analysis first.

---

## Architecture

### Backend

**New route file:** `app/routes/ioc.py`
**Blueprint:** `bp_ioc`, registered in `app/__init__.py`

**Single endpoint:**
```
GET /api/cases/<case_id>/ioc
```

Query params:
- `?type=phone|email|url|crypto|ip|coords` — filter by IOC type (default: all)
- `?limit=500` — cap results (default 500)

**Response shape:**
```json
{
  "case_id": "...",
  "summary": { "total": 87, "by_type": { "phone": 32, "url": 21, ... } },
  "iocs": [
    {
      "type": "phone",
      "value": "+97312345678",
      "occurrences": 14,
      "first_seen": "2024-01-15T08:23:11+00:00",
      "last_seen": "2024-03-02T17:44:00+00:00",
      "sources": [
        { "platform": "whatsapp", "thread_id": "...", "message_id": "...", "timestamp": "...", "snippet": "..." }
      ]
    }
  ]
}
```

**Extraction logic (`app/ioc_extractor.py`):**

Regex patterns:
| IOC Type | Pattern notes |
|---|---|
| `phone` | E.164 / local formats: `+?\d[\d\s\-().]{7,14}\d` — normalised to strip spaces/dashes |
| `email` | Standard RFC5322-lite pattern |
| `url` | `https?://\S+` + bare domains with TLD |
| `crypto` | BTC: `[13][a-km-zA-HJ-NP-Z1-9]{25,34}` / ETH: `0x[a-fA-F0-9]{40}` |
| `ip` | IPv4 only: `\b\d{1,3}(\.\d{1,3}){3}\b` (exclude private ranges 10.x, 192.168.x, 127.x) |
| `coords` | Decimal degrees: `-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}` |

Sources scanned: `messages.body`, `contacts.phone + contacts.email + contacts.raw_json`, `call_logs.number`

Deduplication: group by `(type, normalised_value)`, aggregate `occurrences` count and collect up to 5 source snippets per IOC.

Performance: runs a single pass over all messages + contacts for the case; at 50k messages takes < 1s in Python.

---

## Frontend

**New file:** `static/js/ioc.js`
**Tab:** "Intelligence" tab button added between Correlation and Analysis in `templates/index.html`

**Layout:**
```
[ Summary bar: 6 IOC type chips with counts ]

[ Type filter pills: All | Phone | Email | URL | Crypto | IP | Coords ]

[ IOC table:
  Value | Type | Occurrences | First Seen | Last Seen | Sources (N) | [Copy] [Jump]
]
```

Clicking "Sources (N)" expands an inline accordion showing up to 5 message snippets with platform badge + timestamp + body excerpt.

"Jump" opens the Conversations tab at that thread (reuses existing cross-tab navigation).

"Copy" copies the raw value to clipboard.

"Export CSV" button in the tab header downloads all visible IOCs as CSV.

---

## Data Flow

```
User opens Intelligence tab
  → GET /api/cases/<id>/ioc
  → ioc_extractor.py scans messages + contacts in DB
  → Returns deduplicated IOC list
  → ioc.js renders summary bar + table
```

No caching — always fresh scan. At 50k messages this is < 1s; acceptable.

---

## Error Handling

- Case not found → 404
- No messages → empty `iocs: []` with summary zeros; empty-state UI shown
- Malformed regex match (e.g. partial BTC address) → silently skipped; pattern tuned conservatively

---

## Testing

- `tests/test_ioc_extractor.py`: unit tests per pattern type (phone, email, url, crypto, ip, coords), deduplication, normalisation
- `tests/test_ioc_routes.py`: smoke tests for the API endpoint — empty case, case with known IOC data, type filter

---

## Files Changed

| File | Type |
|---|---|
| `app/ioc_extractor.py` | New — regex patterns + extraction logic |
| `app/routes/ioc.py` | New — Flask blueprint + single endpoint |
| `app/__init__.py` | Modified — register bp_ioc |
| `static/js/ioc.js` | New — Intelligence tab renderer |
| `templates/index.html` | Modified — tab button + panel |
| `static/style.css` | Modified — IOC table + type badge styles |
| `tests/test_ioc_extractor.py` | New |
| `tests/test_ioc_routes.py` | New |
