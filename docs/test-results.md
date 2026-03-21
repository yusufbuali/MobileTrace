# MobileTrace — Test Results & Evidence Ingestion Guide

**Date:** 2026-03-07 (updated same day with Android parser)
**App version:** Phases 1–6 complete + iOS parser + Android parser
**Test environment:** Python 3.13 (native), Docker container (Python 3.12)

---

## 1. Unit Test Results

### Full suite

```
125 passed, 9 warnings in 17.80s
```

| Test file | Tests | Status |
|---|---|---|
| `test_cases_routes.py` | 14 | ✅ all pass |
| `test_analysis_routes.py` | 5 | ✅ all pass |
| `test_chat_routes.py` | 5 | ✅ all pass |
| `test_retriever.py` | 5 | ✅ all pass |
| `test_reports.py` | 16 | ✅ all pass |
| `test_analyzer.py` | 4 | ✅ all pass |
| `test_parsers.py` | 19 | ✅ all pass |
| `test_ios_parser.py` | 19 | ✅ all pass |
| `test_android_parser.py` | 19 | ✅ all pass |
| `test_database.py` | 10 | ✅ all pass |
| `test_health.py` | 2 | ✅ all pass |
| `test_fts.py` | 7 | ✅ all pass |

**Total: 125 passing, 0 failing, 9 deprecation warnings (Python 3.13 datetime)**

---

## 2. Smoke Test Results (Live Docker container — port 5001)

| Endpoint | Expected | Result |
|---|---|---|
| `GET /api/health` | `{"status":"ok","app":"mobiletrace"}` | ✅ |
| `POST /api/cases` | Case created, UUID returned | ✅ |
| `GET /api/cases` | Returns array of cases | ✅ |
| `GET /api/cases/<id>` | Returns single case | ✅ |
| `GET /api/cases/<id>/messages/count` | `{"count": N}` | ✅ |
| `GET /api/cases/<id>/contacts/count` | `{"count": N}` | ✅ |
| `GET /api/cases/<id>/calls/count` | `{"count": N}` | ✅ |
| `GET /api/cases/<id>/analysis` | Returns array | ✅ |
| `GET /api/cases/<id>/evidence` | Returns array | ✅ |
| `GET /api/cases/<id>/graph` | `{"nodes":[...],"edges":[...]}` | ✅ |
| `GET /api/cases/<id>/report` | HTML with `dir="ltr"` | ✅ |
| `GET /api/cases/<id>/chat/history` | Returns array | ✅ |
| `GET /api/cases/nonexistent/report` | `{"error":"not found"}` 404 | ✅ |
| `GET /api/` | UI HTML loads | ✅ |
| UI sidebar | Case list renders | ✅ |
| UI case dashboard | Stats grid + tabs visible | ✅ |
| UI new case form | All fields render | ✅ |

---

## 3. Real Evidence Ingestion Results

### 3.1 iphone8.zip (iOS full filesystem ZIP — 8.2 GB)

```
POST /api/cases/<id>/evidence
Content-Type: application/json
{"source_path": "/opt/aift/evidence/iphone8.zip"}
```

**Result:**
```json
{
  "evidence_id": "bbbb7d7e-5dba-4190-a6dc-12dfa6bcf3c6",
  "format": "ios_fs",
  "device_info": {"platform": "ios", "sample_contact": "+18622176888"},
  "stats": {"calls": 0, "contacts": 0, "messages": 13},
  "warnings": ["Contacts parse error: no such table: ABPerson"]
}
```

**Forensic findings:**
- **13 SMS messages** extracted from `private/var/mobile/Library/SMS/sms.db`
- **Contacts:** AddressBook.sqlitedb present but empty (4 096 bytes, no ABPerson table) — device contacts may be encrypted or erased
- **Calls:** CallHistory.storedata present (74 KB schema) but 0 rows — call log cleared
- **Format detected:** `ios_fs` ✅

### 3.2 BelkaCTF_6_CASE240405_D201AP.tar (iOS full filesystem TAR — 4.8 GB)

