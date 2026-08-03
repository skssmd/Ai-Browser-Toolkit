"""Schema validation runs before the browser is touched, so it needs no driver."""

from __future__ import annotations

import pytest

from abt.errors import OpError
from abt.schema import OP_NAMES, parse_command


def test_every_op_has_a_handler():
    from abt.ops import REGISTRY

    assert sorted(REGISTRY) == OP_NAMES


def test_parses_a_valid_command():
    cmd = parse_command({"op": "goto", "url": "https://example.com"})
    assert cmd.op == "goto"
    assert cmd.url == "https://example.com"


def test_defaults_are_applied():
    cmd = parse_command({"op": "find", "css": ".card"})
    assert cmd.mode == "shell"
    assert cmd.limit == 100
    assert cmd.visible_only is False


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ("not a dict", "must be an object"),
        ({}, "missing the 'op' field"),
        ({"op": "teleport"}, "unknown op"),
        ({"op": "goto"}, "url"),
        ({"op": "find"}, "is required"),
        ({"op": "find", "css": ".a", "xpath": "//a"}, "only one of"),
        ({"op": "click", "css": ".a", "bogus": 1}, "bogus"),
        ({"op": "select", "css": "#s"}, "exactly one of"),
        ({"op": "select", "css": "#s", "value": "a", "option_index": 1}, "exactly one"),
        ({"op": "scroll"}, "target or y"),
        ({"op": "scroll", "css": ".a", "y": 10}, "not both"),
        ({"op": "find", "css": ".a", "limit": 0}, "limit"),
    ],
)
def test_rejects_bad_input(payload, fragment):
    with pytest.raises(OpError) as caught:
        parse_command(payload)
    assert caught.value.type == "invalid_op"
    assert fragment in caught.value.message


def test_optional_target_ops_allow_no_target():
    for op in ("get_html", "get_text", "screenshot"):
        assert parse_command({"op": op}).has_target is False


def test_target_required_ops_reject_no_target():
    for op in ("click", "hover", "find"):
        with pytest.raises(OpError):
            parse_command({"op": op})
