"""The login entry, decided without installing one.

`plan()` is pure on purpose: the three mechanisms are one shape, and the part
that is easy to get wrong -- the command line and the paths inside it -- can
then be checked for all three platforms from whichever one the tests run on.
The installing half touches Task Scheduler, launchd or systemd and is not
exercised here; there is nothing to assert about it that would not amount to
testing those tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from abt import autostart


KINDS = ("windows", "macos", "linux")


def make(kind: str, tmp_path: Path, **kw):
    defaults = dict(
        port=8765,
        browser="chrome",
        profile=tmp_path / "profile",
        log_dir=tmp_path / "logs",
        kind=kind,
        exe="/opt/abt/bin/abt",
        home=tmp_path / "home",
    )
    defaults.update(kw)
    return autostart.plan(**defaults)


@pytest.mark.parametrize("kind", KINDS)
def test_the_browser_is_named_and_never_prompted_for(kind, tmp_path):
    """`abt serve` prompts when --browser is missing and stdin is a tty.

    A logon entry gets a console on Windows, so it prompts -- and then waits
    forever with nobody to answer, leaving one line in the log reading
    "Select browser to use [chrome]:". Observed while launching the server
    detached during this project, which is why it is asserted rather than
    trusted.
    """
    argv = make(kind, tmp_path).argv
    assert "--browser" in argv
    assert argv[argv.index("--browser") + 1] == "chrome"


@pytest.mark.parametrize("kind", KINDS)
def test_no_browser_is_launched_at_login(kind, tmp_path):
    """The entire feature is only sane because the server starts browserless.

    With --start-browser it would open Chrome on the persistent profile at
    every logon, which costs about two minutes of every boot.
    """
    assert "--start-browser" not in make(kind, tmp_path).argv


@pytest.mark.parametrize("kind", KINDS)
def test_every_path_is_absolute(kind, tmp_path):
    """A logon entry has no working directory worth resolving against.

    A relative ./profiles/default would resolve against the launcher's cwd --
    on Windows that is C:\Windows\System32 -- so the server would build a
    that is C:\\Windows\\System32 -- so the server would build a second, empty
    profile there and none of the logins would be in it.
    """
    argv = make(kind, tmp_path).argv
    for flag in ("--profile", "--log-dir"):
        value = Path(argv[argv.index(flag) + 1])
        assert value.is_absolute(), f"{flag} is relative: {value}"


@pytest.mark.parametrize("kind", KINDS)
def test_the_interpreter_is_a_path_not_a_bare_name(kind, tmp_path):
    """`abt` alone would be resolved against the logon session's PATH, which
    does not have the venv on it. It has to be the full path to the thing.

    Asserted as "contains a separator" rather than `Path.is_absolute()`,
    because the plan is built for all three platforms from whichever one is
    running the tests -- and to a WindowsPath, `/opt/abt/bin/abt` is not
    absolute for want of a drive letter. The invariant that matters is that
    nothing here is looked up on PATH.
    """
    exe = make(kind, tmp_path).argv[0]
    assert "/" in exe or "\\" in exe, exe


def test_a_source_checkout_names_the_module(tmp_path):
    """Without an installed console script there is no `abt` to run, so the
    interpreter has to be told what to import."""
    argv = make("linux", tmp_path, exe="/usr/bin/python3.11").argv
    assert argv[1:3] == ["-m", "abt.cli"]


def test_an_installed_script_does_not(tmp_path):
    argv = make("linux", tmp_path, exe="/opt/abt/bin/abt").argv
    assert "-m" not in argv


@pytest.mark.parametrize("kind", KINDS)
def test_the_engine_is_recorded(kind, tmp_path):
    """Whichever engine you chose is the one that comes back after a reboot."""
    argv = make(kind, tmp_path, engine="playwright").argv
    assert argv[argv.index("--engine") + 1] == "playwright"


def test_the_unit_files_land_where_the_platform_looks(tmp_path):
    home = tmp_path / "home"
    mac = make("macos", tmp_path).path
    lin = make("linux", tmp_path).path
    assert mac == home / "Library" / "LaunchAgents" / f"{autostart.MACOS_LABEL}.plist"
    assert lin == home / ".config" / "systemd" / "user" / autostart.LINUX_UNIT


def test_windows_has_no_file_because_the_task_store_is_not_one(tmp_path):
    spec = make("windows", tmp_path)
    assert spec.path is None
    assert spec.content and "cmd.exe" in spec.content


def test_windows_reads_stdin_from_nul(tmp_path):
    """The other half of the prompt problem: a task gets a console, so stdin
    has to be closed as well as --browser being passed."""
    assert "< NUL" in (make("windows", tmp_path).content or "")


def test_the_plist_is_well_formed_and_starts_at_load(tmp_path):
    import plistlib

    content = make("macos", tmp_path).content or ""
    parsed = plistlib.loads(content.encode("utf-8"))
    assert parsed["Label"] == autostart.MACOS_LABEL
    assert parsed["RunAtLoad"] is True
    assert parsed["KeepAlive"] is True
    assert parsed["ProgramArguments"][0].endswith("abt")


def test_the_unit_restarts_on_failure_but_not_on_a_clean_stop(tmp_path):
    unit = make("linux", tmp_path).content or ""
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit


def test_a_path_with_spaces_survives_the_unit_file(tmp_path):
    """systemd's ExecStart splits on spaces, so an unquoted Program Files path
    becomes two arguments and the unit fails to start."""
    spec = make("linux", tmp_path, exe="/opt/my apps/abt")
    line = next(
        row for row in (spec.content or "").splitlines() if row.startswith("ExecStart=")
    )
    assert '"/opt/my apps/abt"' in line


def test_linux_says_how_to_survive_a_logout(tmp_path):
    """A user unit stops at logout, which is a surprise for something called
    autostart. The remedy belongs with the thing, not in a wiki."""
    assert any("linger" in note for note in make("linux", tmp_path).notes)


def test_an_unsupported_platform_says_so(tmp_path):
    with pytest.raises(autostart.AutostartError):
        make("plan9", tmp_path)
