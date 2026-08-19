"""What to launch: the parameters that describe the browser process itself.

Kept apart from the rest of BrowserSession's settings deliberately.
`action_timeout`, the diff budget and the settle windows are *behaviour* knobs
that hold no matter which browser is up; these three describe the *process*.
Keeping that line sharp is what stops `POST /browser/start` from accreting into
a second copy of `abt serve`'s twenty-flag list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import OpError

SUPPORTED_BROWSERS = ("chrome", "edge")


@dataclass(frozen=True)
class LaunchConfig:
    browser: str = "chrome"
    profile: Path = Path("./profile")
    headless: bool = False

    def __post_init__(self) -> None:
        browser = str(self.browser).strip().lower()
        if browser not in SUPPORTED_BROWSERS:
            raise OpError(
                "bad_browser",
                f"unsupported browser {self.browser!r}; "
                f"choose from {', '.join(SUPPORTED_BROWSERS)}",
            )
        # A frozen dataclass still gets to normalise itself during __post_init__;
        # object.__setattr__ is the sanctioned way in.
        object.__setattr__(self, "browser", browser)
        object.__setattr__(self, "profile", Path(self.profile).expanduser().resolve())

    def merge(
        self,
        browser: str | None = None,
        profile: Path | str | None = None,
        headless: bool | None = None,
    ) -> "LaunchConfig":
        """This config with only the supplied fields replaced.

        `None` means keep, which is why `headless` is compared against None
        rather than tested for truth -- `headless=False` is a caller asking for
        a window, not a caller saying nothing.
        """
        return LaunchConfig(
            browser=self.browser if browser is None else browser,
            profile=self.profile if profile is None else profile,
            headless=self.headless if headless is None else headless,
        )

    def to_dict(self) -> dict:
        return {
            "browser": self.browser,
            "profile": str(self.profile),
            "headless": self.headless,
        }