```
POST /api/cases/<id>/evidence
Content-Type: application/json
{"source_path": "/opt/aift/evidence/BelkaCTF_6_CASE240405_D201AP.tar"}
```

**Result:**
```json
{
  "evidence_id": "fcdb2e82-3c96-4b8c-946c-c2059a9f10d0",
  "format": "ios_fs",
  "device_info": {"platform": "ios"},
  "stats": {"calls": 0, "contacts": 0, "messages": 0},
  "warnings": ["Contacts parse error: no such table: ABPerson"]
}
```

**Forensic findings:**
- **D201AP** = iPhone 8 model identifier
- **SMS:** sms.db present (288 KB, full schema) but **0 messages** — native SMS wiped
- **Calls:** CallHistory.storedata present but **0 rows** — call log wiped
- **Contacts:** AddressBook.sqlitedb is an empty placeholder (4 096 bytes) — no ABPerson table
- **TikTok:** 8 137 entries detected in the TAR — app data present (requires dedicated TikTok parser, outside current scope)
- **Forensic significance:** The wiping of native communications while app data remains is a key finding

---

## 4. Evidence Ingestion Guide

### 4.1 Supported formats

| Format | Extension | Parser | Status |
|---|---|---|---|
| iOS full filesystem ZIP | `.zip` | `iOSParser` | ✅ |
| iOS full filesystem TAR | `.tar` | `iOSParser` | ✅ |
| Android data TAR (raw) | `.tar` | `AndroidParser` | ✅ |
| Magnet Acquire Android | `.zip` (contains `.tar`) | `AndroidParser` | ✅ |
| Cellebrite UFDR | `.ufdr` | `UfdrParser` | ✅ |
| XRY / MSAB | `.zip` or folder with `.xrep` | `XryParser` | ✅ |
| Oxygen Forensics | `.ofb` | `OxygenParser` | ✅ |

### 4.2 What the iOS parser extracts

| Artifact | DB path (inside image) | Tables |
|---|---|---|
| SMS / iMessage | `private/var/mobile/Library/SMS/sms.db` | `message`, `handle` |
| Contacts | `private/var/mobile/Library/AddressBook/AddressBook.sqlitedb` | `ABPerson`, `ABMultiValue` |
| Call history | `private/var/mobile/Library/CallHistoryDB/CallHistory.storedata` | `ZCALLRECORD` |
| WhatsApp (if present) | `*/Documents/ChatStorage.sqlite` | `ZWAMESSAGE`, `ZWACHATSESSION` |

### 4.3 Method A — Upload small files via UI (< ~500 MB)

1. Go to `http://localhost:5001/api/`
2. Click **+ New Case** → fill in title and officer → **Create Case**
3. Click the case in the sidebar → click the **Evidence** tab
4. Choose file → **Upload**
5. The app parses immediately and shows stats on the Overview tab

### 4.4 Method B — Local path for large files (recommended for GB-sized images)

Large iOS dumps (GB range) must be ingested via the local path API.

**Step 1 — Place the file in the evidence folder:**
```
C:\claudecode projects\AIFT-final-1\MobileTrace\evidence\
   OR
C:\claudecode projects\AIFT-final-1\AIFT-DEPLOYMENT-2\evidence\
```
Both are mounted read-only inside the container at:
- `/opt/mobiletrace/evidence/`
- `/opt/aift/evidence/`

**Step 2 — Create a case:**
```bash
curl -X POST http://localhost:5001/api/cases \
  -H "Content-Type: application/json" \
  -d '{"title": "My Case", "officer": "Analyst"}'
# → returns {"id": "<case_id>", ...}
```

**Step 3 — Ingest the evidence by path:**
```bash
curl -X POST http://localhost:5001/api/cases/<case_id>/evidence \
  -H "Content-Type: application/json" \
  -d '{"source_path": "/opt/aift/evidence/iphone8.zip"}'
```

For a BelkaCTF TAR:
```bash
curl -X POST http://localhost:5001/api/cases/<case_id>/evidence \
  -H "Content-Type: application/json" \
  -d '{"source_path": "/opt/aift/evidence/BelkaCTF_6_CASE240405_D201AP.tar"}'
```

