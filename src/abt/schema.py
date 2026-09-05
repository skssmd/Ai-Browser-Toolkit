"""Pydantic models for every command. Validation happens before the browser is touched."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import OpError

# What names an element by describing it. At most one may be given.
SELECTOR_FIELDS = ("css", "xpath", "text")
# Every way of naming a target. `level` is here so "some target was given"
# still counts it, but it is a place rather than a description, so it is
# allowed alongside a selector to scope it -- see `_exactly_one_target`.
TARGET_FIELDS = SELECTOR_FIELDS + ("level",)


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Base):
    """Targeting fields shared by every op that acts on an element."""

    css: str | None = None
    xpath: str | None = None
    text: str | None = None
    # The address the text track prints. A selector names an element by what it
    # is; a level names one by where it sits -- and since a control's line now
    # carries its own address, the thing you just read is the thing you act on
    # without a search in between. Everything after a `#` is a label the reader
    # is meant to see and the resolver ignores.
    level: str | None = None
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
        # A level is a place, not a description, so it is the one target that
        # combines: `level` says where to look and a selector says what to look
        # for in there. Neither answers "the price in *this* row" alone -- the
        # selector matches the whole page, the level brings back everything
        # under it. Two selectors together still make no sense and are still
        # refused.
        selectors = [f for f in SELECTOR_FIELDS if getattr(self, f) is not None]
        if len(selectors) > 1:
            raise ValueError(
                f"supply only one of {', '.join(SELECTOR_FIELDS)}, got {selectors}"
            )
        if not given and self.target_required:
            raise ValueError(f"one of {', '.join(TARGET_FIELDS)} is required")
        if self.near is not None and not given:
            # Silently the most expensive mistake here. On an op where no
            # target means "the whole document", `near` alone used to fall
            # through to that branch: an agent asking for the HTML *near*
            # something was handed the entire page instead -- measured at
            # 127,941 bytes, more than asking for `body` outright, with no
            # error to say the qualifier had been ignored.
            raise ValueError(
                "near qualifies a selector, it is not one: give css, xpath or "
                "text as well, or drop near to read the whole document"
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

    """

    diff: bool | None = None
    include_removed: bool = False
    element_diff: bool = False
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
    """Visible text, laid out as the tree it sits in.

    `level` reads one subtree by the path the text track already prints -- the
    same "AEDBAAAB" that labelled those strings when you last saw them. It is
    how you look at what a navigation reported as unchanged: the page told you
    where the table was, and asking for that level again brings it back without
    the rest of the document coming with it.

    Not a selector, so it does not compete with css/xpath/text: those name an
    element by what it is, `level` names one by where it sits -- which is why
    the two combine. Give both and the level scopes the selector: `level` says
    where to look, `css` says what to look for in there. Neither answers "the
    price in *this* row" alone.
    """

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
        if self.shadow and self.xpath is not None:
            raise ValueError(
                "shadow search takes css or text; xpath cannot cross a shadow "
                "boundary"
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


class BrowserOpenManual(Base):
    """Launch a plain, non-automated browser on the same profile.

    For sites (Google among them) that block a Selenium/CDP-controlled
    browser at sign-in regardless of anti-detection flags. No `headless`: a
    manual login needs a visible window. abt's own browser must not be
    running on this profile -- stop it first.
    """

    op: Literal["browser_open_manual"]
    browser: str | None = None
    profile: str | None = None



class GuidelinesSearch(Base):
    """Is there a written playbook for this site?

    Ask before driving somewhere unfamiliar. An empty result is an answer --
    most sites have no playbook, and that means the workflow document is all
    there is. It does not mean search again differently.
    """

    op: Literal["guidelines_search"]
    query: str
    """A domain, or anything domain-ish. Fuzzy: `sheets` finds docs.google.com."""
    limit: int = Field(default=8, ge=1, le=50)


class GuidelinesRead(Base):
    """One playbook in full, by the name a search returned."""

    op: Literal["guidelines_read"]
    name: str
    """`domain/file.md` for a site playbook, or a bare stem like
    `toolkit-workflow` for a general one."""


class GuidelinesNote(Base):
    """Append what you had to work out, so the next run starts ahead.

    Write one only when a site genuinely fought you and you won. The four
    fields are all required because an entry missing any of them cannot be
    acted on by the next reader: without the URL they do not know where it
    applies, without `tried` they repeat your dead ends.

    Saved locally. A pull never overwrites it, and it is not shared anywhere
    -- contributing upstream is a separate, deliberate step.
    """

    op: Literal["guidelines_note"]
    domain: str
    """Site the note is about, e.g. `shop.example.com`."""
    title: str
    """One line naming the problem, as the next reader would recognise it."""
    url: str
    """Where it happened, so a reader knows the scope."""
    problem: str
    """What happened, in the terms you first saw it."""
    tried: str
    """What you tried and what it taught you. Name dead ends as dead ends --
    that is as useful as the fix."""
    solution: str
    """What worked, concretely enough to run."""
    replaces: str | None = None
    """Title of an existing entry this one supersedes, copied exactly.

    Use it when you find an entry here is wrong or has been overtaken, rather
    than appending a second entry that argues with the first -- a reader who
    meets both cannot tell which one won. That entry is cut and yours takes
    its place; every other entry is untouched. Leave it unset for anything
    new."""

Command = Annotated[
    Union[
        Goto, Back, Forward, Reload, CurrentUrl,
        GetHtml, GetText, Find, FindFull, Screenshot,
        Click, Input, Select, Hover, Scroll, WaitFor, Press,
        TabNew, TabList, TabSwitch, TabClose,
        RunJs, Diff, Status, Shutdown, Alert,
        ReadConsole, ReadNetwork,
        GuidelinesSearch, GuidelinesRead, GuidelinesNote,
        BrowserStart, BrowserStop, BrowserRestart, BrowserStatus,
        BrowserOpenManual,
    ],
    Field(discriminator="op"),
]


class _Wrapper(BaseModel):
    command: Command


COMMAND_MODELS = get_args(get_args(Command)[0])

OP_NAMES = sorted(
    get_args(m.model_fields["op"].annotation)[0] for m in COMMAND_MODELS
)


def op_signatures() -> dict[str, dict]:
    """Every op with its parameters, their types and their defaults.

    The names were all `/ops` and `abt ops` ever returned, while both claimed
    to print "every op and its exact parameters". A caller that believed them
    -- and the CLI's own help says it, so callers do -- had to guess parameter
    names, and guessed `js` for `script`, `selector` and `pattern` for `css`,
    `x`/`y` on a click. Five of those in one benchmark session, all of them
    unnecessary: the models below have carried the answer the whole time.

    Derived from the pydantic models rather than written down, so it cannot
    drift from what the server will actually accept.
    """
    signatures: dict[str, dict] = {}
    for model in COMMAND_MODELS:
        name = get_args(model.model_fields["op"].annotation)[0]
        params = {}
        for field, info in model.model_fields.items():
            if field == "op":
                continue
            entry: dict[str, Any] = {
                "type": _type_name(info.annotation),
                "required": info.is_required(),
            }
            default = info.default
            # PydanticUndefined is not JSON-serialisable and means "no default".
            if not info.is_required() and default is not None and repr(default) != "PydanticUndefined":
                entry["default"] = default
            if info.description:
                entry["doc"] = info.description
            params[field] = entry
        signatures[name] = params
    return signatures


def _type_name(annotation: Any) -> str:
    """A short, readable type for a parameter -- not a JSON Schema."""
    text = str(annotation)
    for noise in ("typing.", "<class '", "'>", "abt.schema."):
        text = text.replace(noise, "")
    text = text.replace("Optional[", "").replace("Union[", "")
    text = text.replace(" | None", "").rstrip("]")
    # Literals carry the allowed values, which is the useful part.
    if "Literal[" in text:
        return text[text.index("Literal[") :].replace("Literal[", "one of ")
    return text.split(",")[0].strip() or "any"


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
