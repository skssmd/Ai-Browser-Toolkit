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

A page's frames are walked the same way and folded into the same three tracks,
because a frame is a separate document that no amount of walking the parent will
reach. Each snapshot also reports the frames its own document embeds, so the
walk pays for itself only where there is something to walk -- see `frames.py`.

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
# Where an element sits, and the text it owns. Shared by the snapshot walk and
# by `find`, so a path means the same thing whichever way you arrived at the
# element -- an address printed by the text track has to be the address `find`
# would give the same node, or the scheme is two schemes.
#
# One character per level, A-Z then a-z: 52 siblings before the alphabet runs
# out. Past that the level is a plain number, and digits are deliberately kept
# out of the alphabet so a run of them can only ever mean one level -- "ABr100C"
# is A, B, r, 100, C, with nothing escaped. Two adjacent numeric levels are the
# only ambiguous case, so a dot separates those and only those: it takes a 53rd
# child that itself has a 53rd child, and costs a character nowhere else.
#
# The index comes from previousElementSibling, not from the order a walk reaches
# nodes: the number has to mean the element's real position, or an address is
# only true for the walk that produced it.
_PATH_JS = r"""
const ALPH = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
const seg = (n) => (n <= 52 ? ALPH.charAt(n - 1) : String(n));
const _path = new Map();
if (document.body) _path.set(document.body, 'A');
const pathOf = (el) => {
  const hit = _path.get(el);
  if (hit !== undefined) return hit;
  const par = el.parentElement;
  if (!par) return '';
  const base = pathOf(par);
  if (!base) return '';
  let i = 1;
  for (let s = el; (s = s.previousElementSibling); ) i++;
  let step = seg(i);
  if (step.charCodeAt(0) < 58 && base.charCodeAt(base.length - 1) < 58) {
    step = '.' + step;
  }
  const p = base + step;
  _path.set(el, p);
  return p;
};
// The text an element owns: its own child text nodes, not its descendants'.
// innerText would drag a container's whole subtree in and force a reflow to do
// it; this is what the element itself says.
const ownText = (el) => {
  let s = '';
  for (const child of el.childNodes) {
    if (child.nodeType === 3) s += child.textContent;
  }
  return s.replace(/\s+/g, ' ').trim();
};
"""

_SNAPSHOT_JS = _PATH_JS + r"""
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
// Hosts are counted, never entered. See shadow.py: the count is what turns an
// empty diff from a silence into "nothing changed where I looked".
let shadowHosts = 0;
if (!document.body) { return {dom: dom, text: text, actionable: actionable, frames: frames, shadowHosts: 0}; }

// Which frames this document embeds, answered here because the snapshot is
// already a round trip and a second one to ask "are there any?" would be the
// whole cost of frame support on the pages that have none.
//
// Reported as document positions -- where the <iframe> sits among its
// siblings. A page has a second, different ordering of the same frames in
// `window.frames`, and on linkedin.com/login the two disagree; see frames.py
// for why everything here stays in this one.
const framesOf = () => {
  const nodes = document.querySelectorAll('iframe, frame');
  for (let i = 0; i < nodes.length; i++) {
    const f = nodes[i];
    // Nothing can be read or clicked in a frame with no box. The 0x0 preload
    // that sign-in widgets mount beside their real button is the usual one.
    if (f.getClientRects().length === 0) continue;
    if (f.offsetWidth < MIN_FRAME || f.offsetHeight < MIN_FRAME) continue;
    frames.push(i);
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

// Positional path per element -- body is "0", then the element's index among
// its parent's element children. Text arrives flat otherwise, and a flat list
// cannot say which strings belong to one table row: an agent reading it has to
// go back with run_js and querySelectorAll to recover the rows it was already
// given. Measured across a benchmark campaign, that was the single largest use
// of run_js, and the counting failures that came with it were all off-by-a-few
// rather than wrong in kind, which is what reading a flat cell stream produces.
//
// The index is counted from previousElementSibling rather than from the order
// this walk happens to visit in: only text-bearing elements ask for a path, so
// a visit-order counter would number them 1,2,3 regardless of where they
// actually sit, and the number would mean nothing. Ancestors are cached, so
// each element pays for its own depth once.
// A root confines the walk to one subtree -- what `get_text` on a selector
// asks for. Paths stay absolute, measured from body, so a string read this way
// carries the same address it would have had in a full page read.
const ROOT = arguments[4] || document.body;
const walker = document.createTreeWalker(ROOT, NodeFilter.SHOW_ELEMENT);
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

    // One property read on a node the walk already has in hand. Not entered:
    // this says how many places were not looked at, never what is in them.
    if (el.shadowRoot) shadowHosts++;

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
      if (value) text.push([pathOf(el), value.slice(0, 400)]);
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
return {dom: dom, text: text, actionable: actionable, frames: frames,
        shadowHosts: shadowHosts};
"""


