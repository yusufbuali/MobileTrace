# MobileTrace Parsing Workflow

> Last updated: 2026-03-08

## End-to-End Flow

Evidence upload reaches upload_evidence() in app/routes/cases.py.
The file is saved then passed to _ingest_path() which calls dispatcher.py.

dispatcher._PARSERS order (first can_handle() match wins):
  1. UfdrParser       (.ufdr)
  2. AndroidParser    (.zip or .tar containing data/data/ paths)
  3. XryParser        (.xrep)
  4. OxygenParser     (.ofb)
  5. iOSParser        (.zip or .tar containing private/var/mobile/ paths)

## UfdrParser  (app/parsers/ufdr_parser.py)

Handles Cellebrite UFDR exports.

  try: import mobile_ingest from /aift_mobile (AIFT Docker volume)
       -> mi.extract_evidence() - AIFT UFDR engine (Type A+B, 2GB cap)
       -> returns device_info + .db paths
  except ImportError: _parse_standalone()
       -> reads Metadata.xml or ufed_report.xml
       -> extracts .db/.sqlite/.plist/.xml files
       -> returns raw_db_paths only (no messages/contacts parsed)

## AndroidParser  (app/parsers/android_parser.py)

Handles Magnet Acquire ZIP+TAR and raw Android data-partition TARs.
Detection: scans up to 5000 entries for data/data/ or data/user/ prefixes.

Target DBs extracted from TAR:
  sms      -> com.android.providers.telephony/databases/mmssms.db
  calllog  -> com.android.providers.contacts/databases/calllog.db
  contacts -> com.android.providers.contacts/databases/contacts2.db
  wa_msg   -> com.whatsapp/databases/msgstore.db
  wa_ct    -> com.whatsapp/databases/wa.db
  telegram -> org.telegram.messenger/files/cache4.db
  signal   -> org.thoughtcrime.securesms/databases/signal.db  [SKIPPED - encrypted]

sqlite3 parsers:
  _read_sms()          mmssms.db    sms table               -> messages (sms)
  _read_calls()        calllog.db   calls table             -> call_logs
  _read_contacts()     contacts2.db raw_contacts+data+mime  -> contacts
  _read_wa_contacts()  wa.db        wa_contacts             -> contacts (whatsapp)
  _read_whatsapp()     msgstore.db  old schema: data col
                                    new schema: text_data+jid -> messages (whatsapp)
  _read_telegram()     cache4.db    messages_v2 TLV binary, ASCII string extract
                                                            -> messages (telegram)

Signal.db: detected, extracted, NOT parsed. SQLCipher encrypted. Warning added.

## iOSParser  (app/parsers/ios_parser.py)

Handles iOS full-filesystem TAR and ZIP dumps.
Detection: scans up to 5000 entries for private/var/mobile|root|wireless/ prefixes.

Target DBs extracted:
  sms      -> private/var/mobile/Library/SMS/sms.db
  contacts -> private/var/mobile/Library/AddressBook/AddressBook.sqlitedb
  calls    -> private/var/mobile/Library/CallHistoryDB/CallHistory.storedata
  whatsapp -> **/Documents/ChatStorage.sqlite (suffix match)

sqlite3 parsers:
  _read_sms()         sms.db              message+handle, Apple epoch +978307200s
                                          -> messages (sms)  [PARTIAL: no groups/attachments]
  _read_contacts()    AddressBook.sqlitedb ABPerson+ABMultiValue  -> contacts
  _read_calls()       CallHistory.storedata ZCALLRECORD           -> call_logs
  _read_whatsapp()    ChatStorage.sqlite  ZWAMESSAGE+ZWACHATSESSION -> messages (whatsapp)
  _read_device_info() sms.db              handle table sample number

GAPS: Telegram on iOS not parsed. iMessage group chats and attachments not captured.

## XryParser  (app/parsers/xry_parser.py)
Handles XRY .xrep exports (XML-based).

## OxygenParser  (app/parsers/oxygen_parser.py)
Handles Oxygen Forensic .ofb exports (proprietary container).

## Common Output: ParsedCase  (app/parsers/base.py)

  format: str           # ufdr | android_tar | ios_fs | xry | oxygen
  device_info: dict     # model, imei, os_version, platform
  contacts: list[dict]  # name, phone, email, source_app, raw_json
  messages: list[dict]  # platform, direction, sender, recipient, body, timestamp, thread_id
  call_logs: list[dict] # number, direction, duration_s, timestamp, platform
  raw_db_paths: list    # paths to extracted .db files
  warnings: list[str]   # non-fatal parse issues

## Storage  (app/routes/cases.py: _store_parsed)

  contacts    -> contacts table
  messages    -> messages table + messages_fts FTS5 virtual table
  call_logs   -> call_logs table
  device_info -> cases.device_info (JSON column)

## Downstream Consumers

  Conversations tab : GET /api/cases/<id>/threads + /messages[?platform&thread&q]
                      FTS5 search via messages_fts
  Chat tab          : GET /api/cases/<id>/chat (FTS retrieval -> LLM)
                      app/retriever.py: fts_retrieve()
  Analysis tab      : POST /api/cases/<id>/analyze
                      app/analyzer.py: MobileAnalyzer -> LLM per artifact type
  Report            : GET /api/cases/<id>/report
                      templates/report.html structured JSON rendering

## iLEAPP / ALEAPP: NOT USED

  Format            Parser          iLEAPP/ALEAPP?
  ────────────────  ──────────────  ─────────────────────────────────────────────────
  .ufdr Cellebrite  UfdrParser      No - AIFT mobile_ingest.py for extraction + sqlite3
  Android TAR/ZIP   AndroidParser   No - direct sqlite3 against known DB paths
  iOS TAR/ZIP       iOSParser       No - direct sqlite3 against known DB paths
  XRY .xrep         XryParser       No - XML report parsing
  Oxygen .ofb       OxygenParser    No - proprietary container parsing

iLEAPP/ALEAPP target raw filesystem images. MobileTrace targets forensic export formats
where DBs are already accessible. Raw image ingest is not on the current roadmap.

## Known Gaps (Planned)

  Signal Android  - SQLCipher encrypted, skipped    -> docs/plans/2026-03-08-missing-parsers.md
  iMessage iOS    - group chats and attachments      -> docs/plans/2026-03-08-missing-parsers.md
  Telegram iOS    - not implemented                  -> docs/plans/2026-03-08-missing-parsers.md
