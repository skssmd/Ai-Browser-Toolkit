# Parked work

Things deliberately deferred, with enough context to pick them up cold.

## Packaged application + installer

**Status:** parked 2026-08-19, before any code was written.

Wanted: ship the toolkit as an installable Windows application rather than a
`.venv` plus two shell scripts.

Shapes considered, none chosen yet:

* **Packaged CLI + installer, no GUI.** PyInstaller-bundle `abt` into a
  standalone `.exe` (no Python on the target machine), wrapped in an Inno Setup
  installer: installs to Program Files, puts `abt` on PATH, offers the opt-in
  autostart logon task as a checkbox, ships an uninstaller.
* **Tray app + installer.** The above plus a system-tray icon showing
  server-up/browser-up, with start/stop/restart-browser menu items and a link to
  the log viewer. Direct answer to "the browser died, where am I?".
* **Full desktop app.** Status, embedded session-log viewer, tab list, command
  console, config editor. Mostly duplicates the existing `/viewer` web UI.
* **pipx only.** `pipx install aibrowsertoolkit` plus an `abt autostart install`
  subcommand. No native installer, requires Python, cross-platform for free.

**Why it is parked behind the browser/server decoupling:** the opt-in always-on
logon task is the installer's most valuable feature, and it is only sane once
the server starts *without* launching a browser. Installed against the old
behaviour it would open Chrome on the persistent profile at every logon and cost
~2 minutes of every boot. Decoupling first is a prerequisite, not a preference.

**Decisions already made that this inherits:** `abt up` spawns the server via a
third party (Task Scheduler / WMI on Windows) so it lands outside the calling
agent's job object; the always-on logon task is opt-in, never installed by
default.
