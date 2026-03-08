# Telegram Deep Analysis Instructions

You are analyzing Telegram message data extracted from a mobile device.

## Normalized Data Structure
Each message record contains:
- `platform` — always `"telegram"`
- `direction` — `"outgoing"` (sent) or `"incoming"` (received)
- `sender` — display name (resolved from users table) or `"device"`
- `recipient` — display name or `"device"`
- `body` — message content
- `timestamp` — ISO 8601 UTC string
- `thread_id` — dialog ID (numeric string)

## Critical Context
Telegram is heavily used for encrypted group coordination, channels, self-destructing messages,
and secret chats. SQLCipher-encrypted databases (Telegram v4+) may yield no message content —
in that case, the existence of Telegram itself is forensically significant.

## Analysis Requirements

### 1. Conversation Risk Assessment (REQUIRED)
For each unique thread_id/contact, produce a risk table:

```
## Conversation Risk Assessment

| Contact / Dialog | Messages | Risk Score | Risk Level | Key Indicators |
|------------------|----------|------------|------------|----------------|
| Bob Smith | 89 | 7/10 | HIGH | Coordination language, file references |
```

### 2. Encryption Status
- If data is present: note the database was successfully decrypted by the forensic tool
- If no data / empty result: "Telegram database appears SQLCipher-encrypted. Data not accessible."
  Flag as HIGH risk — encrypted communication with inaccessible content.

### 3. Key Findings
- Most active conversations by message count
- Forensically relevant message content (cite timestamp)
- Unknown senders (numeric ID only, no name resolved)
- Short coded messages

### 4. Channel and Group Analysis
Numeric thread IDs (dialog_id > 1,000,000,000 often indicate channels/supergroups):
- What content the user communicated about
- Whether device owner was primarily sending or receiving

## Output Format

Return ONLY valid JSON — no markdown fences, no explanation text outside the JSON.

```json
{
  "risk_level_summary": "One-sentence overall risk assessment",
  "confidence_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "encryption_status": "Decrypted successfully | SQLCipher-encrypted — content not accessible",
  "conversation_risk_assessment": [
    {
      "thread_id": "dialog_id_or_contact_name",
      "messages": 18,
      "sent": 9,
      "received": 9,
      "risk_score": 7,
      "risk_level": "HIGH",
      "key_indicators": ["Coded language", "File references"]
    }
  ],
  "key_findings": [
    {
      "thread_id": "dialog_id_or_contact_name",
      "summary": "Forensic significance",
      "key_messages": [
        { "timestamp": "2021-11-25T19:33:08Z", "direction": "incoming", "body": "message text" }
      ]
    }
  ]
}
```
