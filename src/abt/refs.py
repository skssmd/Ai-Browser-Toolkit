"""Per-tab element ref cache.

`find` hands back stable names (el_0, el_1, ...) so an agent can search once and
then act, instead of constructing selectors it may get wrong. Refs die when the
tab navigates or the element leaves the DOM -- acting on a dead ref is an error,
never a silent hit on a different element.
"""

from __future__ import annotations

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.remote.webelement import WebElement

from .errors import OpError


class RefCache:
    def __init__(self) -> None:
        self._tabs: dict[str, dict[str, WebElement]] = {}
        self._counters: dict[str, int] = {}

    def allocate(self, tab_id: str, elements: list[WebElement]) -> list[str]:
        table = self._tabs.setdefault(tab_id, {})
        start = self._counters.get(tab_id, 0)
        names = []
        for offset, element in enumerate(elements):
            name = f"el_{start + offset}"
            table[name] = element
            names.append(name)
        self._counters[tab_id] = start + len(elements)
        return names

    def get(self, tab_id: str, ref: str) -> WebElement:
        element = self._tabs.get(tab_id, {}).get(ref)
        if element is None:
            raise OpError(
                "stale_ref",
                f"ref {ref!r} is not known for tab {tab_id}; run find again",
            )
        try:
            element.is_enabled()
        except (StaleElementReferenceException, NoSuchElementException) as exc:
            self._tabs[tab_id].pop(ref, None)
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

    def drop_tab(self, tab_id: str) -> None:
        """Forget a closed tab entirely. Tab ids are never reissued, so the
        counter can go with it."""
        self.invalidate(tab_id)
        self._counters.pop(tab_id, None)

    def count(self, tab_id: str) -> int:
        return len(self._tabs.get(tab_id, {}))
