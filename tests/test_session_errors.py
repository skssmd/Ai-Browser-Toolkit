"""The session error types exist and each says what to do."""

from __future__ import annotations

import pytest

from abt.errors import ERROR_TYPES, OpError

NEW = (
    "unknown_session",
    "session_exists",
    "session_sealed",
    "tab_locked",
    "profile_limit",
    "profile_in_use",
    "profile_not_found",
)


@pytest.mark.parametrize("kind", NEW)
def test_each_session_error_has_a_hint(kind):
    assert kind in ERROR_TYPES
    assert OpError(kind, "x").hint