# Pulls back only the positions the diff picked -- no re-walk, so the predicate
# that decides what counts as a control exists in exactly one place.
_ACTIONABLE_ELEMENTS_JS = """
const stash = window.__abtActionable;
if (!stash) { return []; }
return arguments[0].map((i) => stash[i] || null);
"""

# The nearest text that tells two identically-named controls apart.
#
# Climbs from the control until an ancestor holds text that is not the
# control's own, and returns the first such string -- which on a table row is
# the first cell, and on a card is its heading. It knows nothing about tables
# or cards; it just walks up until something else has something to say.
#
# Only ever asked for repeated names, so the walk runs on a handful of elements
# and never on an ordinary page. See `ops.actionable_report`.
_ACTIONABLE_CONTEXT_JS = r"""
const stash = window.__abtActionable;
if (!stash) { return []; }
const CAP = 80;
// Text inside these is source, not content. The snapshot walk skips them for
// the same reason.
const SKIP = {SCRIPT: 1, STYLE: 1, TEMPLATE: 1, NOSCRIPT: 1};
const tidy = (s) => s.replace(/\s+/g, ' ').trim();

function firstTextBeside(root, inner) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  let node;
  while ((node = walker.nextNode())) {
    // The control's own label is what we are trying to qualify, so it can
    // never be the qualifier.
    if (inner.contains(node)) { continue; }
    const parent = node.parentElement;
    if (!parent || SKIP[parent.tagName]) { continue; }
    const text = tidy(node.textContent);
    if (text) { return text; }
  }
  return '';
}

return arguments[0].map(function (slot) {
  const el = stash[slot];
  if (!el) { return null; }
  const own = tidy(el.innerText || el.textContent || '');
  let node = el.parentElement;
  let depth = 0;
  // Six is past a table row and a card without reaching the page shell, where
  // the first text is a nav item and identical for every control on screen.
  while (node && depth < 6) {
    const found = firstTextBeside(node, el);
    if (found && found.toLowerCase() !== own.toLowerCase()) {
      return found.length > CAP ? found.slice(0, CAP) : found;
    }
    node = node.parentElement;
    depth += 1;
  }
  return null;
});
"""


def actionable_context(driver, slots: list[int]) -> list:
    """The disambiguating text for each parked element, or None where there is
    none to be had. Never raises: a missing qualifier is a smaller loss than a
    failed command."""
    if not slots:
        return []
    try:
        found = driver.execute_script(_ACTIONABLE_CONTEXT_JS, list(slots))
    except Exception:
        return [None] * len(slots)
    if not isinstance(found, list) or len(found) != len(slots):
        return [None] * len(slots)
    return found

def _blank() -> dict:
    return {"dom": [], "text": [], "actionable": [], "frames": [], "shadow_hosts": 0}


def snapshot(
    driver,
    max_lines: int = MAX_SNAPSHOT_LINES,
    max_text: int = MAX_TEXT_LINES,
    max_actionable: int = MAX_ACTIONABLE_SCANNED,
    min_frame_px: int = 4,
    root=None,
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
            _SNAPSHOT_JS, max_lines, max_text, max_actionable, min_frame_px, root
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
        # (path, value) pairs, as tuples: the diff aligns text with
        # SequenceMatcher, which indexes its elements and so needs them
        # hashable. JSON hands lists back, which are not.
        "text": _pairs(raw.get("text")),
        "actionable": actionable,
        "frames": [int(slot) for slot in raw.get("frames") or []],
        "shadow_hosts": int(raw.get("shadowHosts") or 0),
    }


