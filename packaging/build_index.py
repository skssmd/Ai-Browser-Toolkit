"""Generate guidelines/index.json and each domain's meta.json.

Generated, never hand-written. The index is what a machine consults to answer
"is there a playbook for this domain", and a hand-maintained copy would drift
from the files the moment anyone added one.

    python packaging/build_index.py            # write
    python packaging/build_index.py --check    # fail if stale, for CI

Versions are bumped by hand in meta.json when a playbook's content changes --
the daily update check compares an integer, so it has to mean something. This
script only creates a meta.json that is missing, and never rewrites a version
someone set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "guidelines"

# Kept out of the index and out of the wheel: these name a real organisation,
# its routes and its staff records. `.gitignore` covers the repository; this
# covers anything built from a working tree that still has them on disk.
EXCLUDED = {"onehr"}


def domains() -> list[Path]:
    """A domain is any directory with a dot in its name.

    That is the whole rule, and it is why `toolkit-workflow.md` and
    `README.md` sit flat at the top: they are not about a site.
    """
    return sorted(
        d
        for d in ROOT.iterdir()
        if d.is_dir() and "." in d.name and d.name not in EXCLUDED
    )


def build() -> dict:
    index: dict[str, dict] = {}
    for domain in domains():
        meta_path = domain / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            meta = {"version": 1}
        meta["files"] = sorted(p.name for p in domain.glob("*.md"))
        index[domain.name] = {"version": int(meta["version"]), "files": meta["files"]}
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the index on disk is stale instead of rewriting it.",
    )
    args = parser.parse_args(argv)

    index = build()
    rendered = json.dumps(index, indent=2) + "\n"
    path = ROOT / "index.json"

    if args.check:
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current != rendered:
            print("guidelines/index.json is stale; run packaging/build_index.py")
            return 1
        print("index is current")
        return 0

    path.write_text(rendered, encoding="utf-8")
    print(f"{path} -> {len(index)} domains")
    return 0


if __name__ == "__main__":
    sys.exit(main())
