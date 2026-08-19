"""Per-tab element ref cache.

`find` hands back stable names (el_0, el_1, ...) so an agent can search once and
then act, instead of constructing selectors it may get wrong. Refs die when the
tab navigates or the element leaves the DOM -- acting on a dead ref is an error,
never a silent hit on a different element.
"""

from __future__ import annotations

from .engine import Element, NoSuchElement, StaleElement
from .errors import OpError


class RefCache:
    """Names to elements, plus the frame each element was found in.

    An Element only answers while the driver is switched into the document it
    came from, so a ref for something inside a frame is half a handle on its
    own. The frame path is stored with it and `BrowserSession.resolve_ref` goes
    there first -- otherwise a ref from a sign-in widget would report stale from
    the top document, which is true of the lookup and false of the element.
    """

    def __init__(self) -> None:
        self._tabs: dict[str, dict[str, Element]] = {}
        self._frames: dict[str, dict[str, tuple[int, ...]]] = {}
        self._counters: dict[str, int] = {}

    def allocate(
        self,
        tab_id: str,
        elements: list[Element],
        frame: tuple[int, ...] = (),
    ) -> list[str]:
        table = self._tabs.setdefault(tab_id, {})
        homes = self._frames.setdefault(tab_id, {})
        start = self._counters.get(tab_id, 0)
        names = []
        for offset, element in enumerate(elements):
            name = f"el_{start + offset}"
            table[name] = element
            if frame:
                homes[name] = tuple(frame)
            names.append(name)
        self._counters[tab_id] = start + len(elements)
        return names

    def frame_of(self, tab_id: str, ref: str) -> tuple[int, ...]:
        """Where this ref lives. The top document for anything unrecorded, so an
        unknown ref fails as a stale ref rather than as a missing frame."""
        return self._frames.get(tab_id, {}).get(ref, ())

    def get(self, tab_id: str, ref: str) -> Element:
        element = self._tabs.get(tab_id, {}).get(ref)
        if element is None:
            raise OpError(
                "stale_ref",
                f"ref {ref!r} is not known for tab {tab_id}; run find again",
            )
        try:
            element.is_enabled()
        except (StaleElement, NoSuchElement) as exc:
            self._tabs[tab_id].pop(ref, None)
            self._frames.get(tab_id, {}).pop(ref, None)
            raise OpError(
                "stale_ref",
                f"ref {ref!r} no longer matches an element in the DOM; run find again",
            ) from exc
        return element

    def invalidate(self, tab_id: str) -> None:
        """Drop every ref for a tab. Called whenever the tab navigates.

        The counter deliberately survives, so names are never reused within a
        tab's life. If numbering restarted, the new page's el_0 would answer to
        a caller still holding el_0 from the old one -- the silent wrong-element
        hit that stale_ref exists to prevent. Names climbing into the thousands
        on a long session is the cheaper problem.
        """
        self._tabs.pop(tab_id, None)
        self._frames.pop(tab_id, None)

    def drop_tab(self, tab_id: str) -> None:
        """Forget a closed tab entirely. Tab ids are never reissued, so the
        counter can go with it."""
        self.invalidate(tab_id)
        self._counters.pop(tab_id, None)

    def count(self, tab_id: str) -> int:
        return len(self._tabs.get(tab_id, {}))
