"""The seam holds only while nothing routes around it.

`engine.py` exists so the driver can be swapped by changing one file plus
`browser.py`. That property is not visible in any single diff -- one `from
selenium...` added to an op looks harmless in review and silently puts the
coupling back. These tests are what make it visible.

No browser required: all of this is import-graph and table shape.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from abt import engine

SRC = Path(__file__).resolve().parents[1] / "src" / "abt"

# The two files allowed to name the driver library. `engine` is the seam itself;
# `browser` owns the driver object, launches it and holds its lifecycle.
DRIVER_OWNERS = {"engine.py", "browser.py"}


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


def test_only_the_driver_owners_import_selenium():
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(
            name for name in _imports(path) if name.split(".")[0] == "selenium"
        )
        for path in _modules()
        if path.name not in DRIVER_OWNERS
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, (
        "these modules import the driver library directly instead of going "
        f"through abt.engine: {offenders}"
    )


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


def test_keys_table_is_derived_not_typed():
    """The accepted key spellings must stay exactly what the driver offers.

    Written by hand this table lost 44 of its 73 entries and changed
    `arrow_down` to `arrowdown`, which would have broken every caller sending a
    named arrow key while looking like a tidy-up.
    """
    from selenium.webdriver.common.keys import Keys

    expected = {
        name.lower(): getattr(Keys, name)
        for name in dir(Keys)
        if name.isupper() and not name.startswith("_")
    }
    assert engine.KEYS == expected
    # Spellings that only a derived table has.
    for spelling in ("arrow_down", "page_down", "f12", "numpad0", "semicolon"):
        assert spelling in engine.KEYS, spelling


def test_every_modifier_is_also_a_key():
    """A chord's modifier has to be sendable on its own, or the chord cannot be
    assembled. Nothing enforced that while the two tables lived apart."""
    values = set(engine.KEYS.values())
    unknown = {n: v for n, v in engine.MODIFIERS.items() if v not in values}
    assert unknown == {}


def test_locator_strategies_match_the_wire_strings():
    """`By` is a rename, and stops being one the moment a value drifts."""
    from selenium.webdriver.common.by import By as SeleniumBy

    assert engine.By.CSS == SeleniumBy.CSS_SELECTOR
    assert engine.By.XPATH == SeleniumBy.XPATH
    assert engine.By.TAG == SeleniumBy.TAG_NAME


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
        if not n.startswith("_") and n not in {"annotations"}
    }
    # Names re-exported under their driver spelling are deliberately not public
    # API of the seam; the neutral alias beside each is what callers use.
    driver_spellings = {
        n for n in public if n.endswith("Exception")
    }
    assert public - driver_spellings - set(engine.__all__) == set()
