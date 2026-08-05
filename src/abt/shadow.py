"""Searching the trees a page keeps beside its document.

A shadow root is a separate tree hanging off a host element. The snapshot's
TreeWalker does not cross into it, `innerText` stops at the host, and
`querySelectorAll` from the document never sees inside -- the same silence an
iframe used to produce, by a different mechanism.

**Why this is opt-in when frames are not.** A page that has frames nearly
always has content in them, so folding them into the tracks pays for itself. A
page that has shadow roots usually does not: component libraries put their
internals there, and the internals are rarely what anyone came for. On the
LinkedIn profile-setup page that prompted this there was exactly one author
root and nothing in it -- walking it on every snapshot would have cost the
whole session and bought nothing.

So the split is: the snapshot **counts** hosts, which is one property check on
a walk already happening, and `shadow: true` on a search is what actually looks
inside. The count is what makes the silence legible -- an empty diff on a page
with hosts means "nothing changed where I looked", and an agent can tell that
from "nothing changed".

That is also what lets the search ladder end. A search that has looked in the
document, its frames and its open shadow roots has looked everywhere reachable,
and can report "not there" as a fact rather than a shrug.

**The limit, stated rather than papered over.** `attachShadow({mode: 'closed'})`
makes `host.shadowRoot` null. Nothing in JavaScript can read such a root or
even prove it exists, so nothing here can either. They are rare in author code
-- mostly browser internals, the controls inside `<video>` and friends -- but
they are why the rule is "nothing reachable has it" and not "it does not
exist".
"""

from __future__ import annotations

from selenium.common.exceptions import WebDriverException

# Hosts descended into per search. A design system can mount hundreds; the cap
# stops one search from turning into a full-page component audit.
MAX_SHADOW_HOSTS = 400

# Roots inside roots inside roots. Real nesting is two or three deep.
MAX_SHADOW_DEPTH = 10

# Counting only. Runs on the light DOM of one document, so it says how many
# places this snapshot did not look -- not what is in them.
_COUNT_JS = """
let hosts = 0;
const all = document.querySelectorAll('*');
for (let i = 0; i < all.length; i++) {
  if (all[i].shadowRoot) hosts++;
}
return hosts;
"""

# Collects matches across the document and every open root beneath it. Handles
# come straight back as elements, so a ref made from one acts like any other.
_SEARCH_JS = """
const selector = arguments[0];
const mode = arguments[1];
const limit = arguments[2];
const maxHosts = arguments[3];
const maxDepth = arguments[4];
const out = [];
let hosts = 0;

const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();

const collect = (root) => {
  if (mode === 'css') {
    let found;
    try { found = root.querySelectorAll(selector); } catch (e) { return; }
    for (let i = 0; i < found.length && out.length < limit; i++) {
      out.push(found[i]);
    }
    return;
  }
  // Text mode mirrors the xpath the light-DOM path uses: an element whose
  // whole normalised text is the string, ancestors included.
  const all = root.querySelectorAll('*');
  for (let i = 0; i < all.length && out.length < limit; i++) {
    if (norm(all[i].textContent) === selector) out.push(all[i]);
  }
};

const walk = (root, depth) => {
  collect(root);
  if (depth >= maxDepth || out.length >= limit) return;
  const all = root.querySelectorAll('*');
  for (let i = 0; i < all.length; i++) {
    // Null for a closed root, and indistinguishable from having none at all.
    const sub = all[i].shadowRoot;
    if (!sub) continue;
    hosts++;
    if (hosts > maxHosts) return;
    walk(sub, depth + 1);
    if (out.length >= limit) return;
  }
};

walk(document, 0);
return out;
"""


def host_count(driver) -> int:
    """How many open shadow roots hang off the current document.

    Best effort: a driver that will not answer reports none, because this is a
    hint about where else to look and must never fail a command.
    """
    try:
        found = driver.execute_script(_COUNT_JS)
    except WebDriverException:
        return 0
    return int(found or 0)


def search(driver, selector: str, mode: str, limit: int) -> list:
    """Elements matching `selector` in this document and its open roots."""
    try:
        found = driver.execute_script(
            _SEARCH_JS, selector, mode, limit, MAX_SHADOW_HOSTS, MAX_SHADOW_DEPTH
        )
    except WebDriverException:
        return []
    return [el for el in found or [] if el is not None]
