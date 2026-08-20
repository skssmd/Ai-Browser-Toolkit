# Packaging and Distribution — Design

Date: 2026-08-20
Status: Approved

## Purpose

The toolkit installs today by cloning a repo, creating a `.venv`, and running
one of two shell scripts. That is a developer's install. It cannot be typed
from memory, it leaves the program wherever the clone happened to land, and it
has no answer for someone who does not have Python.

This design ships the toolkit as an installable program on six channels —
PyPI, winget, a downloadable Windows installer, Scoop, a Homebrew tap, the AUR,
and a Gemfury apt/rpm/apk repository — from a single `v*` tag, with no manual
step between the tag and the last channel.

It also closes the loop on `abt autostart`, which shipped on 2026-08-20 but
which nothing currently offers to run. The Windows installer offers it as an
unchecked box; every other channel prints the command.

`docs/TODO.md` records the direction this follows and the reasoning behind it.
That entry is superseded by this document and should point here.

## Non-goals

- **A GUI or tray application.** `docs/TODO.md` lists a tray app and a full
  desktop app among the shapes considered. Neither is in scope. This ships the
  CLI that already exists, packaged.
- **Bundling a browser.** `pwdriver.py` drives the user's installed Chrome or
  Edge via `channel="chrome"`. No Chromium is downloaded and none is shipped.
- **Machine-scope installation.** Every install is per-user. See "Why per-user
  on Windows".
- **Snap, Nix and Chocolatey.** Wanted, deferred, and the reasons are recorded
  under "Wave 4".
- **Authenticode signing.** Deliberately out of the free-tier signing decision.
  Windows users will see a SmartScreen warning on the standalone installer.
- **Replacing the developer workflow.** `start-server.bat`, `start-server.sh`
  and an editable install keep working exactly as they do now.

## Decisions

Settled during brainstorming, recorded so the plan does not relitigate them:

| Decision | Choice |
|---|---|
| Bundle model | Self-contained bundles everywhere except PyPI, which stays a normal wheel. |
| Bundle mechanism | `uv venv --relocatable` over a python-build-standalone CPython. Not PyInstaller. |
| Build topology | Five native runners, one per target. Not a cross-build from one host. |
| Install scope | Per-user on every platform. Never elevated. |
| Autostart | Unchecked installer checkbox on Windows; a printed hint everywhere else. Never default-on. |
| Signing | Free tier only: PyPI OIDC, GitHub build provenance, `checksums.txt`. No GPG, no Authenticode. |
| Chrome dependency | `optdepends` / `Recommends`, never a hard dependency. |
| Homebrew tap | Reuse `the-graft-project/homebrew-tap`. |
| winget fork | Reuse `the-graft-project/winget-pkgs`. |
| Release ordering | The GitHub release is created first; all six publishers read from it. |

## What carries over from Graft, and what does not

The Graft repo already ships this shape: one tag, one workflow, fan-out to a
Homebrew tap, an AUR `-bin` package, a winget PR into `microsoft/winget-pkgs`
from a fork, and `.deb`/`.rpm`/`.apk` pushed to Gemfury. That topology is
proven and is reproduced here.

What does not carry over is the build. GoReleaser's `builds:` is Go-only, and
the `prebuilt` builder that would consume a Python bundle is a Pro feature. So
GoReleaser is not used at all; the build is a Python matrix and the fan-out is
the ecosystems' own publisher actions.

Two things worth knowing before copying Graft's workflow verbatim:

- Its workflow imports a GPG key and installs `cosign` and `syft`, but
  `.goreleaser.yaml` has no `signs:`, `signature:` or `sboms:` block. Nothing
  is signed there today and `checksums.txt` is the only integrity artifact.
  This design does not inherit that gap: build provenance is real and attested.
- PyPI has not accepted GPG signatures since 2023. Trusted Publishing is the
  mechanism now, and it involves no stored secret at all.

## Prerequisite: per-user data directories

`cli.py:87`, `cli.py:627` and `launch.py:23` default `--profile` to
`./profiles/default`, and `--log-dir` to `./logs`. Both are resolved against
the current working directory.

That is correct for a repo checkout and wrong for an installed program. Run
`abt serve` from a home directory and it silently builds a second, empty Chrome
profile there, containing none of the logins. Run it from a logon task and the
working directory is `C:\Windows\System32` — the exact failure
`autostart.py`'s module docstring already warns about.

A new `src/abt/paths.py` resolves both:

| | Windows | macOS | Linux |
|---|---|---|---|
| profile | `%LOCALAPPDATA%\AIBrowserToolkit\profiles\default` | `~/Library/Application Support/AIBrowserToolkit/profiles/default` | `$XDG_DATA_HOME/aibrowsertoolkit/profiles/default` |
| logs | `%LOCALAPPDATA%\AIBrowserToolkit\logs` | `~/Library/Logs/AIBrowserToolkit` | `$XDG_STATE_HOME/aibrowsertoolkit/logs` |