# --- text track ---------------------------------------------------------------


PATH_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# Walks the indices a decoded path names. Kept here beside the encoder so the
# two halves of the scheme cannot drift: whatever `seg()` writes, this reads.
_AT_PATH_JS = """
var idx = arguments[0], el = document.body;
for (var i = 0; i < idx.length; i++) {
  if (!el) return null;
  el = el.children[idx[i] - 1];
}
return el || null;
"""


def decode_path(path: str) -> list[int] | None:
    """The child indices a path names, or None if it is not one.

    The inverse of the `seg()` encoder in the snapshot walk: a letter is one
    level, a run of digits is one level past the 52nd sibling, and a dot only
    ever separates two numeric levels. The leading level is the body itself and
    is dropped, so what comes back is the walk from body down.
    """
    if not path or path[0] not in PATH_ALPHABET:
        return None
    levels: list[int] = []
    index = 0
    while index < len(path):
        char = path[index]
        if char == ".":
            index += 1
            continue
        if char.isdigit():
            stop = index
            while stop < len(path) and path[stop].isdigit():
                stop += 1
            levels.append(int(path[index:stop]))
            index = stop
            continue
        position = PATH_ALPHABET.find(char)
        if position < 0:
            return None
        levels.append(position + 1)
        index += 1
    # The first level is body, which is where the walk starts rather than a
    # step it takes.
    return levels[1:] if levels else None


def element_at(driver, path: str):
    """The element a path names, or None if nothing sits there any more."""
    indices = decode_path(path)
    if indices is None:
        return None
    try:
        return driver.execute_script(_AT_PATH_JS, indices)
    except Exception:
        return None


def _split_tail(path: str) -> tuple[str, str]:
    """Split a path into its parent and its own last level.

    A level is one letter, or -- past the 52nd sibling -- a run of digits. Since
    digits appear in no other role, a run of them is exactly one level, and
    neither form has to be escaped for this to be unambiguous.
    """
    if not path:
        return "", ""
    if path[-1].isdigit():
        cut = len(path)
        while cut and path[cut - 1].isdigit():
            cut -= 1
        own = path[cut:]
        # A dot only ever separates two numeric levels, so it belongs to the
        # parent's side of the split, not to the level it introduces.
        if cut and path[cut - 1] == ".":
            cut -= 1
        return path[:cut], own
    return path[:-1], path[-1]


def _pairs(raw) -> list[tuple[str, str]]:
    """Normalise the walk's text track to (path, value) tuples."""
    out: list[tuple[str, str]] = []
    for item in raw or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.append((str(item[0]), str(item[1])))
        else:
            # A snapshot from an older page script, or a caller passing plain
            # strings. Pathless entries still render, just without grouping.
            out.append(("", str(item)))
    return out


def render_text(pairs: list[tuple[str, str]]) -> list[str]:
    """Lay the text track out as its tree, one line per string.

    Every string carries where it sits, so strings that share a parent are
    visibly one group -- which is what makes a table row readable as a row.
    A flat list cannot express that, and an agent handed one goes back with
    `run_js` and `querySelectorAll` to rebuild what it was already given.

    The path is written once per group rather than once per string. Text on a
    Magento page sits at a median DOM depth of 15, so repeating the full path on
    every string costs more characters than the strings themselves; writing it
    on the group and giving each member its own index is the same information
    for about a fifth of the price. Nothing is lost: a member's full path is its
    group's path plus its own index.

    A group holding a single string keeps that string on the group's own line,
    so the common case never costs two lines to say one thing.
    """
    lines: list[str] = []
    index = 0
    while index < len(pairs):
        path, value = pairs[index]
        parent, own = _split_tail(path)
        if not parent:
            lines.append(f"{path} {value}" if path else value)
            index += 1
            continue

        run = [(own, value)]
        probe = index + 1
        while probe < len(pairs):
            sibling_path, sibling_value = pairs[probe]
            sibling_parent, sibling_own = _split_tail(sibling_path)
            if sibling_parent != parent:
                break
            run.append((sibling_own, sibling_value))
            probe += 1

        if len(run) == 1:
            lines.append(f"{path} {value}")
        else:
            lines.append(parent)
            lines.extend(f"  {own} {value}" for own, value in run)
        index = probe
    return lines


