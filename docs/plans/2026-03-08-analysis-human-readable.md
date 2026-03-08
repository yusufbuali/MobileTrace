# Analysis Human-Readable Output Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make analysis results human-readable by (A) normalizing inconsistent LLM JSON schemas in the renderer and (B) enforcing a strict JSON schema in every prompt file so future runs are consistent.

**Architecture:** Two files change on the JS side (`static/js/chat.js` — add `_normalizeAnalysis()` called before `_renderJsonAnalysis()`). Six prompt files change to append an explicit JSON output block. No backend changes, no new dependencies.

**Root cause:** The LLM returns structurally inconsistent JSON across artifact types — WhatsApp/Telegram wrap data under `"analysis"`, SMS uses `contact_risk_assessment` instead of `conversation_risk_assessment`, `key_findings` is sometimes a list not a dict, `key_indicators` is sometimes a string not an array. Unrecognized fields fall to the generic KV grid which `JSON.stringify()`s nested objects → raw JSON wall.

**Tech Stack:** Vanilla JS ES modules, markdown prompt files.

---

## Task 1 — Add `_normalizeAnalysis()` to `chat.js`

**Files:**
- Modify: `static/js/chat.js`

### Step 1: Find insertion point

The function goes **immediately before** `_renderJsonAnalysis` (currently around line 289):
```javascript
function _renderJsonAnalysis(p, container) {
```

### Step 2: Insert `_normalizeAnalysis` before `_renderJsonAnalysis`

```javascript
// ── Analysis JSON normalizer ──────────────────────────────────────────────────
// LLMs return inconsistent field names and nesting. This maps everything to the
// canonical schema before rendering.

function _normalizeAnalysis(raw) {
  let p = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};

  // 1. Unwrap "analysis" wrapper  e.g. { "analysis": { ... } }
  if (p.analysis && typeof p.analysis === "object" && !Array.isArray(p.analysis)) {
    p = { ...p.analysis, ...p };
    delete p.analysis;
  }

  // 2. Alias contact_risk_assessment → conversation_risk_assessment
  if (!p.conversation_risk_assessment && p.contact_risk_assessment) {
    p.conversation_risk_assessment = p.contact_risk_assessment;
  }

  // 3. Normalize each CRA item's field names
  if (Array.isArray(p.conversation_risk_assessment)) {
    p.conversation_risk_assessment = p.conversation_risk_assessment.map(item => ({
      ...item,
      // thread_id alias: phone_number / contact / number
      thread_id: item.thread_id || item.phone_number || item.contact || item.number || "—",
      // messages alias: calls
      messages: item.messages ?? item.calls ?? 0,
      // sent alias: outgoing
      sent: item.sent ?? item.outgoing ?? 0,
      // received alias: incoming
      received: item.received ?? item.incoming ?? 0,
      // key_indicators: string → array, or indicators alias
      key_indicators: Array.isArray(item.key_indicators)
        ? item.key_indicators
        : item.key_indicators
          ? [item.key_indicators]
          : Array.isArray(item.indicators) ? item.indicators : [],
    }));
  }

  // 4. Normalize key_findings: array → { top_significant_conversations: [...] }
  if (Array.isArray(p.key_findings)) {
    p.key_findings = {
      top_significant_conversations: p.key_findings.map(f => ({
        thread_id: f.thread_id || f.thread_number || f.category || f.contact || "",
        summary:   f.summary || f.details || f.significance || f.key_details || "",
        key_messages: Array.isArray(f.key_messages) ? f.key_messages : [],
      })),
    };
  }

  // 5. Normalize key_findings items inside dict form
  if (p.key_findings && Array.isArray(p.key_findings.top_significant_conversations)) {
    p.key_findings.top_significant_conversations = p.key_findings.top_significant_conversations.map(tc => ({
      ...tc,
      thread_id: tc.thread_id || tc.thread_number || tc.contact || "",
      summary:   tc.summary || tc.significance || tc.key_details || "",
    }));
  }

  // 6. Normalize risk_level_summary from alternate fields
  if (!p.risk_level_summary) {
    p.risk_level_summary = p.risk_classification || p.executive_summary || p.overall_assessment || "";
  }

  return p;
}
```

