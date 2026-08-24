"""Pydantic models for every command. Validation happens before the browser is touched."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import OpError

TARGET_FIELDS = ("ref", "css", "xpath", "text")


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Base):
    """Targeting fields shared by every op that acts on an element."""

    ref: str | None = None
    css: str | None = None
    xpath: str | None = None
    text: str | None = None
    index: int = 0
    # Not a selector -- a qualifier on one. `text: "Edit"` names a dozen
    # buttons on a table of documents; `near: "Medication"` says which. Kept
    # out of TARGET_FIELDS deliberately, so it combines with a selector rather
    # than competing with one.
    near: str | None = None

    # Subclasses set this to False when "no target" means "the whole document".
    target_required: ClassVar[bool] = True

    @model_validator(mode="after")
    def _exactly_one_target(self):
        given = [f for f in TARGET_FIELDS if getattr(self, f) is not None]
        if len(given) > 1:
            raise ValueError(f"supply only one of {', '.join(TARGET_FIELDS)}, got {given}")
        if not given and self.target_required:
            raise ValueError(f"one of {', '.join(TARGET_FIELDS)} is required")
        if self.near is not None and self.ref is not None:
            raise ValueError(
                "near qualifies a selector that matches several elements; a ref "
                "already names exactly one"
            )
        return self

    @property
    def has_target(self) -> bool:
        return any(getattr(self, f) is not None for f in TARGET_FIELDS)


class OptionalTarget(Target):
    target_required: ClassVar[bool] = False


class Diffable(Base):
    """Ops that report what they changed on the page.

    `diff` defaults to None, meaning "follow the server's --diff default".
    Set it true to force a diff on a command, false to suppress one entirely.

    What you get by default is the *text* diff: the strings that appeared on
    screen. It is small enough to always be on, so it has no budget.

    `include_removed` adds the strings that left the screen. Off by default
    because on a page that swaps its body they are the whole old document; the
    count is reported either way, so you can always tell when it is worth
    asking.

    `element_diff` adds the element-level diff -- tags, ids, classes,
    attributes -- for when you need to know which element the text belongs to,
    or when the change was an attribute with no visible text at all.
    `diff_max_tokens` budgets that element diff, and supplying it implies
    `element_diff` since a budget for something you did not ask for is a typo.

    `actionable` is the ref-and-role decoration on the text track, on by
    default. Unlike the text track it is not free -- it costs roughly a quarter
    again on top of a diffed op -- so it can be switched off for the commands in
    a batch whose new controls you are never going to click.
    """

    diff: bool | None = None
    include_removed: bool = False
    element_diff: bool = False
    actionable: bool = True
    diff_max_tokens: int | None = Field(default=None, ge=1, le=100_000)

    @model_validator(mode="after")
    def _budget_implies_elements(self):
        if self.diff_max_tokens is not None:
            self.element_diff = True
        return self


# --- navigation ---------------------------------------------------------------


# Navigation ops are Diffable so they can hand back the page they landed on.
# There is nothing to diff against once the document is replaced, so the text
# track carries the whole new page and the element track is skipped.


class Goto(Diffable):
    op: Literal["goto"]
    url: str


class Back(Diffable):
    op: Literal["back"]


class Forward(Diffable):
    op: Literal["forward"]


class Reload(Diffable):
    op: Literal["reload"]


class CurrentUrl(Base):
    op: Literal["current_url"]


# --- reading ------------------------------------------------------------------


class GetHtml(OptionalTarget):
    op: Literal["get_html"]


class GetText(OptionalTarget):
    op: Literal["get_text"]


class ShadowSearch(Target):
    """A search that can also look inside open shadow roots.

    Off by default. Most pages have no author shadow roots at all, and the ones
    that do keep component internals there rather than anything you came for --
    so the walk is opt-in and a plain search stays the cheap common case. When
    a search comes back empty on a page that has hosts, the response says so,
    which is the cue to turn this on.

    css and text only. The walk is `querySelectorAll` on each root, which is
    the only way across the boundary and does not speak xpath.
    """

    shadow: bool = False

    @model_validator(mode="after")
    def _shadow_needs_a_reachable_selector(self):
        if self.shadow and (self.xpath is not None or self.ref is not None):
            raise ValueError(
                "shadow search takes css or text; xpath cannot cross a shadow "
                "boundary and a ref already names an element"
            )
        return self


class Find(ShadowSearch):
    op: Literal["find"]
    mode: Literal["shell", "full"] = "shell"
    limit: int = Field(default=100, ge=1, le=1000)
    visible_only: bool = False


class FindFull(ShadowSearch):
    op: Literal["find_full"]
    limit: int = Field(default=100, ge=1, le=1000)
    visible_only: bool = False


class Screenshot(OptionalTarget):
    """A frame of the page, returned as a file path.

    `base64: true` inlines the image instead. Only ask for that from a client
    that renders images inline -- a base64 PNG is hundreds of thousands of
    characters, and a caller that reads its tool output as text gets its
    context filled with an image it still cannot see.
    """

    op: Literal["screenshot"]
    base64: bool = False


# --- interaction --------------------------------------------------------------


class Click(Diffable, OptionalTarget):
    """A click on an element, or at a point.

    `at: [x, y]` clicks a coordinate with a real synthesized mouse event, for
    things the DOM cannot address: a canvas, a closed shadow root, an image map.
    On its own it is a point in the viewport. Combined with a target it is an
    offset inside that element -- `{"css": "canvas", "at": [120, 40]}` -- which
    is what you almost always want, since it survives scrolling and does not
    depend on where the page happens to sit.
    """

    op: Literal["click"]
    at: tuple[int, int] | None = None
    force: bool = False
    new_tab: bool = False
    activate: bool = True

    @model_validator(mode="after")
    def _target_or_point(self):
        if not self.has_target and self.at is None:
            raise ValueError(f"one of {', '.join(TARGET_FIELDS)}, or at, is required")
        if self.force and self.new_tab:
            raise ValueError(
                "force and new_tab are mutually exclusive; new_tab opens the href "
                "directly and never dispatches a click"
            )
        if self.at is not None and (self.force or self.new_tab):
            raise ValueError(
                "at is a raw mouse click: force has nothing to defeat, and there "
                "is no href at a coordinate to open in a new tab"
            )
        return self


class Input(Diffable, Target):
    op: Literal["input"]
    value: str
    clear: bool = True


class Select(Diffable, Target):
    op: Literal["select"]
    by_text: str | None = None
    value: str | None = None
    option_index: int | None = None

    @model_validator(mode="after")
    def _exactly_one_choice(self):
        given = [
            f for f in ("by_text", "value", "option_index") if getattr(self, f) is not None
        ]
        if len(given) != 1:
            raise ValueError("supply exactly one of by_text, value, option_index")
        return self


class Hover(Diffable, Target):
    op: Literal["hover"]


class Scroll(Diffable, OptionalTarget):
    op: Literal["scroll"]
    y: int | None = None

    @model_validator(mode="after")
    def _target_or_y(self):
        if self.has_target and self.y is not None:
            raise ValueError("supply a target or y, not both")
        if not self.has_target and self.y is None:
            raise ValueError("supply a target or y")
        return self


class WaitFor(Diffable, Target):
    op: Literal["wait_for"]
    state: Literal["present", "visible", "clickable", "absent"] = "visible"
    timeout: float = Field(default=10.0, gt=0, le=300)


class Press(Diffable, OptionalTarget):
    op: Literal["press"]
    key: str
    """A single character, a named key (e.g. "Enter", "Tab", "Backspace"), or a
    modifier chord like "ctrl+v", "ctrl+alt+1", or "shift+enter". Modifiers:
    ctrl/control, shift, alt/option, meta/command/cmd/windows."""


# --- tabs ---------------------------------------------------------------------


class TabNew(Base):
    op: Literal["tab_new"]
    url: str | None = None
    activate: bool = True


class TabList(Base):
    op: Literal["tab_list"]


class TabSwitch(Base):
    op: Literal["tab_switch"]
    tab_id: str


class TabClose(Base):
    op: Literal["tab_close"]
    tab_id: str | None = None


# --- control ------------------------------------------------------------------


class RunJs(Diffable):
    op: Literal["run_js"]
    script: str
    args: list[Any] = Field(default_factory=list)


class Alert(Base):
    """A native browser dialog (alert/confirm/prompt), which lives outside the
    page DOM and so never shows up in a diff.

    action:
      text      -- report {present, text} without touching it
      accept    -- click OK / Yes
      dismiss   -- click Cancel / No
      send_text -- type `text` into a prompt, then accept it
    """

    op: Literal["alert"]
    action: Literal["text", "accept", "dismiss", "send_text"] = "accept"
    text: str | None = None

    @model_validator(mode="after")
    def _text_requires_send(self):
        if self.text is not None and self.action != "send_text":
            raise ValueError("text only applies to the 'send_text' action")
        return self


class Diff(Base):
    """The manual diff: current page against the last recorded baseline.

    Unlike the automatic diff on a command, this returns the element diff as
    well as the text diff by default -- you asked for it explicitly, so you get
    everything. Pass element_diff false for the text alone.
    """

    op: Literal["diff"]
    reset: bool = False
    include_removed: bool = True
    element_diff: bool = True
    actionable: bool = True
    max_tokens: int = Field(default=1000, ge=1, le=100_000)


class ReadConsole(Base):
    """What the page logged. Captured from document start, so a reload gives you
    everything a page said while loading -- which is where the useful errors
    usually are."""

    op: Literal["read_console"]
    pattern: str | None = None
    """Case-insensitive regex over the message text."""
    levels: list[Literal["log", "info", "warn", "error", "debug"]] = Field(
        default_factory=list
    )
    limit: int = Field(default=100, ge=1, le=500)


class ReadNetwork(Base):
    """What the page requested, and how each request answered.

    Statuses and URLs, not bodies. A cross-origin response without
    Timing-Allow-Origin reports `status: null` and `opaque: true` -- the browser
    genuinely will not say, so neither will this.
    """

    op: Literal["read_network"]
    pattern: str | None = None
    """Case-insensitive regex over the URL."""
    failures_only: bool = False
    """Keep only 4xx/5xx and responses the browser would not disclose."""
    min_status: int | None = Field(default=None, ge=100, le=599)
    limit: int = Field(default=100, ge=1, le=1000)


class Status(Base):
    op: Literal["status"]


class Shutdown(Base):
    op: Literal["shutdown"]


class BrowserStart(Base):
    """Launch a browser. Omitted fields fall back to the server's defaults."""

    op: Literal["browser_start"]
    browser: str | None = None
    profile: str | None = None
    headless: bool | None = None