def diff_text(
    before: list[tuple[str, str]],
    after: list[tuple[str, str]],
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
    # Accept either shape. The walk hands over (path, value) pairs, but a caller
    # holding plain strings -- a unit test, an older snapshot -- gets the same
    # answer, rendered without positions rather than crashing on the unpack.
    before, after = _pairs(before), _pairs(after)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    added_pairs: list[tuple[str, str]] = []
    removed_pairs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed_pairs.extend(before[i1:i2])
        if tag in ("replace", "insert"):
            added_pairs.extend(after[j1:j2])

    removed_count = len(removed_pairs)
    added = render_text(added_pairs)
    removed = render_text(removed_pairs) if include_removed else []

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
    """The new page, with what the last one already showed you taken out.

    Landing on a page puts its content straight in hand, which saves a separate
    read. It used to put *all* of it in hand: the old document is gone, so the
    reasoning went, the two documents are unrelated and there is nothing to diff
    against.

    That holds between sites and is false within one. Consecutive pages of the
    same site share their nav, header, footer and grid furniture, and measured
    across a benchmark campaign the repetition was 38% of admin page text, 47%
    of the forum's and 60% of the storefront's -- about half of every character
    delivered, re-sent on each navigation and then carried in the conversation
    for every turn that followed.

    So `before` is now diffed against, on the string rather than on the path:
    paths shift between documents, and matching on them would suppress real
    content whenever a page happened to nest it the same way. What repeats is
    what the agent has already read.

    Suppressed text is summarised, never silently dropped. An agent cannot ask
    for what it does not know is missing, so the count and the way to get it
    back both travel with the result.
    """
    pairs = _pairs(text)
    removed = list(before) if before is not None else []

    kept = pairs
    unchanged = 0
    if before:
        seen: dict[str, int] = {}
        for _, value in _pairs(before):
            seen[value] = seen.get(value, 0) + 1
        kept = []
        hidden_parents: dict[str, int] = {}
        for path, value in pairs:
            left = seen.get(value, 0)
            if left:
                # Repeat of something the previous page showed. Counted here so
                # the total is honest even when several copies survive, and its
                # parent is remembered so the note below can cite a level that
                # actually holds some of what was withheld.
                seen[value] = left - 1
                unchanged += 1
                parent, _ = _split_tail(path)
                if parent:
                    hidden_parents[parent] = hidden_parents.get(parent, 0) + 1
                continue
            kept.append((path, value))
        example = max(hidden_parents, key=hidden_parents.get) if hidden_parents else ""

    added = render_text(kept)
    if unchanged:
        # Says plainly what was withheld and how to get it, because the levels
        # are the answer: the agent saw them on the page it came from, and an
        # unchanged subtree still sits at the level it sat at then. So this is
        # not "some text is missing" -- it is "the parts you already read are
        # where you left them", which is a fact it can act on.
        where = example or "the level it was at"
        added.append(
            f"… {unchanged} string{'s' if unchanged != 1 else ''} identical to "
            f"the previous page {'are' if unchanged != 1 else 'is'} not "
            f"repeated here -- only what changed is shown above. To read any of "
            f"them again, ask for the level: "
            f'{{"op": "get_text", "level": "{where}"}} returns that subtree and '
            f"nothing else."
        )

    added, removed_kept, truncated = _cap(
        added, render_text(_pairs(removed)) if include_removed else [], max_chars
    )
    out = {"added": added, "truncated": truncated}
    if unchanged:
        out["unchanged_count"] = unchanged
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
    # A frame's paths start at its own body, so they would read as host paths
    # and collide with them. The frame's position goes in front, which keeps
    # every path in the merged track pointing at exactly one element.
    tag_path = "".join(f"[f{index}]" for index in path)
    state["text"].extend(
        (tag_path + item_path, value) for item_path, value in _pairs(sub.get("text"))
    )
    # A frame's unwalked roots are unwalked places too, so they add up.
    state["shadow_hosts"] = state.get("shadow_hosts", 0) + sub.get("shadow_hosts", 0)
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
