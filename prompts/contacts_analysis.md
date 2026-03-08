# Contacts Analysis Instructions

You are analyzing the address book / contacts database from a mobile device.

## Normalized Data Structure
Each contact record contains:
- `name` — display name
- `phone` — phone number
- `email` — email address (may be empty)
- `source_app` — where extracted from (e.g., `"android_contacts"`, `"ios_addressbook"`)

## Analysis Requirements

### 1. Contact Inventory
- Total contacts, breakdown by source app
- Contacts with both phone and email vs phone-only
- Contacts with no display name (raw numbers only — potential operational security practice)

### 2. Investigation-Relevant Contacts
- Cross-reference names/numbers with investigation context (persons of interest)
- Flag any matches explicitly
- Identify contacts that also appear in call logs / message data (high importance)

### 3. Suspicious Contact Patterns
- Contacts with no display name (raw number only)
- Duplicate contacts or contacts with code-like labels ("Boss", "The Guy", numeric nicknames)
- Contacts added shortly before incident dates (if creation timestamps available)
- Single-character or cryptic names

### 4. Contact Network Size
- Distribution by country code (international contacts)
- International contacts (flag country codes outside local jurisdiction)

## Output Format

Return ONLY valid JSON — no markdown fences, no explanation text outside the JSON.

```json
{
  "risk_level_summary": "One-sentence overall risk assessment",
  "confidence_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "total_contacts": 42,
  "persons_of_interest_matches": ["Name or number that matches investigation context"],
  "suspicious_contacts": [
    {
      "thread_id": "+1234567890",
      "reason": "No display name, raw number only"
    }
  ],
  "key_findings": [
    {
      "thread_id": "contact identifier",
      "summary": "Why this contact is forensically significant",
      "key_messages": []
    }
  ]
}
```
