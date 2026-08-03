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

    # Subclasses set this to False when "no target" means "the whole document".
    target_required: ClassVar[bool] = True

    @model_validator(mode="after")
    def _exactly_one_target(self):
        given = [f for f in TARGET_FIELDS if getattr(self, f) is not None]
        if len(given) > 1:
            raise ValueError(f"supply only one of {', '.join(TARGET_FIELDS)}, got {given}")
        if not given and self.target_required:
            raise ValueError(f"one of {', '.join(TARGET_FIELDS)} is required")
        return self

    @property
    def has_target(self) -> bool:
        return any(getattr(self, f) is not None for f in TARGET_FIELDS)


class OptionalTarget(Target):
    target_required: ClassVar[bool] = False


# --- navigation ---------------------------------------------------------------


class Goto(Base):
    op: Literal["goto"]
    url: str


class Back(Base):
    op: Literal["back"]


class Forward(Base):
    op: Literal["forward"]


class Reload(Base):
    op: Literal["reload"]


class CurrentUrl(Base):
    op: Literal["current_url"]


# --- reading ------------------------------------------------------------------


class GetHtml(OptionalTarget):
    op: Literal["get_html"]


class GetText(OptionalTarget):
    op: Literal["get_text"]


class Find(Target):
    op: Literal["find"]
    mode: Literal["shell", "full"] = "shell"
    limit: int = Field(default=100, ge=1, le=1000)
    visible_only: bool = False


class FindFull(Target):
    op: Literal["find_full"]
    limit: int = Field(default=100, ge=1, le=1000)
    visible_only: bool = False


class Screenshot(OptionalTarget):
    op: Literal["screenshot"]


# --- interaction --------------------------------------------------------------


class Click(Target):
    op: Literal["click"]
    force: bool = False
    new_tab: bool = False
    activate: bool = True

    @model_validator(mode="after")
    def _force_xor_new_tab(self):
        if self.force and self.new_tab:
            raise ValueError(
                "force and new_tab are mutually exclusive; new_tab opens the href "
                "directly and never dispatches a click"
            )
        return self


class Input(Target):
    op: Literal["input"]
    value: str
    clear: bool = True


class Select(Target):
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


class Hover(Target):
    op: Literal["hover"]


class Scroll(OptionalTarget):
    op: Literal["scroll"]
    y: int | None = None

    @model_validator(mode="after")
    def _target_or_y(self):
        if self.has_target and self.y is not None:
            raise ValueError("supply a target or y, not both")
        if not self.has_target and self.y is None:
            raise ValueError("supply a target or y")
        return self


class WaitFor(Target):
    op: Literal["wait_for"]
    state: Literal["present", "visible", "clickable", "absent"] = "visible"
    timeout: float = Field(default=10.0, gt=0, le=300)


class Press(OptionalTarget):
    op: Literal["press"]
    key: str


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


class RunJs(Base):
    op: Literal["run_js"]
    script: str
    args: list[Any] = Field(default_factory=list)


class Status(Base):
    op: Literal["status"]


class Shutdown(Base):
    op: Literal["shutdown"]


Command = Annotated[
    Union[
        Goto, Back, Forward, Reload, CurrentUrl,
        GetHtml, GetText, Find, FindFull, Screenshot,
        Click, Input, Select, Hover, Scroll, WaitFor, Press,
        TabNew, TabList, TabSwitch, TabClose,
        RunJs, Status, Shutdown,
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
