"""Tab ops. Tab ids are server-assigned and stay stable across switches."""

from __future__ import annotations

from ..browser import BrowserSession


def tab_new(session: BrowserSession, cmd) -> dict:
    tab_id = session.new_tab(cmd.url, cmd.activate)
    return {"tab_id": tab_id, "tabs": session.tabs()}


def tab_list(session: BrowserSession, cmd) -> list[dict]:
    return session.tabs()


def tab_switch(session: BrowserSession, cmd) -> dict:
    session.switch_tab(cmd.tab_id)
    return {"tab_id": cmd.tab_id, **session.location()}


def tab_close(session: BrowserSession, cmd) -> dict:
    session.close_tab(cmd.tab_id)
    return {"active_tab": session.active_tab, "tabs": session.tabs()}
