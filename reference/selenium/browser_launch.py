"""Reference only: how `BrowserSession` launched a Selenium-driven browser.

Nothing imports this file. It is the Selenium half of `src/abt/browser.py` as
it stood before the Selenium engine was retired (0.7.0), kept so the engine can
be re-attached without archaeology. See README.md in this folder.

In the live code, `BrowserSession._launch_driver` ended with the fallback below
once the Playwright branch had returned, and `stop`, `health_check` and friends
caught `selenium.common.exceptions.WebDriverException` where they now catch
`abt.engine.EngineError`.
"""

from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions


def launch_driver(config):
    """What `_launch_driver` did for `engine="selenium"`."""
    options = make_options(config)
    if config.browser == "edge":
        return webdriver.Edge(options=options)
    return webdriver.Chrome(options=options)


def make_options(config):
    """`BrowserSession._make_options`, verbatim."""
    if config.browser == "edge":
        options = EdgeOptions()
    else:
        options = ChromeOptions()
    options.add_argument(f"--user-data-dir={config.profile}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    if config.headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,900")
    return options
