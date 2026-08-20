# Parked work

Things deliberately deferred, with enough context to pick them up cold.

## Packaged application + installer

Designed and planned, 2026-08-20. See
[the design](superpowers/specs/2026-08-20-packaging-and-distribution-design.md)
and [the plan](superpowers/plans/2026-08-20-packaging-and-distribution.md).

The shapes considered and rejected -- tray app, full desktop app, one-file
PyInstaller binary -- are recorded in the design's non-goals, along with the
reason the one-file binary in particular cannot work here: Playwright locates
its Node driver at runtime, and an extracted temporary directory is not where
it looks.

Snap, Nix and Chocolatey are wanted and deliberately deferred; the design's
"Wave 4" says why each one is more than a manifest.
