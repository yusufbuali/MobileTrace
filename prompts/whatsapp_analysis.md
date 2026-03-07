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

## Output Must Include
- Conversation Risk Assessment table
- Total message count, date range, unique contacts
- CRITICAL/HIGH/MEDIUM/LOW confidence label at the end
