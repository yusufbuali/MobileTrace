/**
 * markdown.js — Self-contained markdown renderer for MobileTrace.
 * Ported from AIFT analysis.js. No external dependencies.
 *
 * Exports:
 *   markdownToFragment(text)        — full block renderer → DocumentFragment
 *   renderInlineMarkdown(text)      — inline: bold, italic, code, severity badges
 *   highlightConfidenceTokens(text) — CRITICAL/HIGH/MEDIUM/LOW → colored spans
 */

const CONFIDENCE_TOKEN_PATTERN = /\b(CRITICAL|HIGH|MEDIUM|LOW)\b/gi;
const CONFIDENCE_CLASS_MAP = {
  CRITICAL: 'confidence-critical',
  HIGH: 'confidence-high',
  MEDIUM: 'confidence-medium',
  LOW: 'confidence-low',
};

function _escapeHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function highlightConfidenceTokens(text) {
  CONFIDENCE_TOKEN_PATTERN.lastIndex = 0;
  return String(text || '').replace(CONFIDENCE_TOKEN_PATTERN, (match, token) => {
    const normalized = String(token || match || '').toUpperCase();
    const cssClass = CONFIDENCE_CLASS_MAP[normalized] || 'confidence-unknown';
    return `<span class="confidence-inline ${cssClass}">${normalized}</span>`;
  });
}

export function renderInlineMarkdown(text) {
  const source = String(text || '');
  if (!source) return '';
  const parts = source.split(/(`[^`\n]*`)/g);
  return parts
    .map((part) => {
      if (part.startsWith('`') && part.endsWith('`') && part.length > 1) {
        return `<code>${_escapeHtml(part.slice(1, -1))}</code>`;
      }
      let out = _escapeHtml(part);
      out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      out = out.replace(/__(.+?)__/g, '<strong>$1</strong>');
      out = out.replace(/\*(.+?)\*/g, '<em>$1</em>');
      out = out.replace(/_(.+?)_/g, '<em>$1</em>');
      out = highlightConfidenceTokens(out);
      return out;
    })
    .join('');
}

function _splitTableRow(line) {
  const raw = String(line || '');
  if (!raw.includes('|')) return null;
  let trimmed = raw.trim();
  if (!trimmed || !trimmed.includes('|')) return null;
  if (trimmed.startsWith('|')) trimmed = trimmed.slice(1);
  if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1);
  return trimmed.split('|').map((c) => c.trim());
}

function _isTableSeparatorRow(cells) {
  if (!Array.isArray(cells) || !cells.length) return false;
  return cells.every((c) => /^:?-{3,}:?$/.test(String(c || '').trim()));
}

function _normalizeTableCells(cells, count) {
  const out = Array.isArray(cells)
    ? cells.slice(0, count).map((c) => String(c || '').trim())
    : [];
  while (out.length < count) out.push('');
  return out;
}

export function markdownToFragment(text) {
  const fragment = document.createDocumentFragment();
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  let paragraphLines = [];
  let listNode = null;
  let listType = '';
  let inCodeFence = false;
  let codeFenceLines = [];

  const closeList = () => {
    if (!listNode) return;
    fragment.appendChild(listNode);
    listNode = null;
    listType = '';
  };

  const flushParagraph = () => {
    if (!paragraphLines.length) return;
    const p = document.createElement('p');
    p.innerHTML = renderInlineMarkdown(paragraphLines.join('\n')).replace(/\n/g, '<br>');
    fragment.appendChild(p);
    paragraphLines = [];
  };

  const flushCodeFence = () => {
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.textContent = codeFenceLines.join('\n');
    pre.appendChild(code);
    fragment.appendChild(pre);
    codeFenceLines = [];
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = String(line || '').trim();

    if (inCodeFence) {
      if (trimmed.startsWith('```')) { inCodeFence = false; flushCodeFence(); continue; }
      codeFenceLines.push(line);
      continue;
    }

    if (trimmed.startsWith('```')) {
      flushParagraph(); closeList();
      inCodeFence = true; codeFenceLines = [];
      continue;
    }

    if (!trimmed) { flushParagraph(); closeList(); continue; }

    // Table detection
    const headerCells = _splitTableRow(line);
    if (headerCells && i + 1 < lines.length) {
      const sepCells = _splitTableRow(lines[i + 1]);
      if (sepCells && headerCells.length === sepCells.length && _isTableSeparatorRow(sepCells)) {
        flushParagraph(); closeList();
        const cols = headerCells.length;
        const table = document.createElement('table');
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        _normalizeTableCells(headerCells, cols).forEach((cell) => {
          const th = document.createElement('th');
          th.innerHTML = renderInlineMarkdown(cell);
          headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);
        const tbody = document.createElement('tbody');
        let hasBody = false;
        i += 2;
        while (i < lines.length) {
          const bLine = lines[i];
          const bTrimmed = String(bLine || '').trim();
          if (!bTrimmed) break;
          const bCells = _splitTableRow(bLine);
          if (!bCells) break;
          const tr = document.createElement('tr');
          _normalizeTableCells(bCells, cols).forEach((cell) => {
            const td = document.createElement('td');
            td.innerHTML = renderInlineMarkdown(cell);
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
          hasBody = true;
          i += 1;
        }
        if (hasBody) table.appendChild(tbody);
        fragment.appendChild(table);
        i -= 1;
        continue;
      }
    }

    // Headings
    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph(); closeList();
      const h = document.createElement(`h${heading[1].length}`);
      h.innerHTML = renderInlineMarkdown(heading[2] || '');
      fragment.appendChild(h);
      continue;
    }

    // Ordered list
    const ordered = trimmed.match(/^\d+\.\s+(.*)$/);
    if (ordered) {
      flushParagraph();
      if (listType !== 'ol') { closeList(); listNode = document.createElement('ol'); listType = 'ol'; }
      const li = document.createElement('li');
      li.innerHTML = renderInlineMarkdown(ordered[1] || '');
      listNode.appendChild(li);
      continue;
    }

    // Unordered list
    const unordered = trimmed.match(/^[-*]\s+(.*)$/);
    if (unordered) {
      flushParagraph();
      if (listType !== 'ul') { closeList(); listNode = document.createElement('ul'); listType = 'ul'; }
      const li = document.createElement('li');
      li.innerHTML = renderInlineMarkdown(unordered[1] || '');
      listNode.appendChild(li);
      continue;
    }

    closeList();
    paragraphLines.push(trimmed);
  }

  if (inCodeFence) flushCodeFence();
  flushParagraph();
  closeList();
  return fragment;
}
