"""Tab ops. Tab ids are server-assigned and stay stable across switches.

On a shared profile they are numbered per profile, and another session's tab
is visible but locked: see `BrowserSession.foreign_tabs`.
"""

from __future__ import annotations

from ..browser import BrowserSession


def tab_new(session: BrowserSession, cmd) -> dict:
    tab_id = session.new_tab(cmd.url, cmd.activate)
    return {"tab_id": tab_id, "tabs": session.tabs()}


def tab_list(session: BrowserSession, cmd) -> list[dict]:
    return session.tabs() + session.foreign_tabs()


def tab_switch(session: BrowserSession, cmd) -> dict:
    session.check_tab(cmd.tab_id)
    session.switch_tab(cmd.tab_id)
    return {"tab_id": cmd.tab_id, **session.location()}


def tab_close(session: BrowserSession, cmd) -> dict:
    if cmd.tab_id:
        session.check_tab(cmd.tab_id)
    session.close_tab(cmd.tab_id)
    return {"active_tab": session.active_tab, "tabs": session.tabs()}


def tab_claim(session: BrowserSession, cmd) -> dict:
    tab_id = session.claim_tab(cmd.tab_id)
    return {"tab_id": tab_id, "tabs": session.tabs()}


def tab_release(session: BrowserSession, cmd) -> dict:
    tab_id = session.release_tab(cmd.tab_id)
    return {"released": tab_id, "tabs": session.tabs()}
