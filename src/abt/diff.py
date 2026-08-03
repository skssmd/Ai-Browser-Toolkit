"""Canonical DOM snapshots and cheap diffs for SPA state tracking.

A snapshot has two tracks, both produced by one walk of the document:

* **text** -- one entry per element that carries its own visible text, plus the
  live value of every form control. This is what changed *on screen*. It is
  small, it is what an agent actually reads, and it is immune to the styling
  and state-attribute churn that makes raw DOM diffs unreadable. Each element
  contributes its own text only, never its children's, so two adjacent labels
  stay two entries and never merge into one blob.
* **dom** -- a line per element: tag, id, classes, attributes, own text. Full
  fidelity, much larger, and opt-in on a per-command basis.

Two snapshots diff with difflib. The text track reports what appeared, counts
what left, and lists what left only on request -- a page that replaces its body
would otherwise return the whole old document as removals. The element track
diffs into a unified diff capped at a token budget.

When the page navigates there is nothing to diff against, so the text track
reports the whole new page instead of going silent. Landing somewhere and
learning what is on it is the same question either way.

Attributes are sorted so attribute reordering never reads as a change. Script,
style, and template elements are skipped, as are volatile style/event/on
attributes that change on hover but mean nothing. Password field values are
never captured -- diffs get written to session logs.
"""

from __future__ import annotations

import difflib

# Element lines captured per snapshot. Enough to see any real mutation on an
# SPA; short enough that two snapshots still diff fast.
MAX_SNAPSHOT_LINES = 8000

# Text entries captured per snapshot. A page with more visible strings than
# this is a data dump, not an interface.
MAX_TEXT_LINES = 4000

# Safety ceiling on a rendered text diff. Not a budget knob -- the text diff is
# small by construction, and this only exists so a page that swaps its entire
# body cannot return a response measured in megabytes.
MAX_TEXT_DIFF_CHARS = 40_000

# The snapshot runs in the browser so the dump costs one round trip, no matter
# how deep the tree is. Both tracks come from the same walk.
_SNAPSHOT_JS = r"""
const MAX = arguments[0] || 8000;
const MAX_TEXT = arguments[1] || 4000;
const dom = [];
const text = [];
if (!document.body) { return {dom: dom, text: text}; }
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
let node = walker.currentNode;
while (node) {
  const el = node;
  const tag = el.tagName;
  if (tag && tag !== 'SCRIPT' && tag !== 'STYLE' && tag !== 'TEMPLATE' && tag !== 'NOSCRIPT') {
    let own = '';
    for (const child of el.childNodes) {
      if (child.nodeType === 3) own += child.textContent;
    }
    own = own.trim();

    if (dom.length < MAX) {
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
      if (own) line += ' "' + own.slice(0, 160) + '"';
      dom.push(line);
    }

    // Only what is on screen counts as text: a menu that exists but is hidden
    // has not appeared yet, and saying otherwise is the whole reason raw DOM
    // diffs mislead.
    if (text.length < MAX_TEXT && el.getClientRects().length > 0) {
      let value = null;
      if (tag === 'INPUT') {
        const type = (el.type || '').toLowerCase();
        // Never capture a password, and a hidden input is not on screen.
        if (type !== 'password' && type !== 'hidden') value = el.value;
      } else if (tag === 'TEXTAREA') {
        value = el.value;
      } else if (tag === 'SELECT') {
        const chosen = el.selectedOptions[0];
        value = chosen ? chosen.textContent : '';
      }
      // Everything else, contenteditable included, reports its own text. A rich
      // editor's content lives in descendants that the walk reaches anyway.
      if (value === null) value = own;
      value = String(value).replace(/\s+/g, ' ').trim();
      if (value) text.push(value.slice(0, 400));
    }
  }
  if (dom.length >= MAX && text.length >= MAX_TEXT) break;
  node = walker.nextNode();
}
return {dom: dom, text: text};
"""

