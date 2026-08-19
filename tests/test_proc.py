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
    assert mechanism in {"wmi", "schtasks", "detached", "setsid"}


def test_spawn_detached_rejects_an_empty_command(tmp_path):
    with pytest.raises(ValueError):
        proc.spawn_detached([], tmp_path, tmp_path / "o", tmp_path / "e")
