# Parked work

Things deliberately deferred, with enough context to pick them up cold.

## Packaged application + installer

**Status:** partly done. The always-on logon entry -- the piece this was
mostly wanted for -- shipped 2026-08-20 as `abt autostart`, which writes a
Task Scheduler task, a launchd agent or a systemd user unit and is opt in.
What remains is *distribution*: an installer and the package-manager channels.

The prerequisite named below is met: the server starts without a browser.

Wanted: ship the toolkit as an installable Windows application rather than a
`.venv` plus two shell scripts.

**Direction chosen 2026-08-20:** a single installer carrying an embedded
Python, not a one-file binary. PyInstaller's sharp edge here is Playwright's
Node driver, which it locates at runtime; an installer with a real
`site-packages` has no such problem, so *both* engines survive packaging
rather than the binary being Selenium-only. It also suits winget, which wants
an installer rather than a bare executable.

Distribution can reuse the pipeline already proven in the Graft repo -- the
Homebrew tap, `AUR_SSH_KEY` and the winget fork all exist. The one step that
does not transfer is the build: GoReleaser's `builds:` is Go-only, and the
`prebuilt` builder that would consume PyInstaller output is Pro. Replace that
step with a PyInstaller matrix plus the dedicated publisher actions
(`KSXGitHub/github-actions-deploy-aur`, `vedantmgoyal9/winget-releaser`) and
the rest of the shape carries over.

Worth knowing before wiring signing: the Graft workflow imports a GPG key and
installs cosign and syft, but its `.goreleaser.yaml` has no `signs:`,
`signature:` or `sboms:` block -- so none of them sign anything today, and
`checksums.txt` is the only integrity artifact. PyPI has not accepted GPG
signatures since 2023; that is Trusted Publishing (OIDC) now.

Shapes considered for the installer itself:

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