`$XDG_DATA_HOME` falls back to `~/.local/share` and `$XDG_STATE_HOME` to
`~/.local/state` when unset, per the XDG base directory specification.

**The development escape hatch.** If the current working directory contains a
`pyproject.toml` whose `[project] name` is `aibrowsertoolkit`, the old
cwd-relative `./profiles` and `./logs` are used instead. This is what keeps
`start-server.bat`, the existing `profiles/default` with its live logins, and
every current guideline working untouched. An installed copy never sees that
file and always gets the per-user location.

`--profile` and `--log-dir` continue to override everything.

## Artifact graph

One `v*` tag produces two kinds of build output. Every channel consumes one of
them and none of them builds anything.

```
tag v0.2.0
  |
  +-- wheel + sdist ---------------------> PyPI (pip / pipx)
  |
  +-- 5 x self-contained bundle            +-- winget (Inno .exe -> PR to microsoft/winget-pkgs)
      linux-x86_64  / linux-aarch64  --+   +-- standalone .exe on the GitHub release
      macos-arm64   / macos-x86_64    --+--+-- Scoop bucket (zip)
      windows-x86_64                  --+   +-- Homebrew tap (tarball)
                                            +-- AUR aibrowsertoolkit-bin (tarball)
                                            +-- nfpm -> .deb/.rpm/.apk -> Gemfury
```

This is the property that makes six channels cost roughly what two would: every
manifest points at bytes that were already built and smoke-tested once.

## Bundle layout

Identical on all five targets:

```
aibrowsertoolkit-0.2.0-linux-x86_64/
  venv/                       relocatable venv over python-build-standalone CPython 3.13
    bin/abt                   the console script, relative shebang
    lib/.../site-packages/    abt, playwright, selenium, fastapi, uvicorn, pydantic, httpx, typer
  LICENSE
  README.md
  guidelines/
```

`uv venv --relocatable` is what makes this work. It rewrites script shebangs
and the Windows launcher stubs to resolve relative to the venv, so the tree can
be moved into `/opt`, a Homebrew Cellar, or `%LOCALAPPDATA%` with no post-install
fixup and no path rewriting in any packaging script.

**Why not PyInstaller.** `onefile` extracts to a temporary directory and
Playwright locates its Node driver at runtime, which breaks — this is recorded
in `docs/TODO.md` and is why the one-file binary was rejected. `onedir` would
mostly work but reintroduces hidden-import guesswork for Typer, Pydantic and
uvicorn. A real `site-packages` has neither problem, and it is why **both
engines survive packaging** rather than the bundle being Selenium-only.

Approximate size: 55–70 MB per bundle, dominated by the Playwright wheel's
Node driver and the embedded CPython.

## Install locations

| Channel | Location | Entry point |
|---|---|---|
| Windows installer, winget | `%LOCALAPPDATA%\Programs\AIBrowserToolkit` | `venv\Scripts` added to the user `PATH` |
| Scoop | Scoop's own `apps` directory | Scoop shim to `venv\Scripts\abt.exe` |
| Homebrew | `libexec` in the Cellar | `bin.install_symlink libexec/"venv/bin/abt"` |
| AUR, deb, rpm, apk | `/opt/aibrowsertoolkit` | symlink at `/usr/bin/abt` |
| pip / pipx | the user's environment | whatever pip does |

### Why per-user on Windows

The toolkit's premise is a persistent per-user Chrome profile and a user-level
logon task — `autostart.py` is explicit that a system service would run as
another user and find none of the logins. A machine-scope install would put the
program in one account's reach and its state in another's.

Per-user install also means no UAC prompt during installation, and lets the
winget manifest declare `Scope: user`, which is what makes `winget install`
work without elevation.

## Channels

| Channel | Consumes | Target | Publisher |
|---|---|---|---|
| PyPI | wheel + sdist | `aibrowsertoolkit` | `pypa/gh-action-pypi-publish`, Trusted Publishing |
| Standalone installer | windows bundle | GitHub release asset | Inno Setup `iscc` on the Windows runner |
| winget | that same `.exe` | PR to `microsoft/winget-pkgs` | `vedantmgoyal9/winget-releaser` |
| Scoop | windows **zip** | `the-graft-project/scoop-bucket` | CI commits `bucket/aibrowsertoolkit.json` |
| Homebrew | macos arm64 + x86_64 tarballs | `the-graft-project/homebrew-tap` | CI regenerates `Formula/aibrowsertoolkit.rb` |
| AUR | linux x86_64 + aarch64 tarballs | `aibrowsertoolkit-bin` | `KSXGitHub/github-actions-deploy-aur` |
| deb/rpm/apk | linux tarballs | Gemfury | `nfpm pkg`, then `curl -F package=@…` |