class BrowserStop(Base):
    op: Literal["browser_stop"]


class BrowserRestart(Base):
    """Stop and start again. Omitted fields keep what is running now."""

    op: Literal["browser_restart"]
    browser: str | None = None
    profile: str | None = None
    headless: bool | None = None


class BrowserStatus(Base):
    op: Literal["browser_status"]


Command = Annotated[
    Union[
        Goto, Back, Forward, Reload, CurrentUrl,
        GetHtml, GetText, Find, FindFull, Screenshot,
        Click, Input, Select, Hover, Scroll, WaitFor, Press,
        TabNew, TabList, TabSwitch, TabClose,
        RunJs, Diff, Status, Shutdown, Alert,
        ReadConsole, ReadNetwork,
        BrowserStart, BrowserStop, BrowserRestart, BrowserStatus,
    ],
    Field(discriminator="op"),
]


class _Wrapper(BaseModel):
    command: Command


COMMAND_MODELS = get_args(get_args(Command)[0])

OP_NAMES = sorted(
    get_args(m.model_fields["op"].annotation)[0] for m in COMMAND_MODELS
)


def parse_command(data: Any) -> Any:
    """Validate a raw dict into a command model, or raise OpError('invalid_op')."""
    if not isinstance(data, dict):
        raise OpError("invalid_op", f"command must be an object, got {type(data).__name__}")
    if "op" not in data:
        raise OpError("invalid_op", "command is missing the 'op' field")
    if data["op"] not in OP_NAMES:
        raise OpError(
            "invalid_op", f"unknown op {data['op']!r}; known ops: {', '.join(OP_NAMES)}"
        )
    try:
        return _Wrapper(command=data).command
    except ValidationError as exc:
        raise OpError("invalid_op", _format_errors(data["op"], exc)) from exc


def _format_errors(op: str, exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"] if p not in ("command", op))
        parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return f"invalid args for op {op!r}: " + "; ".join(parts)
