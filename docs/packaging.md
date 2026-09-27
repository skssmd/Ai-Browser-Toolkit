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

## The winget manifest needs a privacy policy

WinGet repository policy
[1.5.1](https://learn.microsoft.com/windows/package-manager/package/windows-package-manager-policies)
asks any package that touches personal data to publish a product-specific
privacy policy and point `PrivacyUrl` at it. ABT does: it drives a persistent
browser profile, so it can reach cookies, authenticated sessions, page text,
screenshots, session logs and Messenger threads. The moderation nudge on
[microsoft/winget-pkgs#428651](https://github.com/microsoft/winget-pkgs/pull/428651)
is the check-in policy asking for exactly that.

The policy is [`PRIVACY.md`](../PRIVACY.md) at the repository root, published at
<https://github.com/skssmd/Ai-Browser-Toolkit/blob/main/PRIVACY.md>.

`PrivacyUrl` is a **locale manifest** field, not an installer one — it goes in
`manifests/s/skssmd/AIBrowserToolkit/<version>/skssmd.AIBrowserToolkit.locale.en-US.yaml`,
directly after `PublisherSupportUrl`. There is no MSIX manifest here to carry it;
the Inno installer's `AppPublisherURL` is not the place, and WinGet reads nothing
from the installer for this.

The manifest is not in this repository — it lives in `microsoft/winget-pkgs`, and
the PR's head branch lives in the `The-Graft-Project/winget-pkgs` fork.

**Merge the policy before the manifest change.** `PrivacyUrl` is a link into this
repository on `main`; it returns 404 until `PRIVACY.md` lands, and a `PrivacyUrl`
that does not resolve is not going to satisfy anybody.

### Pointing the PR at the current release

A new-package PR is expected to submit the **latest** version, and PR 428651 was
opened against 0.3.6 while the project is now further along. `winget-releaser`
cannot fix this — it only *updates* an identifier that already exists upstream,
so until the first version is merged every release has to be hand-advanced in
the PR.

`packaging/winget/manifest-v0.6.2.patch` does it in one step: it renames the
version directory `0.3.6/` to `0.6.2/`, sets `PackageVersion`, the installer URL
and SHA256, `ReleaseDate` and `ReleaseNotesUrl`, and adds `PrivacyUrl` in the
same pass. Eight lines across three files, verified with `git apply --check`
against the PR's actual contents.

```bash
git clone --branch skssmd.AIBrowserToolkit-0.3.6-ff27dee5-d0c7-4d7a-babb-9d87713da460 \
  https://github.com/The-Graft-Project/winget-pkgs
cd winget-pkgs
git apply /path/to/aibrowsertoolkit/packaging/winget/manifest-v0.6.2.patch
git add -A
git commit -m "Add PrivacyUrl and update to 0.6.2"
git push origin skssmd.AIBrowserToolkit-0.3.6-ff27dee5-d0c7-4d7a-babb-9d87713da460
```

The branch name is from PR 428651; re-read it from the PR if it has changed.

The SHA256 in that patch —
`D76ECB26A386CA80241AD610AA6D6DE171A2D7A4F2C96AF9D107F64F04D1922F` — is the one
the release published in its own `checksums.txt`, and it matches the asset
digest GitHub reports. A mistyped hash is the most common reason a manifest gets
sent back, so take it from `checksums.txt` and never from a terminal transcript.

For a later release, the same edit is four substitutions: `PackageVersion` in
all three files, `InstallerUrl`, `InstallerSha256`, `ReleaseDate`, plus
`ReleaseNotesUrl` in the locale file — and the version directory has to be
renamed to match, or the validation pipeline rejects the PR. `wingetcreate new`
does all of it interactively, including downloading the asset to hash it, and
`wingetcreate.exe` is already in the repository root. Check afterwards that
`PrivacyUrl` is still in the locale file: a regenerated manifest will not
invent it.

### If the version is already right

`packaging/winget/privacy-url.patch` is the one-line change on its own, for when
the manifest already points at the version you want to submit. Both patches are
pinned to 0.3.6 in their paths; edit the header for a different version.

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