Three details that are not boilerplate:

**Scoop takes the zip, winget takes the installer.** The same bundle is
packaged twice. Scoop manages its own shims and would fight an installer that
writes `PATH`. The winget manifest is `InstallerType: inno`, `Scope: user`,
silent switches `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`, package identifier
`skssmd.AIBrowserToolkit`.

**Chrome is `optdepends`, never `depends`.** A browser is required at runtime,
but Google Chrome is not in Arch's repositories or Debian's, and Edge counts
too. A hard dependency would make the package uninstallable on distributions
where the only Chrome is itself an AUR build. So: `optdepends` on Arch,
`Recommends:` on deb, and a clear runtime error from `abt` when neither browser
is found.

**Shared repositories need a retry.** The tap and the winget fork are also
written by Graft's release workflow. Two releases in the same minute would make
the second push a non-fast-forward rejection. Every push into a shared repo
does `pull --rebase` and retries twice.

## Autostart

`abt autostart install` and `abt autostart uninstall` already exist and are not
changed by this design. What changes is that something now offers to call them.

| Channel | Behaviour |
|---|---|
| Windows installer, winget | A `[Tasks]` entry, **unchecked**: "Start AI Browser Toolkit at logon". If checked, `[Run]` executes `abt autostart install --browser chrome`. |
| deb / rpm | `postinstall` prints the command. `prerm` runs `abt autostart uninstall`. |
| AUR | A `.install` file prints the command. `pre_remove` runs `abt autostart uninstall`. |
| Homebrew | A `caveats` block prints the command, and warns that uninstall will not remove the agent. |
| pip / pipx / Scoop | A first-run hint. |

The installer's `[UninstallRun]` executes `abt autostart uninstall` *before*
removing any files, so uninstalling can never leave a Task Scheduler entry
pointing at a deleted executable.

**Known gap: Homebrew has no uninstall hook.** `brew uninstall` will leave the
launchd agent in place, and it will fail at the next logon. The caveats block
must say so plainly. Nothing in Homebrew's design fixes this; a loud failure is
the better of the two available behaviours.

## Pipeline

Ordering is the part GoReleaser hides and this workflow must make explicit:
every downstream publisher needs a URL and a SHA256 of a file that is already
published, so the GitHub release is created before any fan-out.

```
test --> wheel --> bundle (5x native matrix, each smoke-tested)
                      |
                      +--> installer   (windows: iscc -> .exe)
                      +--> linux-pkgs  (nfpm: deb/rpm/apk, x86_64 + aarch64)
                                  |
                                  v
                    release  -- checksums.txt + attest-build-provenance
                                  |
        +--------+--------+-------+-------+--------+--------+
       pypi    winget   scoop    brew    aur     fury
```

The six terminal jobs have no interdependencies. One failing channel leaves the
other five shipped, and the fix is to re-run a single job rather than the
release.

### Runners

| Target | Runner |
|---|---|
| linux-x86_64 | `ubuntu-24.04` |
| linux-aarch64 | `ubuntu-24.04-arm` |
| macos-arm64 | `macos-14` |
| macos-x86_64 | `macos-13` |
| windows-x86_64 | `windows-latest` |

The ARM runners are free for public repositories. **If
`skssmd/Ai-Browser-Toolkit` is private, this is not available** and the
fallback is to build the two ARM targets with `uv pip install --python-platform
… --only-binary :all:` from their x86_64 counterparts, accepting that they are
not smoke-tested. Confirm visibility before implementing the matrix.

### The smoke test

This is the reason for a native matrix rather than a single cross-building
host. Each bundle job, on the operating system it targets, runs:

1. `abt --version`
2. `abt serve --port <random> --no-start-browser` in the background
3. poll `GET /status` until it answers
4. `abt shutdown`

That exercises the relocated venv, the rewritten shebang, and Playwright's Node
driver import — the three things that break silently. A bundle that fails this
never reaches the release.

### Guards

- **Version guard.** A step fails the run if the tag does not match
  `pyproject.toml`'s version. This prevents the unfixable mistake of a `v0.2.0`
  release shipping wheels labelled `0.1.0`.
- **Dry run.** `workflow_dispatch` takes a `dry_run` input that builds and
  smoke-tests everything and publishes nothing. Six channels are otherwise only
  testable by burning real version numbers, and AUR and winget publish into
  repositories owned by other people, where a mistake is public.

## Credentials runbook

Every credential is being obtained fresh. Since nothing has shipped, rotating
costs nothing — no user is trusting an old signature.

Three consolidations reduce seven secrets to four:

- **PyPI needs no secret.** Trusted Publishing is OIDC. Register a *pending
  publisher* on PyPI before the project exists, then GitHub proves identity per
  run. There is nothing to store and nothing to lose again.
- **One fine-grained PAT covers the tap and the Scoop bucket** — same owner,
  `Contents: read/write` on those two repositories only.
- **GPG is dropped.** Gemfury signs its own repository metadata; per-package
  `nfpm` signing is additive, not required. With `checksums.txt` and build
  provenance already in the design, the key pair buys little and is one more
  thing to lose.

| Secret | Obtain from | Blocks |
|---|---|---|
| *(none)* | pypi.org → Publishing → add pending publisher: owner `skssmd`, repo `Ai-Browser-Toolkit`, workflow `release.yml`, environment `pypi`. Confirm the name `aibrowsertoolkit` is unclaimed. | wave 1 |
| `TAP_TOKEN` | GitHub fine-grained PAT, `Contents: RW` on the tap and the Scoop bucket. If the org disallows fine-grained tokens, a classic PAT with `repo` scope works instead. | waves 2, 3 |
| `WINGET_TOKEN` | GitHub **classic** PAT with `public_repo`. `winget-releaser` requires a classic token. | wave 2 |
| `AUR_SSH_KEY` | `ssh-keygen -t ed25519 -f aur_ed25519`. Public half onto aur.archlinux.org → My Account; private half into the repository secret. | wave 3 |
| `FURY_TOKEN` | gemfury.com → Tokens → a **push** token. Free open-source tier. | wave 3 |

Also required, and not secrets: a fork of `microsoft/winget-pkgs` under an
account the `WINGET_TOKEN` can push to, synced with upstream `master` before
each run; and a `scoop-bucket` repository.

**Waves 0 and 1 need no credentials at all.** `GITHUB_TOKEN` is issued
automatically. The whole build half of this can be written and proven green
before a single account is recovered.

## Files

```
src/abt/paths.py                              tests/test_paths.py
packaging/bundle.py                           builds one bundle; runs locally
packaging/windows/abt.iss
packaging/nfpm.yaml
packaging/aur/PKGBUILD.template
packaging/homebrew/formula.rb.template
packaging/scoop/manifest.json.template
.github/workflows/ci.yml                      tests on push and PR
.github/workflows/release.yml                 the pipeline above
docs/packaging.md                             how to cut a release
```

`packaging/bundle.py` runs on a laptop by design. A six-channel pipeline whose
build step exists only inside a workflow is one that is debugged at ten minutes
per push.

## Testing

| Level | What |
|---|---|
| Unit | `paths.py` resolution per platform and per XDG variable, with the environment monkeypatched; the `pyproject.toml` escape hatch detected and not detected. |
| Bundle | The four-step smoke test above, on each of the five native runners. |
| Install | Against a dry-run release: `pipx install`, `scoop install`, `brew install`, a PKGBUILD build inside an `archlinux` container, and `apt install` from Gemfury inside a `debian` container. |

The install level is manual for the first release and scripted afterwards. It
cannot run against AUR or winget, whose publication is visible to other people;
those two are verified by reading the generated manifest in the dry run.

## Waves

**Wave 0 — prerequisite.** `paths.py`, its tests, and the three call sites in
`cli.py` and `launch.py`. No packaging. Nothing else can ship correctly until
an installed `abt` finds its profile.

**Wave 1 — build and PyPI.** `packaging/bundle.py`, the five-target matrix with
its smoke test, the wheel, the GitHub release with `checksums.txt` and
`attest-build-provenance`, and PyPI via Trusted Publishing. Needs no
credentials beyond the PyPI publisher registration. Proves the build on every
target.

**Wave 2 — Windows.** The Inno Setup script, the standalone `.exe` on the
release, the winget manifest, and the Scoop bucket. This is the wave that
delivers the autostart checkbox.

**Wave 3 — Unix packages.** The Homebrew formula, the AUR `-bin` package, and
`nfpm` output pushed to Gemfury.

**Wave 4 — deferred, with reasons.** Snap needs store credentials and passes a
review; Graft has its `snapcrafts:` block commented out. Nix means a pull
request into `nixpkgs` reviewed by strangers, on their schedule. Chocolatey has
a moderation queue and in practice expects an Authenticode-signed installer,
which the free-tier signing decision does not provide. All three are wanted.
None belongs in a first release that has not yet shipped once cleanly.

## Open questions

- Is `skssmd/Ai-Browser-Toolkit` public? Free ARM runners and free build
  provenance both depend on it. Resolve before wave 1.
- Is the PyPI name `aibrowsertoolkit` unclaimed? Resolve before wave 1.
- Does `the-graft-project` permit fine-grained personal access tokens? If not,
  `TAP_TOKEN` is a classic token with `repo` scope. Resolve before wave 2.