def snapshot(
    driver,
    max_lines: int = MAX_SNAPSHOT_LINES,
    max_text: int = MAX_TEXT_LINES,
) -> dict:
    """Return the page as {"dom": [element lines], "text": [visible strings]}."""
    try:
        raw = driver.execute_script(_SNAPSHOT_JS, max_lines, max_text)
    except Exception:
        return {"dom": [], "text": []}
    if not isinstance(raw, dict):
        return {"dom": [], "text": []}
    return {
        "dom": [str(line) for line in raw.get("dom") or []],
        "text": [str(line) for line in raw.get("text") or []],
    }


# --- text track ---------------------------------------------------------------


def diff_text(
    before: list[str],
    after: list[str],
    include_removed: bool = False,
    max_chars: int = MAX_TEXT_DIFF_CHARS,
) -> dict:
    """What text appeared, and -- on request -- what disappeared.

    Additions are what you act on: the new options, the result, the error. What
    left the screen is usually the page you were already looking at, and on a
    page that swaps its whole body the removals are the entire old document for
    no benefit. So removals are counted always and listed only when asked.

    autojunk is off: it would classify a string repeated across a long list --
    every "Add to cart" on a results page -- as noise and drop real changes.
    """
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    added: list[str] = []
    removed: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed.extend(before[i1:i2])
        if tag in ("replace", "insert"):
            added.extend(after[j1:j2])

    removed_count = len(removed)
    if not include_removed:
        removed = []

    added, removed, truncated = _cap(added, removed, max_chars)
    out = {"added": added, "removed_count": removed_count, "truncated": truncated}
    if include_removed:
        out["removed"] = removed
    return out


def page_text(
    text: list[str],
    before: list[str] | None = None,
    include_removed: bool = False,
    max_chars: int = MAX_TEXT_DIFF_CHARS,
) -> dict:
    """Every visible string on the page, reported as `added`.

    After a navigation there is nothing to diff against -- the old document is
    gone -- so the whole new page is what appeared. Returning it here saves the
    agent a separate read: land on a page and its content is already in hand,
    in the same shape a diff would have used.

    `before` is the outgoing page's text. It is never diffed against -- the two
    documents are unrelated -- but it is counted, so `removed_count` still tells
    you how much text you left behind, and the strings themselves are there on
    request.
    """
    removed = list(before) if before is not None else []
    added, removed_kept, truncated = _cap(
        list(text), removed if include_removed else [], max_chars
    )
    out = {"added": added, "truncated": truncated}
    if before is not None:
        out["removed_count"] = len(before)
        if include_removed:
            out["removed"] = removed_kept
    return out


def _cap(
    added: list[str], removed: list[str], max_chars: int
) -> tuple[list[str], list[str], bool]:
    """Trim both lists to a shared character ceiling, saying what was dropped."""
    if sum(len(s) for s in added) + sum(len(s) for s in removed) <= max_chars:
        return added, removed, False

    budget = max_chars
    out: dict[str, list[str]] = {"added": [], "removed": []}
    for name, source in (("added", added), ("removed", removed)):
        kept = out[name]
        for entry in source:
            if budget - len(entry) < 0:
                break
            budget -= len(entry)
            kept.append(entry)
        dropped = len(source) - len(kept)
        if dropped:
            kept.append(f"… ({dropped} more, text diff hit its safety ceiling)")
    return out["added"], out["removed"], True


# --- element track ------------------------------------------------------------


def _render_diff(before: list[str], after: list[str], max_chars: int) -> tuple[str, bool]:
    """Build the unified diff, cutting the tail once the budget runs out."""
    parts = []
    size = 0
    truncated = False
    for line in difflib.unified_diff(before, after, lineterm="", n=0):
        size += len(line) + 1
        if size > max_chars:
            truncated = True
            parts.append("… (diff exceeds budget; raise diff_max_tokens to see the rest)")
            break
        parts.append(line)
    return "\n".join(parts), truncated


def diff_html(
    before: list[str],
    after: list[str],
    max_tokens: int = 1000,
) -> dict:
    """Diff two element snapshots. Counts plus the diff, capped at max_tokens."""
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
