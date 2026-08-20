"""Detached spawning. The platform-specific half is exercised by hand."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from abt import proc


def test_windows_command_line_quotes_paths_with_spaces(tmp_path):
    out = tmp_path / "a b" / "server.log"
    err = tmp_path / "a b" / "server.err"
    line = proc.windows_command_line(
        [str(tmp_path / "a b" / "abt.exe"), "serve", "--port", "8765"], out, err
    )
    assert line.startswith("cmd.exe /c ")
    assert '"' in line
    assert str(out) in line
    assert "2>" in line
    # Without this the server prompts for a browser and hangs forever: WMI
    # gives the process a console, so serve believes someone is watching.
    assert "< NUL" in line


def test_powershell_quoting_doubles_single_quotes():
    assert proc.powershell_single_quote("it's") == "'it''s'"
    assert proc.powershell_single_quote("plain") == "'plain'"


def test_spawn_detached_reports_the_mechanism(tmp_path):
    """A real spawn of something harmless that exits on its own."""
    out = tmp_path / "out.log"
    err = tmp_path / "err.log"
    mechanism = proc.spawn_detached(
        [sys.executable, "-c", "print('hello')"], tmp_path, out, err
    )
    assert mechanism in {"wmi", "schtasks", "detached", "detached-in-job", "setsid"}


def test_spawn_detached_rejects_an_empty_command(tmp_path):
    with pytest.raises(ValueError):
        proc.spawn_detached([], tmp_path, tmp_path / "o", tmp_path / "e")


@pytest.mark.skipif(not proc.IS_WINDOWS, reason="job objects are a Windows concept")
def test_a_restrictive_job_object_still_leaves_a_way_to_spawn(tmp_path):
    """CREATE_BREAKAWAY_FROM_JOB does not degrade: when the job forbids
    breakaway, CreateProcess fails with access-denied instead of starting the
    process unescaped. Passing it alongside DETACHED_PROCESS therefore loses
    both, and the spawn that would have worked never happens.

    Observed on a GitHub Actions Windows runner, where every step runs inside
    a job object and all three mechanisms reported failure.
    """
    out = tmp_path / "out.log"
    err = tmp_path / "err.log"
    assert proc._popen_windows(
        [sys.executable, "-c", "print('hello')"], tmp_path, out, err, breakaway=False
    )


def test_the_in_job_fallback_is_last_and_named_apart():
    """It is worse than the others -- the process dies with the job, so a
    harness waiting on that job still blocks. Preferring it over WMI would
    quietly reintroduce the problem this module exists to solve, so the order
    is asserted rather than trusted.

    Not skipped off Windows: the ordering is a plain data structure, and it is
    worth catching a reordering on any machine that runs the suite.
    """
    names = [name for name, _ in proc._windows_attempts()]
    assert names[-1] == "detached-in-job"
    assert names.index("detached") < names.index("detached-in-job")
    assert names[0] == "wmi"