### Step 3: Call `_normalizeAnalysis` in `loadAnalysisResults` and `_renderJsonAnalysis`

In `loadAnalysisResults`, find the line:
```javascript
    const p = r.result_parsed || null;
    const conf = p ? _jsonRiskLevel(p) : _extractConfidence(r.result || "");
```

Replace with:
```javascript
    const p = r.result_parsed ? _normalizeAnalysis(r.result_parsed) : null;
    const conf = p ? _jsonRiskLevel(p) : _extractConfidence(r.result || "");
```

Also find the same pattern in `triggerAnalysis` artifact_done handler:
```javascript
      const conf = _extractConfidence(d.result || "");
```
(No change needed here — stream cards don't get result content from the server callback.)

### Step 4: Fix the generic KV grid to render nested objects as readable text

In `_renderJsonAnalysis`, find the generic KV grid block (last section):
```javascript
      val.textContent = typeof v === "object" ? JSON.stringify(v) : String(v);
```

Replace with:
```javascript
      if (typeof v === "object" && v !== null) {
        val.classList.add("markdown-output");
        val.appendChild(markdownToFragment(
          Array.isArray(v)
            ? v.map(i => `- ${typeof i === "object" ? JSON.stringify(i) : i}`).join("\n")
            : Object.entries(v).map(([k2, v2]) => `**${k2.replace(/_/g," ")}:** ${typeof v2 === "object" ? JSON.stringify(v2) : v2}`).join("\n")
        ));
      } else {
        val.textContent = String(v ?? "");
      }
```

Also expand the `shown` set to suppress fields that are now rendered via normalization:
```javascript
  const shown = new Set([
    "conversation_risk_assessment","contact_risk_assessment",
    "key_findings","risk_level_summary","summary","risk_level",
    "confidence_level","risk_classification","executive_summary",
    "overall_assessment","analysis",
  ]);
```

### Step 5: Verify visually

Open the app, switch to Analysis tab on the case that already has results. You should see:
- Risk summary banner (text, not `{...}`)
- Conversation/Contact risk cards with coloured pills and risk bars
- Key Findings section with thread summaries
- Any remaining extra fields as readable key-value (not raw JSON)

### Step 6: Commit

```bash
git add static/js/chat.js
git commit -m "feat(analysis): normalize LLM JSON schema + readable KV fallback"
```

---

## Task 2 — Update prompt files to enforce JSON schema

**Files:**
- Modify: `prompts/sms_analysis.md`
- Modify: `prompts/whatsapp_analysis.md`
- Modify: `prompts/telegram_analysis.md`
- Modify: `prompts/call_log_analysis.md`
- Modify: `prompts/contacts_analysis.md`
- Modify: `prompts/signal_analysis.md`

### Step 1: Replace the "Output Must Include" section in `prompts/sms_analysis.md`

Find:
```markdown
## Output Must Include
- Contact Risk Assessment table
- Total message count, date range, unique contacts
- CRITICAL/HIGH/MEDIUM/LOW confidence label
```

Replace with:
```markdown
## Output Format

Return ONLY valid JSON — no markdown fences, no explanation text outside the JSON.

```json
{
  "risk_level_summary": "One-sentence overall risk assessment",
  "confidence_level": "CRITICAL|HIGH|MEDIUM|LOW",
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
      "key_messages": [
        { "timestamp": "2021-12-11T16:11:00Z", "direction": "outgoing", "body": "message text" }
      ]
    }
  ]
}
```
```

### Step 2: Replace "Output Must Include" in `prompts/whatsapp_analysis.md`

Find:
```markdown
## Output Must Include
- Conversation Risk Assessment table
- Total message count, date range, unique contacts
- CRITICAL/HIGH/MEDIUM/LOW confidence label at the end
```

Replace with:
```markdown
## Output Format

Return ONLY valid JSON — no markdown fences, no explanation text outside the JSON.

```json
{
  "risk_level_summary": "One-sentence overall risk assessment",
  "confidence_level": "CRITICAL|HIGH|MEDIUM|LOW",
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
      "key_messages": [
        { "timestamp": "2021-12-01T01:44:07Z", "direction": "outgoing", "body": "message text" }
      ]
    }
  ]
}
```
```

