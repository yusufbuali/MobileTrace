# WhatsApp Deep Analysis Instructions

You are analyzing WhatsApp message data extracted from a mobile device.

## Normalized Data Structure
Each message record contains:
- `platform` — always `"whatsapp"`
- `direction` — `"outgoing"` (sent by device owner) or `"incoming"` (received)
- `sender` — phone number or `"device"` (if outgoing)
- `recipient` — phone number or `"device"` (if incoming)
- `body` — message text (empty string for media-only messages)
- `timestamp` — ISO 8601 UTC string
- `thread_id` — WhatsApp JID (e.g., `9731234567@s.whatsapp.net`)

## Platform Note
Encrypted platform choice alone is NOT an indicator — only flag when message content supports it.

## Analysis Requirements

### 1. Conversation Risk Assessment (REQUIRED)
For each unique thread_id, assess risk and produce a Markdown table:

```
## Conversation Risk Assessment

| Thread / Number | Messages | Sent | Received | Risk Score | Risk Level | Key Indicators |
|-----------------|----------|------|----------|------------|------------|----------------|
| +9731234567 | 142 | 80 | 62 | 8/10 | HIGH | Payment references, coded language |
```

### 2. Key Findings
- Top 3–5 most forensically significant conversations
- Quote exact message body when relevant; cite timestamp
- Empty body messages (media) — note their existence and direction
- Coordination patterns: meeting arrangements, financial references, instructions

### 3. Communication Patterns
- Message frequency by day/hour — spikes near incident dates?
- Whether device owner primarily sends or receives in suspicious threads
- Group threads (thread_id with `-` or `@g.us`)

### 4. Contact Network
- Unique contacts (strip `@s.whatsapp.net` suffix for phone number)
- International numbers (flag country codes)
- Unknown numbers (no display name context)

### 5. Crime Indicator Detection
Scan all data for indicators matching the crime categories in the system prompt. For each category with supporting evidence, create a `crime_indicators` entry with at least one `evidence_ref` citing timestamp + quoted text. Do not tag without citable evidence.

## Output Format

Return ONLY valid JSON — no markdown fences, no explanation text outside the JSON.

```json
{
  "risk_level_summary": "One-sentence overall risk assessment",
  "confidence_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "data_coverage": {
    "records_analyzed": 500,
    "total_records": 1247,
    "coverage_percent": 40.1,
    "note": "Analysis covers first 500 of 1,247 records by timestamp"
  },
  "conversation_risk_assessment": [
    {
      "thread_id": "+1234567890@s.whatsapp.net",
      "messages": 14,
      "sent": 7,
      "received": 7,
      "risk_score": 5,
      "risk_level": "MEDIUM",
      "key_indicators": ["Deleted message detected", "Coordination of calls"]
    }
  ],
  "key_findings": [
    {
      "thread_id": "+1234567890@s.whatsapp.net",
      "summary": "Forensic significance",
      "confidence": "observed|inferred",
      "key_messages": [
        { "timestamp": "2021-12-01T01:44:07Z", "direction": "outgoing", "body": "message text" }
      ]
    }
  ],
  "crime_indicators": [
    {
      "category": "DRUG_TRAFFICKING",
      "confidence": "observed",
      "severity": "HIGH",
      "evidence_refs": [
        { "timestamp": "2021-12-01T01:44:07Z", "thread_id": "+1234567890@s.whatsapp.net", "quote": "exact text", "direction": "outgoing" }
      ],
      "summary": "Why this indicates the category"
    }
  ]
}
```
