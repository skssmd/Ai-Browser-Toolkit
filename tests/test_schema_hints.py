"""A guessed parameter name is answered with the real ones."""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.schema import parse_command


def test_a_guessed_parameter_lists_the_real_ones():
    """Seen live: `url_pattern`, then `timeout_ms`, on one wait_for."""
    with pytest.raises(OpError) as exc:
        parse_command({"op": "wait_for", "timeout_ms": 10000})
    message = exc.value.message
    assert "timeout_ms" in message
    assert "it takes:" in message and "timeout" in message.split("it takes:")[1]


def test_a_wrong_type_is_not_padded_with_the_list():
    with pytest.raises(OpError) as exc:
        parse_command({"op": "wait_for", "timeout": "soon"})
    assert "it takes:" not in exc.value.message
