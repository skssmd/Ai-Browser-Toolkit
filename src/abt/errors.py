"""The closed set of error types every command can fail with."""

from __future__ import annotations

ERROR_TYPES = frozenset(
    {
        "invalid_op",
        "element_not_found",
        "stale_ref",
        "not_interactable",
        "not_a_select",
        "timeout",
        "navigation_failed",
        "js_error",
        "last_tab",
        "tab_not_found",
        "browser_dead",
        "bad_browser",
    }
)


class OpError(Exception):
    """A command failure with a machine-branchable type."""

    def __init__(self, type: str, message: str) -> None:
        if type not in ERROR_TYPES:
            raise ValueError(f"unknown error type: {type}")
        super().__init__(message)
        self.type = type
        self.message = message

    def to_dict(self, op_index: int = 0) -> dict:
        return {"type": self.type, "message": self.message, "op_index": op_index}
