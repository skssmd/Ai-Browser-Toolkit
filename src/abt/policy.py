"""Which URLs a session may reach.

A session's `rules` are strings like `app.domain.com/admin` (allow) and
`!app.domain.com/api` (deny). Deny wins; any allow rule turns the list into an
allow-list. See the session-policy design for the full grammar.

Pure: no browser, no I/O. The same object answers the op-level check before a
`goto` and every request the network guard pauses, so the two can never
disagree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import OpError

# URLs that fetch nothing. Refusing them would break pages without protecting
# anything: about:blank is where every new tab starts.
_INERT = ("about", "data", "blob")
_WEB = ("http", "https", "ws", "wss")

# Checked without `strict`: what a page *is*, and how it talks to a server.
# Stylesheets, images, fonts and scripts load from wherever the page says, so
# an allow-listed site still works when its assets live on a CDN.
NAVIGATION_AND_DATA = frozenset(
    {"Document", "document", "XHR", "xhr", "Fetch", "fetch", "EventSource", "eventsource",
     "WebSocket", "websocket"}
)

_HOST = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:\d{1,5})?$")


@dataclass(frozen=True)
class Rule:
    text: str
    deny: bool
    host: str  # lowercased; may start with "*."
    path: str  # "" or "/segment[/...]", no trailing slash

    def matches(self, host: str, path: str) -> bool:
        if self.host.startswith("*."):
            base = self.host[2:]
            if host != base and not host.endswith("." + base):
                return False
        elif host != self.host:
            return False
        if not self.path:
            return True
        return path == self.path or path.startswith(self.path + "/")


def parse_rule(text: str) -> Rule:
    if not isinstance(text, str) or not text.strip():
        raise OpError("invalid_op", f"a URL rule must be a non-empty string, got {text!r}")
    raw = text.strip()
    deny = raw.startswith("!")
    body = raw[1:].strip() if deny else raw
    if "://" in body:
        body = body.split("://", 1)[1]
    host, _, path = body.partition("/")
    host = host.lower()
    if not _HOST.match(host):
        raise OpError(
            "invalid_op",
            f"bad URL rule {text!r}: expected [!]HOST[/PATH], e.g. "
            "'app.example.com/admin' or '!app.example.com/api'",
        )
    path = "/" + path.strip("/") if path.strip("/") else ""
    return Rule(text=raw, deny=deny, host=host, path=path)


class Policy:
    """A session's rules, compiled. Falsy when there are none."""

    def __init__(self, rules: list[str] | None = None, strict: bool = False) -> None:
        self.rules = [parse_rule(r) for r in (rules or [])]
        self.strict = bool(strict)
        self._allow_list = any(not r.deny for r in self.rules)

    def __bool__(self) -> bool:
        return bool(self.rules)

    def verdict(self, url: str) -> tuple[bool, str | None]:
        """(allowed, the rule that decided it -- None when no rule did)."""
        if not self.rules:
            return True, None
        try:
            parts = urlsplit(url)
        except ValueError:
            return False, None
        scheme = parts.scheme.lower()
        if scheme in _INERT:
            return True, None
        if scheme not in _WEB:
            return False, None
        host = (parts.hostname or "").lower()
        if parts.port is not None:
            with_port = f"{host}:{parts.port}"
        else:
            with_port = host
        path = parts.path or "/"

        def hit(rule: Rule) -> bool:
            target = with_port if ":" in rule.host else host
            return rule.matches(target, path)

        for rule in self.rules:
            if rule.deny and hit(rule):
                return False, rule.text
        if not self._allow_list:
            return True, None
        for rule in self.rules:
            if not rule.deny and hit(rule):
                return True, rule.text
        return False, None

    def allows(self, url: str) -> bool:
        return self.verdict(url)[0]

    def guards(self, resource_type: str) -> bool:
        """Whether a request of this kind is checked at all."""
        return self.strict or resource_type in NAVIGATION_AND_DATA

    def check(self, url: str) -> None:
        """Raise `url_blocked` for a URL this session may not reach."""
        allowed, rule = self.verdict(url)
        if allowed:
            return
        why = f"it matches {rule!r}" if rule else "no allow rule covers it"
        raise OpError("url_blocked", f"this session's rules do not allow {url}: {why}")


def validate_settings(settings: object) -> dict:
    """Check the policy keys of a settings object; return it unchanged.

    Unknown keys pass through untouched -- later features add their own.
    """
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise OpError("invalid_op", "settings must be an object")
    rules = settings.get("rules")
    if rules is not None:
        if not isinstance(rules, list):
            raise OpError("invalid_op", "settings.rules must be a list of strings")
        for rule in rules:
            parse_rule(rule)
    for key in ("strict", "run_js", "uploads_only"):
        value = settings.get(key)
        if value is not None and not isinstance(value, bool):
            raise OpError("invalid_op", f"settings.{key} must be true or false")
    return settings


def from_settings(settings: dict | None) -> Policy:
    settings = settings or {}
    return Policy(settings.get("rules") or [], bool(settings.get("strict")))
