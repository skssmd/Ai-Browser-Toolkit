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

    pipx install aibrowsertoolkit
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
| PyPI | wheel + sdist | pypi.org/project/aibrowsertoolkit |
| Standalone / winget | Inno `.exe` | GitHub release / microsoft/winget-pkgs |
| Scoop | Windows zip | the-graft-project/scoop-bucket |
| Homebrew | macOS tarballs | the-graft-project/homebrew-tap |
| AUR | Linux tarballs | aibrowsertoolkit-bin |
| apt / dnf / apk | Linux tarballs | apt.fury.io/skssmd |

The tap and the winget fork are shared with the Graft project. Every push into
them rebases and retries, because a simultaneous Graft release would otherwise
lose this one to a non-fast-forward rejection.

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
pending publisher registered at pypi.org naming owner `skssmd`, repository
`Ai-Browser-Toolkit`, workflow `release.yml`, environment `pypi`. Neither is a
secret; both are easy to forget, and their absence only shows up during a real
release.

## Why the build matrix is native

Five runners, one per target, rather than one host cross-building all five.
The point is the smoke test: each bundle starts its own server and answers
`/status` on the operating system it targets. A cross-built bundle is never
executed on the platform it is for, and the relocated interpreter, the
launcher shim and Playwright's Node driver import are exactly the three things
that fail silently. `packaging/bundle.py` refuses a `--target` that is not the
host for the same reason.
