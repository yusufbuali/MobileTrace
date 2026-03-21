# Call Log Analysis Instructions

You are analyzing call history data from a mobile device.

## Normalized Data Structure
Each call record contains:
- `platform` — `"phone"`, `"facetime_video"`, or `"facetime_audio"`
- `number` — phone number contacted
- `direction` — `"incoming"`, `"outgoing"`, or `"missed"`
- `duration_s` — call duration in seconds (0 for missed)
- `timestamp` — ISO 8601 UTC string

## Platform Note
Call metadata alone cannot confirm content. Mark all call-derived crime indicators as `inferred`.

## Analysis Requirements

### 1. Contact Risk Assessment (REQUIRED)
```
## Contact Risk Assessment

| Phone Number | Calls | Total Duration | Outgoing | Incoming | Missed | Risk Score | Risk Level | Indicators |
|--------------|-------|----------------|----------|----------|--------|------------|------------|------------|
| +9731234567 | 12 | 47 min | 8 | 4 | 0 | 7/10 | HIGH | High frequency near incident, long durations |
```

### 2. Key Findings
- Calls around incident dates/times (flag explicitly)
- Frequent contacts — establish significance
- Missed call patterns (avoided contact)
- Very long calls (>10 min) or very short calls (<10 sec, potential coded signals)
- International calls with unfamiliar country codes
- Calls at unusual hours (late night, early morning)

### 3. Communication Patterns
- Total call volume per contact
- Outgoing vs incoming ratio per contact
- Call frequency changes over time (escalation near incident)
- Last contact before/after incident date

### 4. Special Flags
- Calls to emergency services (999, 911, 112, 998, 993)
- International calls (flag country code)
- FaceTime calls (platform=facetime_video/facetime_audio) — indicate Apple device cross-communication

### 5. Crime Indicator Detection
Scan all data for indicators matching the crime categories in the system prompt. For each category with supporting evidence, create a `crime_indicators` entry with at least one `evidence_ref` citing timestamp + quoted text. Do not tag without citable evidence.

## Output Format

Return ONLY valid JSON — no markdown fences, no explanation text outside the JSON.

```json
{
  "risk_level_summary": "One-sentence overall risk assessment",
  "confidence_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "data_coverage": {
    "records_analyzed": 300,
    "total_records": 450,
    "coverage_percent": 66.7,
    "note": "Analysis covers first 300 of 450 records by timestamp"
  },
  "conversation_risk_assessment": [
    {
      "thread_id": "+1234567890",
      "calls": 12,
      "messages": 12,
      "sent": 8,
      "received": 4,
      "duration_s": 2820,
      "risk_score": 7,
      "risk_level": "HIGH",
      "key_indicators": ["High frequency near incident date", "Long duration calls"]
    }
  ],
  "key_findings": [
    {
      "thread_id": "+1234567890",
      "summary": "Forensic significance of this contact's call pattern",
      "confidence": "observed|inferred",
      "key_messages": []
    }
  ],
  "crime_indicators": [
    {
      "category": "ORGANIZED_CRIME",
      "confidence": "inferred",
      "severity": "MEDIUM",
      "evidence_refs": [
        { "timestamp": "2021-12-11T03:22:00Z", "thread_id": "+1234567890", "quote": "call metadata only — no content", "direction": "outgoing" }
      ],
      "summary": "Why this pattern indicates the category"
    }
  ]
}
```
