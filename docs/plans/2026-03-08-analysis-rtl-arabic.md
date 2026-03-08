# Analysis RTL Arabic Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply `dir="rtl"` to individual text elements in the analysis tab renderer when their content is predominantly Arabic/Hebrew script.

**Architecture:** Add a single `_isRtl(text)` helper to `static/js/chat.js` that checks Unicode Arabic/Hebrew ranges (mirroring `app/rtl_support.py`). Call it before setting `.textContent` or `.innerHTML` on five element types inside `_renderJsonAnalysis`. No backend changes, no new dependencies.

**Tech Stack:** Vanilla JS, no build step.

---

## Task 1 — Add `_isRtl()` and apply to all text elements in `_renderJsonAnalysis`

**Files:**
- Modify: `static/js/chat.js`

### Step 1: Find insertion point

Locate the `_extractConfidence` function (immediately after `_renderJsonAnalysis`):
```javascript
function _extractConfidence(text) {
```
Insert `_isRtl` just before it.

### Step 2: Insert `_isRtl` helper

```javascript
function _isRtl(text) {
  if (!text) return false;
  let alpha = 0, rtl = 0;
  for (const ch of String(text)) {
    if (/\p{L}/u.test(ch)) {
      alpha++;
      const cp = ch.codePointAt(0);
      if (
        (cp >= 0x0590 && cp <= 0x05FF) || // Hebrew
        (cp >= 0x0600 && cp <= 0x06FF) || // Arabic
        (cp >= 0x0750 && cp <= 0x077F) || // Arabic Supplement
        (cp >= 0x08A0 && cp <= 0x08FF) || // Arabic Extended-A
        (cp >= 0xFB50 && cp <= 0xFDFF) || // Arabic Presentation Forms-A
        (cp >= 0xFE70 && cp <= 0xFEFF)    // Arabic Presentation Forms-B
      ) rtl++;
    }
  }
  return alpha > 0 && (rtl / alpha) >= 0.3;
}
```

### Step 3: Apply `dir` to the risk banner `<p>`

Find:
```javascript
    banner.innerHTML = `<p>${esc(rsum)}</p>`;
```

Replace with:
```javascript
    banner.innerHTML = `<p${_isRtl(rsum) ? ' dir="rtl"' : ""}>${esc(rsum)}</p>`;
```

### Step 4: Apply `dir` to key indicator `<li>` items

Find:
```javascript
      ${(t.key_indicators||[]).length ? `<ul class="atc-indicators">${(t.key_indicators||[]).map(i=>`<li>${esc(i)}</li>`).join("")}</ul>` : ""}
```

Replace with:
```javascript
      ${(t.key_indicators||[]).length ? `<ul class="atc-indicators">${(t.key_indicators||[]).map(i=>`<li${_isRtl(i) ? ' dir="rtl"' : ""}>${esc(i)}</li>`).join("")}</ul>` : ""}
```

### Step 5: Apply `dir` to key finding summary

Find:
```javascript
      let inner = `<div class="afb-thread">${esc(tc.thread_id||"")}</div>
                   <div class="afb-summary">${esc(tc.summary||"")}</div>`;
```

Replace with:
```javascript
      const _sum = tc.summary || "";
      let inner = `<div class="afb-thread">${esc(tc.thread_id||"")}</div>
                   <div class="afb-summary"${_isRtl(_sum) ? ' dir="rtl"' : ""}>${esc(_sum)}</div>`;
```

### Step 6: Apply `dir` to key message body

Find:
```javascript
        inner += `<div class="afb-msg"><div class="afb-msg-meta">${esc(km.timestamp||"")} · ${esc(km.direction||"")}</div><div>${esc(km.body||"")}</div></div>`;
```

Replace with:
```javascript
        const _body = km.body || "";
        inner += `<div class="afb-msg"><div class="afb-msg-meta">${esc(km.timestamp||"")} · ${esc(km.direction||"")}</div><div${_isRtl(_body) ? ' dir="rtl"' : ""}>${esc(_body)}</div></div>`;
```

### Step 7: Apply `dir` to KV grid string values

Find:
```javascript
      } else {
        val.textContent = String(v ?? "");
      }
```

Replace with:
```javascript
      } else {
        const _sv = String(v ?? "");
        if (_isRtl(_sv)) val.dir = "rtl";
        val.textContent = _sv;
      }
```

### Step 8: Verify visually

Open the app and navigate to the Analysis tab on a case with Arabic content. Check:
- Arabic `risk_level_summary` text renders right-aligned with RTL flow
- Arabic key indicators inside thread cards are right-aligned
- Arabic message bodies in Key Findings render RTL
- English content is unaffected (LTR as before)

### Step 9: Commit

```bash
git add static/js/chat.js
git commit -m "feat(analysis): RTL direction for Arabic text in analysis results"
```
