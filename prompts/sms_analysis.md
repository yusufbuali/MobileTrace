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

## Output Must Include
- Contact Risk Assessment table
- Total message count, date range, unique contacts
- CRITICAL/HIGH/MEDIUM/LOW confidence label
