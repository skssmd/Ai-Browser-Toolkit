"""Glue between BrowserGym episodes and the ai-browser-toolkit server.

Architecture (one browser, two clients):

    Chromium  <-- launched by BrowserGym with --remote-debugging-port=N
      |  obs + scoring (BrowserGym's own task.validate)
      |  actions (every op goes through the abt HTTP API)
    abt server <-- attached over CDP (ABT_CDP_URL)

BrowserGym stamps every interactable element with a literal ``bid`` DOM
attribute while extracting observations. Because abt attaches to the same
browser, those elements are addressable from abt as plain CSS:
``[bid="<bid>"]``. That is the whole translation trick: the agent reads
BrowserGym's accessibility tree, emits standard BrowserGym action strings,
and this module lowers them to toolkit ops against the identical DOM.
"""

from __future__ import annotations

import ast
import json
import urllib.request


class AbtClient:
    """Thin synchronous client for the abt HTTP surface."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, payload) -> dict:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        return json.loads(urllib.request.urlopen(req, timeout=120).read())

    def command(self, cmd: dict) -> dict:
        return self._post("/command", cmd)

    def commands(self, cmds: list[dict]) -> dict:
        return self._post("/commands", cmds)

    def browser_state(self) -> dict:
        req = urllib.request.urlopen(self.base_url + "/browser", timeout=10)
        return json.loads(req.read())

    def attach(self, headless: bool | None = False) -> dict:
        """Attach (or re-attach) to the harness browser.

        One BrowserGym reset() launches a brand-new browser process, so every
        episode starts with a fresh attach. restart covers both the first
        episode (nothing running) and subsequent ones (attached to the corpse
        of the previous browser).
        """
        state = self.browser_state()
        running = state.get("result", {}).get("running", state.get("running"))
        op = "browser_restart" if running else "browser_start"
        body = {"op": op}
        if headless is not None:
            body["headless"] = headless
        return self.command(body)


def inject_cdp_port(port: int) -> None:
    """Make BrowserGym launch its chromium with a CDP endpoint.

    BrowserEnv builds launch(args=[...]) explicitly and splats
    pw_chromium_kwargs afterwards, so passing args there collides. Wrapping
    the global playwright's BrowserType.launch adds the flag without touching
    browsergym's code: the harness stays stock.
    """
    import browsergym.core.env as bgenv

    original_get_pw = bgenv._get_global_playwright

    def get_pw():
        pw = original_get_pw()
        bt = pw.chromium
        if not getattr(bt, "_abt_cdp_patched", False):
            original_launch = bt.launch

            def launch(*args, **kwargs):
                kwargs["args"] = list(kwargs.get("args") or []) + [
                    f"--remote-debugging-port={port}"
                ]
                return original_launch(*args, **kwargs)

            bt.launch = launch
            bt._abt_cdp_patched = True
        return pw

    bgenv._get_global_playwright = get_pw


def _parse_call(action: str) -> tuple[str, list, dict]:
    """Parse one action string ('click(bid=\\'x\\')') without executing it.

    BrowserGym's own executor evals these against its page; here they only
    need to be inspected, so ast.parse does it safely.
    """
    tree = ast.parse(action.strip(), mode="eval")
    if not isinstance(tree.body, ast.Call) or not isinstance(tree.body.func, ast.Name):
        raise ValueError(f"not a function call: {action!r}")
    name = tree.body.func.id
    pos = [ast.literal_eval(a) for a in tree.body.args]
    kw = {k.arg: ast.literal_eval(k.value) for k in tree.body.keywords}
    return name, pos, kw


def _target(bid: str) -> dict:
    return {"css": '[bid="%s"]' % bid.replace('"', '\\"')}


def lower_action(action: str) -> list[dict]:
    """Lower one BrowserGym high-level action string to a list of abt ops.

    Covers the subset of the standard action space an agent needs on
    WebArena/MiniWoB. Anything unmapped raises, loudly: a silently dropped
    action would look exactly like an agent mistake and poison the number.
    """
    name, pos, kw = _parse_call(action)

    def arg(index, key):
        if index < len(pos):
            return pos[index]
        return kw[key]

    if name == "noop":
        # No page interaction involved; the pause itself happens inside
        # BrowserGym's executor when env.step() runs noop(wait_ms).
        return []
    if name == "goto":
        return [{"op": "goto", "url": arg(0, "url")}]
    if name == "go_back":
        return [{"op": "back"}]
    if name == "go_forward":
        return [{"op": "forward"}]
    if name == "new_tab":
        return [{"op": "tab_new"}]
    if name == "tab_close":
        return [{"op": "tab_close"}]
    if name == "tab_focus":
        tabs = None  # resolved at runtime by the caller via tab_list if needed
        raise NotImplementedError("tab_focus(index) requires tab_list resolution")
    if name in ("click", "dblclick", "hover", "check", "uncheck", "focus"):
        op = {"click": "click", "dblclick": "click", "hover": "hover",
              "check": "click", "uncheck": "click", "focus": "click"}[name]
        cmd = {"op": op, **_target(arg(0, "bid"))}
        if name == "dblclick":
            cmd["force"] = True
        return [cmd]
    if name == "clear":
        return [{"op": "input", **_target(arg(0, "bid")), "value": "", "clear": True}]
    if name in ("fill", "type"):
        return [{"op": "input", **_target(arg(0, "bid")), "value": str(arg(1, "value"))}]
    if name == "select_option":
        options = arg(1, "options")
        options = [options] if isinstance(options, str) else list(options)
        # MiniWoB and WebArena selects match by visible label; a validator that
        # reads values still sees the same selection. One op per call: the
        # batch stops at the first failure, so a bad label surfaces loudly.
        return [{"op": "select", **_target(arg(0, "bid")), "by_text": options[0]}]
    if name == "press":
        keys = str(arg(1, "key_comb"))
        return [
            {"op": "click", **_target(arg(0, "bid"))},
            *[{"op": "press", "key": k.strip()} for k in keys.split(",")],
        ]
    if name == "scroll":
        dx, dy = arg(0, "delta_x"), arg(1, "delta_y")
        return [{"op": "scroll", "y": int(dy)}]
    if name == "upload_file":
        return [{"op": "input", **_target(arg(0, "bid")), "value": str(arg(1, "file"))}]
    if name in ("send_msg_to_user", "report_infeasible"):
        # Agent-level signals, not page actions: nothing to drive.
        return []
    raise NotImplementedError(f"action {name!r} not mapped to abt ops")


def run_actions(client: AbtClient, action: str) -> tuple[int, str | None]:
    """Execute one lowered action. Returns (ops_run, error_or_None)."""
    ops = lower_action(action)
    if not ops:
        return 0, None
    payload = client.commands(ops)
    if payload.get("ok"):
        return len(ops), None
    err = payload.get("error") or {}
    return int(payload.get("ran", 0)), f"{err.get('type')}: {err.get('msg')}"
