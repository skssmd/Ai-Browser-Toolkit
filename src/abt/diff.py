"""Canonical DOM snapshots and cheap diffs for SPA state tracking.

A snapshot has three tracks, all produced by one walk of the document:

* **text** -- one entry per element that carries its own visible text, plus the
  live value of every form control. This is what changed *on screen*. It is
  small, it is what an agent actually reads, and it is immune to the styling
  and state-attribute churn that makes raw DOM diffs unreadable. Each element
  contributes its own text only, never its children's, so two adjacent labels
  stay two entries and never merge into one blob.
* **dom** -- a line per element: tag, id, classes, attributes, own text. Full
  fidelity, much larger, and opt-in on a per-command basis.
* **actionable** -- the interactive elements only: role, accessible name, and a
  stable key. Text says *what* appeared; this says *which of it can be clicked*
  and hands back a ref to click it with, so acting on what just changed costs
  no extra `find`. It rides along in the same walk, and because it keeps only
  elements a person could operate it stays a small fraction of the page.

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

# Interactive elements collected per snapshot. Only the "after" snapshot ships
# the elements themselves back over the wire, so this bounds one payload per op.
MAX_ACTIONABLE_SCANNED = 300

# Interactive elements reported per diff. Every one reported costs a ref that
# lives until the tab navigates, so this caps both the response and the cache.
MAX_ACTIONABLE_REPORTED = 50

# The snapshot runs in the browser so the dump costs one round trip, no matter
# how deep the tree is. All three tracks come from the same walk.
_SNAPSHOT_JS = r"""
const MAX = arguments[0] || 8000;
const MAX_TEXT = arguments[1] || 4000;
const MAX_ACT = arguments[2] || 300;
// Not `|| 4`: 0 is a legitimate "walk everything" and would be swallowed.
const MIN_FRAME = arguments[3] == null ? 4 : arguments[3];
const dom = [];
const text = [];
const actionable = [];
const els = [];
const frames = [];
if (!document.body) { return {dom: dom, text: text, actionable: actionable, frames: frames}; }

// Which frames this document embeds, answered here because the snapshot is
// already a round trip and a second one to ask "are there any?" would be the
// whole cost of frame support on the pages that have none.
//
// Reported as positions among the child browsing contexts, which is what the
// driver switches by -- one call instead of fetching the elements and sending
// one back. Reference identity is the only thing about a cross-origin window
// that still works, and it is exactly what is needed here.
const framesOf = () => {
  const nodes = document.querySelectorAll('iframe, frame');
  for (let i = 0; i < nodes.length; i++) {
    const f = nodes[i];
    // Nothing can be read or clicked in a frame with no box. The 0x0 preload
    // that sign-in widgets mount beside their real button is the usual one.
    if (f.getClientRects().length === 0) continue;
    if (f.offsetWidth < MIN_FRAME || f.offsetHeight < MIN_FRAME) continue;
    for (let k = 0; k < window.length; k++) {
      if (window[k] === f.contentWindow) { frames.push(k); break; }
    }
  }
};
try { framesOf(); } catch (e) {}

// Roles a person can operate. An element whose role is not here is content,
// not a control, and reporting it would drown the ones that matter.
const INTERACTIVE = {button: 1, link: 1, checkbox: 1, radio: 1, textbox: 1,
  combobox: 1, listbox: 1, menuitem: 1, menuitemcheckbox: 1, menuitemradio: 1,
  option: 1, searchbox: 1, slider: 1, spinbutton: 1, switch: 1, tab: 1,
  treeitem: 1, file: 1};

const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();

const implicitRole = (el, tag) => {
  if (tag === 'A' || tag === 'AREA') return el.hasAttribute('href') ? 'link' : '';
  if (tag === 'BUTTON' || tag === 'SUMMARY') return 'button';
  if (tag === 'SELECT') return el.multiple ? 'listbox' : 'combobox';
  if (tag === 'TEXTAREA') return 'textbox';
  if (tag === 'OPTION') return 'option';
  if (tag === 'INPUT') {
    const t = (el.type || 'text').toLowerCase();
    if (t === 'hidden') return '';
    if (t === 'file') return 'file';
    if (t === 'checkbox') return 'checkbox';
    if (t === 'radio') return 'radio';
    if (t === 'search') return 'searchbox';
    if (t === 'range') return 'slider';
    if (t === 'number') return 'spinbutton';
    if (t === 'button' || t === 'submit' || t === 'reset' || t === 'image') return 'button';
    return 'textbox';
  }
  return '';
};