**Step 4 — Check the result:**
The response contains:
```json
{
  "format": "ios_fs",
  "device_info": {"platform": "ios"},
  "stats": {"messages": N, "contacts": N, "calls": N},
  "warnings": []
}
```

**Step 5 — Open the UI and view the case:**
Go to `http://localhost:5001/api/` → click the case → Overview tab shows stats.

### 4.5 Security constraints

The local path API only accepts paths under:
- `/opt/mobiletrace/evidence/` (MobileTrace's own evidence folder)
- `/opt/aift/evidence/` (AIFT shared evidence folder)

Any other path returns `403 Forbidden`.

---

## 5. iOS Timestamp Notes

Apple Core Data timestamps are seconds since **2001-01-01T00:00:00 UTC** (not Unix epoch 1970).
MobileTrace's `iOSParser` automatically converts these using the offset `978307200`.
iOS 17+ may store timestamps in nanoseconds — this is also handled automatically.

---

## 5b. Android Parser — What It Extracts

| Artifact | Source DB | Tables |
|---|---|---|
| SMS / MMS | `com.android.providers.telephony/databases/mmssms.db` | `sms` |
| Call log | `com.android.providers.contacts/databases/calllog.db` | `calls` |
| Contacts | `com.android.providers.contacts/databases/contacts2.db` | `raw_contacts`, `data`, `mimetypes` |
| WhatsApp messages | `com.whatsapp/databases/msgstore.db` | `messages` (old) or `message`+`jid` (new) |
| WhatsApp contacts | `com.whatsapp/databases/wa.db` | `wa_contacts` |
| Telegram | `org.telegram.messenger/files/cache4.db` | `messages_v2`, `user_contacts_v7` |
| Signal | `org.thoughtcrime.securesms/databases/signal.db` | **SQLCipher encrypted — skipped** |

### 3.3 Android_12_Tar_File.zip (Magnet Acquire — Google Pixel 3 Android 12 — 16 GB ZIP / 25 GB TAR)

```
POST /api/cases/<id>/evidence
Content-Type: application/json
{"source_path": "/opt/aift/evidence/android 12 tar file/Android_12_Tar_File.zip"}
```

**Result:**
```json
{
  "format": "android_tar",
  "device_info": {"platform": "android"},
  "stats": {"calls": 30, "contacts": 8, "messages": 86},
  "warnings": ["Signal database (signal.db) is SQLCipher-encrypted — cannot parse without decryption key"]
}
```

**Device info (from Magnet Acquire image_info.txt):**
- Manufacturer: Google · Model: Pixel 3 · OS: Android 12 · Serial: 8CEX1N716
- Acquired: 2021-12-16 with Magnet ACQUIRE v2.46.0

**Forensic findings:**
| Source | Count | Notable content |
|---|---|---|
| SMS | 32 | Verification OTPs: Signal, WhatsApp, Telegram, TikTok, Clubhouse, LINE, GroupMe |
| WhatsApp | 24 | Conversations with "Josh Hickman" / "This Is DFIR Two" |
| Telegram | 30 | Login codes + short messages with contacts Josh Hickman, This Is DFIR Two |
| Calls | 30 | Mix of voicemail (type 4) and missed (type 3) |
| Android contacts | 5 | James Test, Josh Hickman (×2), This Is DFIR, This Is DFIR Two |
| WhatsApp contacts | 3 | Josh Hickman ×2 numbers, This Is DFIR Two |
| Signal | — | Encrypted (SQLCipher) — skipped with warning |
| Threema | — | Not yet parsed (future parser) |
| Viber | — | Not yet parsed (future parser) |

---

## 6. Known Limitations

| Limitation | Notes |
|---|---|
| Encrypted AddressBook | Both test images had empty `AddressBook.sqlitedb` (common when device uses full-disk encryption or contacts were erased) |
| TikTok / third-party app DBs | Not parsed — requires dedicated app parsers |
| Large file upload via form | HTTP multipart upload is impractical above ~500 MB — use local path method (Method B) |
| WhatsApp | Neither test image contained `ChatStorage.sqlite` — iOS WhatsApp stores data per-app-container |
