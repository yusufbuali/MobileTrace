# MobileTrace — Extractor Schemas Reference

Accurate DB schemas for each extractor, confirmed against AIFT production queries
(`leapp_integration.py`, `chat_deep_parse.py`, `mobile_forensics.py`) and forensic tool
documentation. Updated 2026-03-07.

---

## What Forensic Tools Actually Produce

| Tool | Output for raw-FS (Type A) | Output for decoded (Type B) |
|---|---|---|
| **Cellebrite UFDR** | Extracted SQLite DBs from filesystem | `report.xml` — pre-decoded XML, not SQLite |
| **XRY** | Raw SQLite DBs (inside ZIP / folder) | `.xrep` XML — pre-decoded, not SQLite |
| **Oxygen OFB** | `.ofb` = their own SQLite, already decoded | Same file |
| **GrayKey** | Decrypted filesystem copy | CSV/JSON exports |

**Implication:** The extractors in `app/extractors/` target Type A (raw SQLite).
For UFDR Type B / XRY XREP, data is already in the `ParsedCase` after the parser layer.

---

## Encryption Caveats

| App | Encrypted on-device? | Forensic tool handling |
|---|---|---|
| **WhatsApp Android** | Yes (WA crypt14/15) | UFDR/XRY decrypt during extraction |
| **WhatsApp iOS** | iOS keychain protected | UFDR/XRY decrypt during extraction |
| **Telegram Android** | Yes — SQLCipher (v4+) | Only Cellebrite PA and some GrayKey targets can decrypt; else data comes via XML report |
| **Telegram iOS** | Yes — SQLCipher | Same as Android |
| **Signal Android** | Yes — SQLCipher | Forensic tools write decrypted plaintext copy; extractor reads that |
| **Signal iOS** | Yes — grdb/SQLCipher | No reliable raw-DB extraction; data via UFDR XML only |
| **iOS SMS** | iOS keychain protected | UFDR/XRY provide decrypted `sms.db` |
| **iOS Calls** | iOS keychain protected | UFDR/XRY provide decrypted `call_history.db` |

---

## WhatsApp

### Android — `msgstore.db`
Path: `data/data/com.whatsapp/databases/msgstore.db`

```sql
-- Messages
SELECT key_remote_jid,   -- JID e.g. "9731234567@s.whatsapp.net"
       key_from_me,      -- 1 = outgoing, 0 = incoming
       data,             -- message body (NULL for media)
       timestamp         -- Unix milliseconds
FROM messages;
```

Direction: `key_from_me = 1` → outgoing.
Strip `@s.whatsapp.net` suffix to get phone number.

### iOS — `ChatStorage.sqlite`
Path: `AppDomainGroup-group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`

```sql
SELECT ZWAMESSAGE.ZFROMJID,
       ZWAMESSAGE.ZTOJID,
       ZWAMESSAGE.ZISFROMME,   -- 1 = outgoing
       ZWAMESSAGE.ZTEXT,
       ZWAMESSAGE.ZMESSAGEDATE -- Apple Core Data epoch (seconds since 2001-01-01)
FROM ZWAMESSAGE
JOIN ZWACHATSESSION ON ZWAMESSAGE.ZCHATSESSION = ZWACHATSESSION.Z_PK;
```

Timestamp: `unix_ts = ZMESSAGEDATE + 978307200`

---

## Telegram

### Android — `cache4.db`
Path: `data/data/org.telegram.messenger/files/cache4.db`

**⚠ SQLCipher encrypted (Telegram v4+, 2018+).** The extractor only works on
a decrypted copy produced by the forensic tool. An encrypted DB raises
`sqlite3.DatabaseError: file is not a database` — caught and logged.

```sql
-- Users lookup
SELECT uid, first_name, last_name, username FROM users;

-- Messages (with optional dialogs join)
SELECT messages.mid, messages.uid, messages.date,  -- date = Unix seconds
       messages.message, messages.out AS direction, -- out=1 → sent
       dialogs.did AS dialog_id
FROM messages
LEFT JOIN dialogs ON messages.uid = dialogs.did
ORDER BY messages.date ASC;
```

### iOS — `TGDatabase` / `TGMessage`
Path: `Documents/` inside Telegram app container.

```sql
SELECT mid, cid, date, message, outgoing FROM TGMessage ORDER BY date ASC;
```

Also SQLCipher-encrypted on modern builds.

---

## Signal

### Android — `signal.db`
Path: `data/data/org.thoughtcrime.securesms/databases/signal.db`

**SQLCipher-encrypted on-device.** Forensic tools write a decrypted plaintext copy.