// Approximates the accessible name -- not the full accname spec, but the
// sources that carry a real label in practice. textContent throughout, never
// innerText: innerText forces a reflow on every candidate, and we have already
// established the element is rendered.
const accName = (el, tag, own) => {
  let n = clean(el.getAttribute('aria-label'));
  if (n) return n;
  const by = el.getAttribute('aria-labelledby');
  if (by) {
    let parts = '';
    by.split(/\s+/).forEach((id) => {
      const t = document.getElementById(id);
      if (t) parts += ' ' + t.textContent;
    });
    n = clean(parts);
    if (n) return n;
  }
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
    const type = (el.type || '').toLowerCase();
    if (tag === 'INPUT' && (type === 'button' || type === 'submit' || type === 'reset')) {
      n = clean(el.value);
      if (n) return n;
    }
    // .labels covers both <label for> and a wrapping <label>, natively -- the
    // hand-rolled version cost a document query per field.
    const labels = el.labels;
    if (labels && labels.length) {
      n = clean(labels[0].textContent);
      if (n) return n;
    }
    n = clean(el.getAttribute('placeholder'));
    if (n) return n;
  } else {
    // `own` is this element's own text, already computed for the dom track.
    // textContent walks every descendant, so it is the fallback, not the first
    // thing tried.
    if (own) return clean(own);
    n = clean(el.textContent);
    if (n) return n;
  }
  n = clean(el.getAttribute('title'));
  if (n) return n;
  return clean(el.getAttribute('alt'));
};

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
    // diffs mislead. Computed once -- getClientRects is the expensive call in
    // this loop and both the text and actionable tracks gate on it.
    const rendered = el.getClientRects().length > 0;

    if (text.length < MAX_TEXT && rendered) {
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

    // The actionable track: what of this can actually be operated. An explicit
    // role wins over the implicit one, exactly as ARIA resolves it.
    //
    // File inputs are the one deliberate exception to "must be rendered". The
    // standard upload pattern hides the real input and fronts it with a custom
    // control that validates or resizes, so the element you must send the path
    // to is never the element on screen -- and if the track skipped it, there
    // would be no way to reach it at all.
    const isFile = tag === 'INPUT' && (el.type || '').toLowerCase() === 'file';
    if (actionable.length < MAX_ACT && (rendered || isFile)) {
      // Everything on this path runs once per element in the document, so it is
      // ordered cheapest-first and nothing is computed before it is needed: the
      // attribute read and the tag switch settle the overwhelming majority of
      // elements, and only the ones with no role at all pay for the rest.
      const roleAttr = el.getAttribute('role');
      let role = roleAttr ? roleAttr.trim().toLowerCase() : '';
      if (!role) role = implicitRole(el, tag);

      let interactive = false;
      let editable = false;
      if (role) {
        interactive = INTERACTIVE[role] === 1;
      } else {
        editable = el.getAttribute('contenteditable') !== null && el.isContentEditable;
        // tabindex catches the custom controls that carry no role at all -- the
        // div a framework wired a click handler onto and made focusable.
        interactive = editable || (el.hasAttribute('tabindex') && el.tabIndex >= 0);
      }

      if (interactive) {
        if (!role) role = editable ? 'textbox' : 'focusable';
        let name = accName(el, tag, own).slice(0, 120);
        // A hidden upload usually carries no label of its own -- the text the
        // user sees belongs to the custom control in front of it. Fall back to
        // whatever identifies it, so it still arrives with something to read.
        if (!name && isFile) {
          name = clean(el.getAttribute('name')) || clean(el.id) || 'file upload';
        }
        // Text is the anchor. A control with no name gives the agent nothing to
        // tie a ref back to, so it is noise -- an unlabelled icon, a focusable
        // wrapper div. Dropping it keeps this track a decoration on what the
        // text track already reported, never a second inventory of the page.
        if (name) {
          const entry = {
            // The key is what two snapshots align on. Role and name identify
            // the control the way a person would; the tag keeps a link and a
            // button with the same label from reading as the same thing.
            key: role + '\u001f' + name + '\u001f' + tag.toLowerCase(),
            role: role,
            name: name,
          };
          if (el.disabled === true || el.getAttribute('aria-disabled') === 'true') {
            entry.disabled = true;
          }
          // Whether one path or several can be sent is the only other thing
          // worth knowing about an upload before you use it.
          if (isFile && el.multiple) { entry.multiple = true; }
          actionable.push(entry);
          els.push(el);
        }
      }
    }
  }
  if (dom.length >= MAX && text.length >= MAX_TEXT && actionable.length >= MAX_ACT) break;
  node = walker.nextNode();
}
// Park the collected elements on the page instead of serialising all of them
// back. Only the handful the diff turns out to care about are ever fetched, and
// the array is replaced by the next snapshot, so nothing is pinned for long.
window.__abtActionable = els;
return {dom: dom, text: text, actionable: actionable, frames: frames};
"""


# Pulls back only the positions the diff picked -- no re-walk, so the predicate
# that decides what counts as a control exists in exactly one place.
_ACTIONABLE_ELEMENTS_JS = """
const stash = window.__abtActionable;
if (!stash) { return []; }
return arguments[0].map((i) => stash[i] || null);
"""

def _blank() -> dict:
    return {"dom": [], "text": [], "actionable": [], "frames": []}


def snapshot(
    driver,
    max_lines: int = MAX_SNAPSHOT_LINES,
    max_text: int = MAX_TEXT_LINES,
    max_actionable: int = MAX_ACTIONABLE_SCANNED,
    min_frame_px: int = 4,
) -> dict:
    """Return the document as its three tracks, plus the frames it embeds.

    Keys only: the live elements behind the actionable entries stay parked in
    the page until `actionable_elements` asks for specific ones. A snapshot is
    taken twice per diffed op, so anything paid for here is paid for twice.

    `frames` is the positions of the child documents worth walking. It rides
    along because this call is already a round trip and asking separately would
    cost every frameless page -- which is nearly all of them -- the price of
    frame support for no benefit.
    """
    try:
        raw = driver.execute_script(
            _SNAPSHOT_JS, max_lines, max_text, max_actionable, min_frame_px
        )
    except Exception:
        return _blank()
    if not isinstance(raw, dict):
        return _blank()

    actionable = []
    for slot, item in enumerate(raw.get("actionable") or []):
        if not isinstance(item, dict):
            continue
        entry = {
            "key": str(item.get("key") or ""),
            "role": str(item.get("role") or ""),
            "name": str(item.get("name") or ""),
            # Where this element sits in the array the walk parked on the page,
            # and which document that array belongs to. Both are internal: they
            # exist so a ref can be fetched later and acted on in the right
            # frame, and neither is ever handed to a caller.
            "slot": slot,
            "frame": (),
        }
        if item.get("disabled"):
            entry["disabled"] = True
        if item.get("multiple"):
            entry["multiple"] = True
        actionable.append(entry)

    return {
        "dom": [str(line) for line in raw.get("dom") or []],
        "text": [str(line) for line in raw.get("text") or []],
        "actionable": actionable,
        "frames": [int(slot) for slot in raw.get("frames") or []],
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


# --- actionable track ----------------------------------------------------------


def diff_actionable(
    before: list[dict],
    after: list[dict],
    limit: int = MAX_ACTIONABLE_REPORTED,
) -> tuple[list[dict], list[int], bool]:
    """Which interactive elements are new since `before`.

    Aligned on the same keys the snapshot built, so duplicates behave: five
    identical "Delete" buttons where there were four reports one addition, not
    five. Returns the new entries, their positions in the walk (which is what
    `actionable_elements` resolves to live handles), and whether the cap bit.
    """
    matcher = difflib.SequenceMatcher(
        a=[entry["key"] for entry in before],
        b=[entry["key"] for entry in after],
        autojunk=False,
    )
    picked: list[int] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            picked.extend(range(j1, j2))

    truncated = len(picked) > limit
    picked = picked[:limit]
    return [after[j] for j in picked], picked, truncated


def merge_frame(state: dict, sub: dict, path: tuple[int, ...]) -> None:
    """Fold a frame's snapshot into the host document's, in reading order.

    Text and dom lines append as they are. A frame's content is content: it is
    what a person sees on the page, and tagging it as foreign would put a
    synthetic string into the one track whose entries are supposed to be
    exactly what is on screen.

    Actionable entries are the exception, because they are aligned on their key
    rather than read. The frame goes into the key so that the same widget in
    two frames -- a page with two card fields, two sign-in buttons -- stays two
    controls instead of collapsing into one.
    """
    state["dom"].extend(sub.get("dom") or [])
    state["text"].extend(sub.get("text") or [])
    tag = ".".join(str(index) for index in path)
    for entry in sub.get("actionable") or []:
        entry["frame"] = path
        entry["key"] = tag + "\u001f" + entry["key"]
        state["actionable"].append(entry)


def actionable_elements(driver, indices: list[int]) -> list:
    """Live handles for the positions a diff picked, in the same order.

    Returns [] on any trouble: refs are a convenience laid on top of a diff that
    has already succeeded, never a reason for the command to fail.
    """
    if not indices:
        return []
    try:
        found = driver.execute_script(_ACTIONABLE_ELEMENTS_JS, list(indices))
    except Exception:
        return []
    if not isinstance(found, list) or any(item is None for item in found):
        return []
    return found


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
