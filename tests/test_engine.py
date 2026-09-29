"""The seam holds only while nothing routes around it.

`engine.py` is the one vocabulary the page layer uses for driver failures, keys
and waits. Selenium is retired: it is not a dependency and nothing may import
it, or point at the reference copy kept in `reference/selenium/`. That is not
visible in any single diff -- one `from selenium...` added to an op looks
harmless in review and breaks every install. These tests make it visible.

No browser required: all of this is import-graph and table shape.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from abt import engine

SRC = Path(__file__).resolve().parents[1] / "src" / "abt"

# The files that name the driver library (Playwright) directly: the driver
# itself, and the few that open a raw connection for what it cannot do.
DRIVER_OWNERS = {"engine.py", "browser.py", "pwdriver.py"}


def _modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _imports(path: Path) -> set[str]:
    """Every module name imported, from the AST rather than the text.

    A regex over the source would also match the word in a comment or a
    docstring -- and `ops.interact` legitimately has one explaining what the
    driver raises. Parsing means only real imports count.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_nothing_imports_selenium():
    """Selenium is retired and not installed; one import breaks every install."""
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(
            name for name in _imports(path) if name.split(".")[0] == "selenium"
        )
        for path in _modules()
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, f"these modules import selenium: {offenders}"


def test_nothing_points_at_the_selenium_reference():
    """`reference/selenium/` is for reading, not for importing or loading."""
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in _modules()
        if "reference/selenium" in path.read_text("utf-8").replace("\\", "/")
        and path.name != "engine.py"  # its docstring says where the copy is
    ]
    assert offenders == []


def test_selenium_is_not_a_dependency():
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text("utf-8")
    assert '"selenium' not in pyproject


def test_the_seam_actually_covers_something():
    """Guard against the previous test passing because the seam went unused.

    Deleting `engine.py` and every import of it would satisfy "nothing imports
    selenium outside the owners" trivially and wrongly.
    """
    users = [
        path.relative_to(SRC).as_posix()
        for path in _modules()
        if path.name not in DRIVER_OWNERS
        and any(mod.endswith("engine") for mod in _imports(path))
    ]
    # Relative imports do not appear above (level > 0), so check the text for
    # those, which is safe here because we only care that the count is nonzero.
    relative = [
        path.relative_to(SRC).as_posix()
        for path in _modules()
        if path.name not in DRIVER_OWNERS and "engine import" in path.read_text("utf-8")
    ]
    assert len(set(users) | set(relative)) >= 8


def test_keys_table_is_the_frozen_webdriver_table():
    """The accepted key spellings must stay exactly what they always were.

    The table was frozen from Selenium's `Keys` when it was retired. Written by
    hand, an earlier version lost 44 of its 73 entries and changed
    `arrow_down` to `arrowdown`, which would have broken every caller sending a
    named arrow key while looking like a tidy-up.
    """
    assert len(engine.KEYS) == 73
    pinned = {
        "arrow_down": "\ue015",
        "page_down": "\ue00f",
        "f12": "\ue03c",
        "numpad0": "\ue01a",
        "semicolon": "\ue018",
        "control": "\ue009",
        "meta": "\ue03d",
        "enter": "\ue007",
    }
    assert {k: engine.KEYS[k] for k in pinned} == pinned


def test_every_modifier_is_also_a_key():
    """A chord's modifier has to be sendable on its own, or the chord cannot be
    assembled. Nothing enforced that while the two tables lived apart."""
    values = set(engine.KEYS.values())
    unknown = {n: v for n, v in engine.MODIFIERS.items() if v not in values}
    assert unknown == {}


def test_locator_strategies_match_the_wire_strings():
    """`pwdriver` translates these exact strings; a drifted value matches nothing."""
    assert engine.By.CSS == "css selector"
    assert engine.By.XPATH == "xpath"
    assert engine.By.TAG == "tag name"


def test_the_wait_polls_ignores_misses_and_times_out():
    calls = []

    def condition(_driver):
        calls.append(1)
        if len(calls) < 3:
            raise engine.NoSuchElement("not yet")
        return "found"

    assert engine.WebDriverWait(None, 5, poll_frequency=0.01).until(condition) == "found"
    with pytest.raises(engine.Timeout):
        engine.WebDriverWait(None, 0.05, poll_frequency=0.01).until(lambda d: False)


def test_engine_errors_keep_their_message():
    exc = engine.NoSuchElement("nothing matched '#x'")
    assert exc.msg == "nothing matched '#x'" and str(exc) == "nothing matched '#x'"


def test_engine_errors_are_all_catchable_as_one():
    """`except EngineError` is the seam's promise that one clause catches any
    driver failure. It only holds while every listed type inherits from it."""
    stray = [e.__name__ for e in engine.ENGINE_ERRORS if not issubclass(e, engine.EngineError)]
    assert stray == []


@pytest.mark.parametrize("name", engine.__all__)
def test_exported_names_exist(name):
    assert hasattr(engine, name)


def test_nothing_public_is_missing_from_all():
    """`__all__` is the port's checklist. A name used by the page layer but
    absent from it is one the port can forget to provide."""
    public = {
        n
        for n in vars(engine)
        if not n.startswith("_")
        and n not in {"annotations", "time", "Any", "Callable", "POLL_SECONDS"}
    }
    # Names re-exported under their driver spelling are deliberately not public
    # API of the seam; the neutral alias beside each is what callers use.
    driver_spellings = {
        n for n in public if n.endswith("Exception")
    }
    assert public - driver_spellings - set(engine.__all__) == set()


def test_keys_reach_playwright_under_names_it_accepts():
    """Several names share a key; the one Playwright is sent must be its own.

    Reordering the key table once sent "BackSpace" (from `back_space`), which
    Playwright rejects, and every chord that used it failed.
    """
    from abt.pwdriver import _playwright_key

    expected = {
        "backspace": "Backspace",
        "arrow_down": "ArrowDown",
        "down": "ArrowDown",
        "control": "Control",
        "left_control": "Control",
        "shift": "Shift",
        "left_shift": "Shift",
        "alt": "Alt",
        "meta": "Meta",
        "enter": "Enter",
        "return": "Return",
        "delete": "Delete",
        "page_down": "PageDown",
        "escape": "Escape",
        "tab": "Tab",
    }
    assert {k: _playwright_key(engine.KEYS[k]) for k in expected} == expected
