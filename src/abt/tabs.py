"""Which session owns which tab, per profile.

One `TabRegistry` per profile, keyed on Chrome's target id -- the one identity
every connection to that Chrome agrees on. It also hands out the `tab_N` ids
callers see, so two sessions on one profile, and the GUI watching them, call
the same tab by the same name.

Pure bookkeeping: no browser, no I/O. The lock is held only to read or change
the maps, never across browser work, so it can never make one session wait on
another's click.
"""

from __future__ import annotations

import threading

from .errors import OpError

OWN = "own"
LOCKED = "locked"
UNOWNED = "unowned"


class TabRegistry:
    def __init__(self, profile: str) -> None:
        self.profile = profile
        self._lock = threading.Lock()
        # target -> owning session, or None for a tab nobody owns. A target
        # missing from this map has not been seen yet.
        self._owner: dict[str, str | None] = {}
        self._label: dict[str, str] = {}
        self._target: dict[str, str] = {}
        # Never reset, not even when Chrome restarts: a stale `tab_3` has to
        # fail as not-found rather than quietly land on a newer tab.
        self._counter = 0

    # --- ids ------------------------------------------------------------------

    def label(self, target: str) -> str:
        with self._lock:
            return self._label_of(target)

    def _label_of(self, target: str) -> str:
        found = self._label.get(target)
        if found is None:
            found = f"tab_{self._counter}"
            self._counter += 1
            self._label[target] = found
            self._target[found] = target
        return found

    def target_of(self, label: str) -> str | None:
        with self._lock:
            return self._target.get(label)

    # --- ownership ------------------------------------------------------------

    def owner_of(self, target: str) -> str | None:
        with self._lock:
            return self._owner.get(target)

    def placed(self, target: str) -> bool:
        """Whether any connection has decided who owns this page yet."""
        with self._lock:
            return target in self._owner

    def opened(self, target: str, session: str) -> str:
        """A tab `session` opened itself. Returns its id.

        Another connection may already have noticed the page and recorded it
        as unowned -- that is not a conflict, only an owner is.
        """
        with self._lock:
            label = self._label_of(target)
            current = self._owner.get(target)
            if current not in (None, session):
                raise _locked(label, current)
            self._owner[target] = session
            return label

    def adopt(self, target: str, opener: str | None) -> str | None:
        """Place a page seen for the first time, and return its owner.

        A page opened by another page belongs to whoever owns the opener, so a
        popup follows the session that caused it. Anything else starts
        unowned. A page already placed keeps its owner.
        """
        with self._lock:
            self._label_of(target)
            if target in self._owner:
                return self._owner[target]
            owner = self._owner.get(opener) if opener else None
            self._owner[target] = owner
            return owner

    def claim(self, target: str, session: str, opener: str | None = None) -> str:
        """Take an unowned tab. A popup of someone else's tab is theirs, even
        if they have not noticed it yet -- otherwise there is a window in which
        any session can take it."""
        with self._lock:
            label = self._label_of(target)
            current = self._owner.get(target)
            if current is None and opener:
                current = self._owner.get(opener)
                if current is not None:
                    self._owner[target] = current
            if current not in (None, session):
                raise _locked(label, current)
            self._owner[target] = session
            return label

    def release(self, target: str, session: str) -> None:
        with self._lock:
            current = self._owner.get(target)
            if current != session:
                raise _locked(self._label_of(target), current)
            self._owner[target] = None

    def set_owner(self, target: str, session: str | None) -> str:
        """The operator's override. No ownership check, by design."""
        with self._lock:
            self._owner[target] = session
            return self._label_of(target)

    def access(self, target: str, session: str) -> str:
        with self._lock:
            owner = self._owner.get(target)
        if owner == session:
            return OWN
        return UNOWNED if owner is None else LOCKED

    def owned_by(self, session: str) -> list[str]:
        with self._lock:
            return [t for t, owner in self._owner.items() if owner == session]

    def forget(self, target: str) -> None:
        with self._lock:
            self._owner.pop(target, None)
            label = self._label.pop(target, None)
            if label is not None:
                self._target.pop(label, None)

    def clear(self) -> None:
        """Chrome restarted and every tab went with it. Ids are not reissued."""
        with self._lock:
            self._owner.clear()
            self._label.clear()
            self._target.clear()


def _locked(label: str, owner: str | None) -> OpError:
    if owner is None:
        return OpError(
            "tab_locked",
            f"{label} is not yours: nobody owns it",
            hint="Take it with tab_claim, or open your own with tab_new.",
        )
    return OpError("tab_locked", f"{label} belongs to session {owner!r}")


class TabGate:
    """One session's view of its profile's registry.

    What the driver and `BrowserSession` hold. They only ever ask about their
    own session, so the name is bound once here instead of being threaded
    through every call.
    """

    def __init__(self, registry: TabRegistry, session: str) -> None:
        self.registry = registry
        self.session = session

    def opened(self, target: str) -> str:
        return self.registry.opened(target, self.session)

    def sees(self, target: str, opener: str | None) -> bool:
        return self.registry.adopt(target, opener) == self.session

    def owns(self, target: str) -> bool:
        return self.registry.owner_of(target) == self.session

    def owner(self, target: str) -> str | None:
        return self.registry.owner_of(target)

    def placed(self, target: str) -> bool:
        return self.registry.placed(target)

    def label(self, target: str) -> str:
        return self.registry.label(target)

    def target_of(self, label: str) -> str | None:
        return self.registry.target_of(label)

    def check(self, label: str) -> None:
        """Refuse a tab id this session may not act on.

        An id this profile has never issued passes: the session's own tab
        registry then reports it as `tab_not_found`, exactly as it does today.
        """
        target = self.registry.target_of(label)
        if target is None:
            return
        if self.registry.access(target, self.session) != OWN:
            raise _locked(label, self.registry.owner_of(target))

    def claim(self, target: str, opener: str | None) -> str:
        return self.registry.claim(target, self.session, opener)

    def release(self, target: str) -> None:
        self.registry.release(target, self.session)