### Step 3: Replace "Output Must Include" in `prompts/telegram_analysis.md`

Find:
```markdown
## Output Must Include
- Conversation Risk Assessment table
- Encryption status statement
- Total message count, unique contacts, date range
- CRITICAL/HIGH/MEDIUM/LOW confidence label
```

Replace with:
```markdown
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
```

### Step 4: Replace "Output Must Include" in `prompts/call_log_analysis.md`

Find:
```markdown
## Output Must Include
- Contact Risk Assessment table
- Total call count, date range, top contacts by duration and frequency
- CRITICAL/HIGH/MEDIUM/LOW confidence label
```

Replace with:
```markdown
## Output Format

Return ONLY valid JSON — no markdown fences, no explanation text outside the JSON.

```json
{
  "risk_level_summary": "One-sentence overall risk assessment",
  "confidence_level": "CRITICAL|HIGH|MEDIUM|LOW",
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
      "key_messages": []
    }
  ]
}
```
```

### Step 5: Replace "Output Must Include" in `prompts/contacts_analysis.md`

Find:
```markdown
## Output Must Include
- Total contacts count
- Persons of interest match results (even if none found — state "No matches found")
- Suspicious contacts list
- LOW/MEDIUM/HIGH/CRITICAL confidence label based on findings
```

Replace with:
```markdown
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
```

### Step 6: Replace "Output Must Include" in `prompts/signal_analysis.md`

Find:
```markdown
## Output Must Include
- Encryption status prominently stated
- If encrypted: explicit recommendation for legal process
- CRITICAL/HIGH/MEDIUM/LOW confidence label
```

Replace with:
```markdown
## Output Format

Return ONLY valid JSON — no markdown fences, no explanation text outside the JSON.

```json
{
  "risk_level_summary": "Signal installed. Database encrypted — content inaccessible.",
  "confidence_level": "HIGH",
  "encryption_status": "SQLCipher-encrypted | Decrypted successfully",
  "legal_recommendation": "Obtain decryption key via GrayKey/Cellebrite Physical/passcode seizure",
  "conversation_risk_assessment": [],
  "key_findings": []
}
```
```

### Step 7: Verify prompt files saved

Run a test analysis on a case with at least one messaging artifact. Check the raw result stored in the DB — it should start with `{` and contain `conversation_risk_assessment` at the top level.

```bash
docker exec mobiletrace //bin/sh -c "python3 -c \"
import sqlite3
db = sqlite3.connect('/opt/mobiletrace/data/mobiletrace.db')
rows = db.execute('SELECT artifact_key, substr(result,1,200) FROM analysis_results ORDER BY created_at DESC LIMIT 5').fetchall()
[print(k, ':', v, '\n---') for k, v in rows]
\""
```

### Step 8: Commit

```bash
git add prompts/
git commit -m "feat(prompts): enforce strict JSON schema output in all analysis prompts"
```

---

## Task 3 — Run tests and verify end-to-end

### Step 1: Run test suite (backend unchanged so all should pass)

```bash
docker run --rm \
  -v "$(pwd -W):/opt/mobiletrace" \
  -e MOBILETRACE_DB_PATH=/tmp/test.db \
  mobiletrace-mobiletrace:latest \
  python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: 144 passed.

### Step 2: Browser smoke test

- Switch to Analysis tab → results show with risk cards and readable text (no `{...}` walls)
- Exec summary in Phase 2 view shows readable bullet points
- Details `<details>` elements show structured risk cards, findings blocks
- Re-run analysis → new results follow strict schema → structured rendering

---

## Files Changed Summary

| File | Task |
|---|---|
| `static/js/chat.js` | Task 1 — `_normalizeAnalysis()` + KV grid fix |
| `prompts/sms_analysis.md` | Task 2 — JSON schema enforcement |
| `prompts/whatsapp_analysis.md` | Task 2 — JSON schema enforcement |
| `prompts/telegram_analysis.md` | Task 2 — JSON schema enforcement |
| `prompts/call_log_analysis.md` | Task 2 — JSON schema enforcement |
| `prompts/contacts_analysis.md` | Task 2 — JSON schema enforcement |
| `prompts/signal_analysis.md` | Task 2 — JSON schema enforcement |
