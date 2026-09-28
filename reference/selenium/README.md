# Selenium engine (retired, reference only)

The toolkit ran on Selenium first and moved to Playwright
([docs/playwright-spike-2026-08-19.md](../../docs/playwright-spike-2026-08-19.md)).
As of 0.7.0 Selenium is gone from the product: it is not a dependency, not
bundled, not imported, and `--engine selenium` is refused. Nothing in `src/`,
`tests/` or the packaging points here.

This folder keeps the Selenium code so it can be looked up, or attached again,
without digging through git history. It lives outside `src/`, so the wheel,
the bundles and the installer never carry it.

| File | What it was |
|---|---|
| `engine.py` | `src/abt/engine.py` when it re-exported Selenium's exceptions, key codes, `WebDriverWait`, `expected_conditions`, `ActionChains` and `Select`. |
| `browser_launch.py` | The Selenium half of `BrowserSession`: `webdriver.Chrome`/`Edge` and the launch options. |

## What replaced it

`src/abt/engine.py` now defines the same names natively: its own exception
classes (same names, same roles), the key table frozen as the same private-use
codepoints Selenium used, and a small `WebDriverWait` plus the three
conditions the page layer needs. The Playwright driver (`pwdriver.py`) already
spoke that vocabulary, so nothing above the engine changed.

## Re-attaching it

1. Add `selenium>=4.20` back to `dependencies` (or as an extra) in
   `pyproject.toml`.
2. Accept `"selenium"` again in `BrowserSession.__init__` and in the
   `--engine` options of `abt serve` / `abt run` (and `tests/conftest.py`).
3. In `BrowserSession._launch_driver`, fall through to
   `browser_launch.launch_driver(config)` when the engine is Selenium.
4. Make Selenium's exceptions count as ours. The simplest route is the one
   `engine.py` here took: alias the engine names to Selenium's classes. The
   key codes need no change -- they are identical.
5. `engine.ActionChains` / `engine.Select`: return Selenium's own classes for a
   Selenium driver, as the reference `engine.py` does.
6. Run the suite with `--engine selenium`.
