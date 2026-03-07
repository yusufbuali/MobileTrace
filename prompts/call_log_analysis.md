# Call Log Analysis Instructions

You are analyzing call history data from a mobile device.

## Normalized Data Structure
Each call record contains:
- `platform` — `"phone"`, `"facetime_video"`, or `"facetime_audio"`
- `number` — phone number contacted
- `direction` — `"incoming"`, `"outgoing"`, or `"missed"`
- `duration_s` — call duration in seconds (0 for missed)
- `timestamp` — ISO 8601 UTC string

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

## Output Must Include
- Contact Risk Assessment table
- Total call count, date range, top contacts by duration and frequency
- CRITICAL/HIGH/MEDIUM/LOW confidence label
