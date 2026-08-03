"""XPath literal quoting has no escape character to lean on, so it gets its own test."""

from __future__ import annotations

from abt.targeting import xpath_literal


def test_plain_string():
    assert xpath_literal("hello") == "'hello'"


def test_string_with_apostrophe():
    assert xpath_literal("it's") == '"it\'s"'


def test_string_with_double_quote():
    assert xpath_literal('say "hi"') == "'say \"hi\"'"


def test_string_with_both_quotes():
    result = xpath_literal("he said \"it's fine\"")
    assert result.startswith("concat(")
    assert "\"'\"" in result
