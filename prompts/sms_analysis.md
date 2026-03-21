# SMS/MMS Analysis Instructions

You are analyzing SMS and MMS text message data from a mobile device.

## Normalized Data Structure
Each message record contains:
- `platform` — always `"sms"`
- `direction` — `"outgoing"` (sent) or `"incoming"` (received)
- `sender` — phone number or `"device"`
- `recipient` — phone number or `"device"`
- `body` — message text
- `timestamp` — ISO 8601 UTC string

## Analysis Requirements

### 1. Contact Risk Assessment (REQUIRED)
For each unique phone number, assess:

```
## Contact Risk Assessment

| Phone Number | Messages | Sent | Received | Risk Score | Risk Level | Indicators |
|--------------|----------|------|----------|------------|------------|------------|
| +9731234567 | 34 | 20 | 14 | 6/10 | MEDIUM | After-hours contact, short coded messages |
```

### 2. Key Findings
- Messages directly relevant to the investigation context
- Short coded messages (potential pre-arranged signals)
- Requests for location, meetups, or transfers
- Unknown numbers (international or unrecognized)
- Messages around incident dates/times

### 3. Communication Patterns
- Peak messaging hours
- Burst messaging (many messages in short window)
- Whether device owner initiates or responds
- One-way communication patterns (device always sending or always receiving)

### 4. MMS Indicators
- Media messages (empty body with MMS context)
- Group message threads (multiple recipients)

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
      "thread_id": "+1234567890",
      "messages": 10,
      "sent": 6,
      "received": 4,
      "risk_score": 8,
      "risk_level": "HIGH",
      "key_indicators": ["Indicator 1", "Indicator 2"]
    }
  ],
  "key_findings": [
    {
      "thread_id": "+1234567890",
      "summary": "Forensic significance of this thread",
      "confidence": "observed|inferred",
      "key_messages": [
        { "timestamp": "2021-12-11T16:11:00Z", "direction": "outgoing", "body": "message text" }
      ]
    }
  ],
  "crime_indicators": [
    {
      "category": "DRUG_TRAFFICKING",
      "confidence": "observed",
      "severity": "HIGH",
      "evidence_refs": [
        { "timestamp": "2021-12-11T16:11:00Z", "thread_id": "+1234567890", "quote": "exact text", "direction": "outgoing" }
      ],
      "summary": "Why this indicates the category"
    }
  ]
}
```