Older builds (pre-v5, pre-2021):
```sql
SELECT address, date_sent AS date,   -- date_sent = Unix milliseconds
       body, type
FROM sms ORDER BY date_sent ASC;
-- type: 1=inbox (incoming), 2=sent (outgoing)
```

Newer builds (Signal v5+):
```sql
SELECT to_recipient_id AS address, date_sent AS date, body, type
FROM message ORDER BY date_sent ASC;
```

`type` field is a bitmask: `type & 0x1f` gives base type (1=incoming, 2=outgoing).

### iOS — `signal.sqlite`
Uses grdb (SQLCipher variant). No standardised raw-SQL query available.
Data comes via UFDR report.xml or XRY XREP XML after tool decryption.
The iOS branch of `extract_signal()` returns `[]` with a logged warning.

---

## SMS / MMS

### Android — `mmssms.db`
Path: `data/data/com.android.providers.telephony/databases/mmssms.db`

```sql
SELECT address, body,
       date,   -- Unix milliseconds
       type    -- 1=inbox (incoming), 2=sent (outgoing)
FROM sms ORDER BY date ASC;
```

### iOS — `sms.db`
Path: `HomeDomain/Library/SMS/sms.db`

```sql
SELECT h.id AS address,   -- phone number from handle table
       m.text AS body,
       m.date AS ts,      -- Apple Core Data epoch (s before iOS 11, ns from iOS 11+)
       m.is_from_me       -- 1 = outgoing
FROM message m
LEFT JOIN handle h ON m.handle_id = h.ROWID
ORDER BY m.date ASC;
```

Timestamp conversion:
```python
APPLE_EPOCH_OFFSET = 978307200
if ts > 1e10:   # nanoseconds (iOS 11+)
    ts = ts / 1e9
unix_ts = ts + APPLE_EPOCH_OFFSET
```

---

## Call Logs

### Android — `contacts2.db`
Path: `data/data/com.android.providers.contacts/databases/contacts2.db`

```sql
SELECT number, duration,   -- duration in seconds
       date,               -- Unix milliseconds
       type                -- 1=incoming, 2=outgoing, 3=missed, 4=voicemail
FROM calls ORDER BY date ASC;
```

### iOS — `call_history.db`
Path: `HomeDomain/Library/CallHistoryDB/CallHistory.storedata`

```sql
SELECT ZADDRESS,           -- phone number
       ZDURATION,          -- seconds (float)
       ZDATE,              -- Apple Core Data epoch (seconds since 2001-01-01)
       ZORIGINATED,        -- 1 = device placed call (outgoing); 0 = incoming / missed
       ZANSWERED,          -- 1 = call was answered
       ZCALLTYPE           -- 1=phone, 8=FaceTime video, 16=FaceTime audio
FROM ZCALLRECORD ORDER BY ZDATE ASC;
```

Direction logic:
```python
if ZORIGINATED:    direction = "outgoing"
elif ZANSWERED:    direction = "incoming"
else:              direction = "missed"
```

---

## Contacts

### Android — `contacts2.db`
```sql
SELECT raw_contacts._id, raw_contacts.display_name,
       data.data1 AS value, mimetypes.mimetype AS type
FROM raw_contacts
JOIN data ON raw_contacts._id = data.raw_contact_id
JOIN mimetypes ON data.mimetype_id = mimetypes._id
WHERE mimetypes.mimetype IN (
    'vnd.android.cursor.item/phone_v2',
    'vnd.android.cursor.item/email_v2'
);
```

### iOS — `AddressBook.sqlitedb`
```sql
SELECT ABPerson.ROWID, ABPerson.First, ABPerson.Last,
       ABMultiValue.value, ABMultiValueLabel.value AS label_type
FROM ABPerson
LEFT JOIN ABMultiValue ON ABPerson.ROWID = ABMultiValue.record_id
LEFT JOIN ABMultiValueLabel ON ABMultiValue.label = ABMultiValueLabel.ROWID;
```

---

## Apple Core Data Epoch Helper

```python
from datetime import datetime, timezone

APPLE_EPOCH_OFFSET = 978307200  # seconds

def apple_to_iso(ts: float) -> str:
    if ts > 1e10:   # nanoseconds (iOS 11+)
        ts /= 1e9
    return datetime.fromtimestamp(ts + APPLE_EPOCH_OFFSET, tz=timezone.utc).isoformat()
```

---

## Adding a New Extractor

Follow the `mt-add-extractor` skill checklist:
1. Create mock SQLite DB in test (matching real app schema from this doc)
2. Write failing test in `tests/test_extractors.py`
3. Implement extractor in `app/extractors/<platform>.py`
4. Add `platform` parameter if Android/iOS schemas differ
5. Commit: `feat(mobiletrace): <name> extractor -- <db file> <platform>`
