# Cutting a release

The whole pipeline hangs off one tag. Nothing is published by hand.

1. Bump `version` in `pyproject.toml`.
2. `git commit -am "Release vX.Y.Z" && git tag vX.Y.Z && git push --follow-tags`
3. Watch the Release workflow. It tests, builds a wheel and five bundles,
   smoke-tests each bundle on its own operating system, publishes a GitHub
   release with checksums and build provenance, then fans out to the channels.

**Bump the file first, then tag -- never the reverse.** The tag must match
`pyproject.toml`'s version or the run fails on purpose: a release shipping
mislabelled wheels cannot be fixed afterwards, because PyPI does not allow
re-uploading a version.

## Testing without burning a version

    gh workflow run Release -f dry_run=true

Builds and smoke-tests everything and publishes nothing. Worth doing before
any release that touches the pipeline itself, because two of the channels --
the AUR and winget -- publish into repositories owned by other people, where
a mistake is public.

## When one channel fails

The publisher jobs are independent and all read from the finished GitHub
release. Re-run the single failed job rather than the whole release; the
release and its assets already exist.

## Verifying an install by hand

    pipx install ai-browser-toolkit
    abt --version
    abt doctor        # finds the browser, and shows where the profile landed

The `abt doctor` line is the one worth running on every channel. It prints the
resolved profile directory, which is the thing most likely to be wrong in a
freshly packaged install -- a copy that resolves its profile against the
working directory looks fine until it is started from somewhere else and finds
none of your logins.

## What feeds what

| Channel | Artifact | Repository |
|---|---|---|
| PyPI | wheel + sdist | pypi.org/project/ai-browser-toolkit |
| Standalone / winget | Inno `.exe` | GitHub release / microsoft/winget-pkgs |
| Scoop | Windows zip | skssmd/scoop-bucket |
| Homebrew | macOS **arm64** tarball | skssmd/homebrew-tap |
| AUR | Linux tarballs | aibrowsertoolkit-bin |
| apt / dnf / apk | Linux tarballs | apt.fury.io/skssmd |

The tap and the Scoop bucket live under `skssmd`. The winget fork does not:
`skssmd/winget-pkgs` redirects to **`The-Graft-Project/winget-pkgs`**, because
the fork was transferred to that org. `fork-user` in the winget job names the
org for that reason -- a redirect is not something the action follows.

The pushes rebase and retry, and they push *before* pulling. `git pull
--rebase` fails outright against a repository with no commits, which is
exactly what a freshly created bucket is, so pulling first meant the very
first release could never land.

**The first winget submission is manual.** `winget-releaser` only *updates* a
package that already exists in `microsoft/winget-pkgs`; on a brand-new
identifier it fails with "Package skssmd.AIBrowserToolkit does not exist in
the winget-pkgs repository". Version 0.1.2 was submitted by hand with
`wingetcreate new`; every release after that is automatic. Once it merges,
remove `continue-on-error: true` from the winget job -- it is there only to
stop that one manual prerequisite colouring every release red, and leaving it
would hide a genuine winget failure later.

## The name is different on every channel

Only the command is constant. This trips people up, so it is written down:

| Channel | Install as |
|---|---|
| PyPI | `pip install ai-browser-toolkit` |
| winget | `winget install skssmd.AIBrowserToolkit` (moniker `abt`) |
| Scoop | `scoop install aibrowsertoolkit` |
| Homebrew | `brew install aibrowsertoolkit` |
| AUR | `yay -S aibrowsertoolkit-bin` |
| apt / dnf / apk | `aibrowsertoolkit` |

Then always `abt`.

PyPI's is the odd one out and not by choice: `aibrowsertoolkit` was rejected
as "too similar to an existing project" -- PyPI strips `-`, `_` and `.` before
comparing, and the project it collided with was our own `ai-browser-toolkit`,
registered earlier. The bundle, installer and distro package names keep the
old spelling deliberately: the winget manifest pins an installer URL, and
renaming the assets would break it.

## Secrets

Five of the seven the design first assumed were consolidated away. What is
left, and which wave first needs it:

| Secret | Wave |
|---|---|
| *(none -- PyPI uses Trusted Publishing)* | 1 |
| `TAP_TOKEN` -- fine-grained PAT, Contents RW on the tap and the Scoop bucket | 3, 4 |
| `WINGET_TOKEN` -- **classic** PAT with `public_repo` | 3 |
| `AUR_SSH_KEY` -- the **private** key, including its trailing newline | 4 |
| `FURY_TOKEN` -- Gemfury **push** token | 4 |

PyPI additionally needs a GitHub environment named exactly `pypi`, and a
publisher registered at pypi.org naming **project `ai-browser-toolkit`**,
owner `skssmd`, repository `Ai-Browser-Toolkit`, workflow `release.yml`,
environment `pypi`. Neither is a secret; both are easy to forget, and their
absence only shows up during a real release.

The project name is the field that goes wrong. It must match
`pyproject.toml`'s `name`, not the repository name -- a mismatch fails with
"Non-user identities cannot create new projects", which reads like an
authentication problem and is not one.

## No Intel Mac build

`macos-13` is GitHub's last Intel image and is being retired; it queued badly
enough to hold up every release behind it, so the matrix dropped it on
2026-08-21. Consequences worth knowing:

* The Homebrew formula is arm64-only and says so with `depends_on arch: :arm64`,
  which refuses the install up front rather than failing on a dead download URL.
* `packaging/bundle.py` still knows the `macos-x86_64` target, so an Intel Mac
  can build a bundle locally with `python packaging/bundle.py --target
  macos-x86_64 ...`. Nothing publishes it.
* Intel Mac users are served by `pipx install ai-browser-toolkit`, which is
  architecture-independent.

## Why the build matrix is native

Four runners, one per target, rather than one host cross-building all four.
The point is the smoke test: each bundle starts its own server and answers
`/status` on the operating system it targets. A cross-built bundle is never
executed on the platform it is for, and the relocated interpreter, the
launcher shim and Playwright's Node driver import are exactly the three things
that fail silently. `packaging/bundle.py` refuses a `--target` that is not the
host for the same reason.
