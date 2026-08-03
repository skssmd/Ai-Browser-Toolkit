"""Canonical DOM snapshots and cheap diffs for SPA state tracking.

A snapshot is a line-per-element dump of the visible-ish document tree: tag,
id, classes, attributes, and the element's own text. Two snapshots diff with
difflib into added/removed lines, which reads far smaller than raw HTML for an
LLM deciding what a click just changed. The dump is capped so a pathological
page never stalls a command, and the diff output is capped at a token budget.

Attributes are sorted so attribute reordering never reads as a change. Script,
style, and template elements are skipped, as are volatile style/event/on
attributes that change on hover but mean nothing.
"""

from __future__ import annotations

import difflib

# Lines captured per snapshot. Enough to see any real mutation on an SPA; short
# enough that two snapshots still diff fast.
MAX_SNAPSHOT_LINES = 8000

# The snapshot runs in the browser so the dump costs one round trip, no matter
# how deep the tree is.
_SNAPSHOT_JS = r"""
const MAX = arguments[0] || 8000;
const lines = [];
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
let node = walker.currentNode;
while (node) {
  const el = node;
  const tag = el.tagName;
  if (tag && tag !== 'SCRIPT' && tag !== 'STYLE' && tag !== 'TEMPLATE' && tag !== 'NOSCRIPT') {
    let line = tag.toLowerCase();
    if (el.id) line += '#' + el.id;
    const cls = typeof el.className === 'string' ? el.className : '';
    if (cls) line += '.' + cls.trim().split(/\s+/).filter(Boolean).join('.');
    const attrs = [];
    for (let i = 0; i < el.attributes.length; i++) {
      const a = el.attributes[i];
      const name = a.name;
      if (name === 'id' || name === 'class' || name === 'style') continue;
      if (name.startsWith('on')) continue;
      attrs.push(name + '=' + JSON.stringify(String(a.value).slice(0, 120)));
    }
    if (attrs.length) line += ' [' + attrs.sort().join(' ') + ']';
    let own = '';
    for (const child of el.childNodes) {
      if (child.nodeType === 3) own += child.textContent;
    }
    own = own.trim();
    if (own) line += ' "' + own.slice(0, 160) + '"';
    lines.push(line);
    if (lines.length >= MAX) break;
  }
  node = walker.nextNode();
}
return lines;
"""


def snapshot(driver, max_lines: int = MAX_SNAPSHOT_LINES) -> list[str]:
    """Return the current page as a list of canonical element lines."""
    try:
        lines = driver.execute_script(_SNAPSHOT_JS, max_lines)
    except Exception:
        return []
    return [str(line) for line in lines] if lines else []


def _render_diff(before: list[str], after: list[str], max_chars: int) -> tuple[str, bool]:
    """Build the unified diff, cutting the tail once the budget runs out."""
    parts = []
    size = 0
    truncated = False
    for line in difflib.unified_diff(before, after, lineterm="", n=0):
        size += len(line) + 1
        if size > max_chars:
            truncated = True
            parts.append("… (diff exceeds budget; run {\"op\": \"diff\"} or fetch the page separately)")
            break
        parts.append(line)
    return "\n".join(parts), truncated


def diff_html(
    before: list[str],
    after: list[str],
    max_tokens: int = 1000,
) -> dict:
    """Diff two snapshots. Returns counts plus the diff, capped at max_tokens."""
    max_chars = max(256, max_tokens * 4)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=True)
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    text, truncated = _render_diff(before, after, max_chars)
    return {"added": added, "removed": removed, "diff": text, "truncated": truncated}


def page_key(url: str) -> tuple[str, str, str]:
    """The part of a URL that identifies the document, not just the fragment."""
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    return (parsed.scheme, parsed.netloc, parsed.path)
