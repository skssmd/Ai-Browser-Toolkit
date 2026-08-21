"""Site playbooks: shipped, looked up, pulled, trusted, and written.

They used to exist only as files in the repo, so `pip install` shipped none of
them and the bundles shipped them as loose files nobody found. An agent that
cannot read the playbook for a site drives it the slow way -- which is the
whole thing the playbooks exist to prevent.

## Nothing fetched is trusted

A playbook is *instructions an agent will follow*. Pulling one automatically
would let whoever controls the source change what agents do, silently, on
machines that merely visited a website. So a pull lands in `pending/` and
`read()` refuses to return it; `trust()` is a separate, deliberate act.

That is also why the domain lookup only ever *reports*. The server cannot
prompt -- it is HTTP -- so `goto` puts what it found in its response and the
caller decides.

## One folder per domain, with a version

    messenger.com/
        meta.json      {"version": 3, "files": [...]}
        messenger.md

`index.json` at the source root maps every domain to its version and files,
so the daily check for updates is one small fetch and an integer compare
rather than a crawl.

Playbooks that are not about a site -- `toolkit-workflow.md`, `README.md` --
sit flat at the top and are never versioned or fetched. A domain is any
directory with a dot in its name; that is the whole rule.

## Four layers

    local     written here by you              highest precedence
    trusted   pulled, then explicitly trusted
    packaged  shipped inside the wheel
    pending   pulled and not yet trusted       visible, never returned

## onehr is excluded at every layer

Those playbooks name a real organisation, its routes and its staff records.
`.gitignore` keeps them out of the repository and the build config keeps them
out of the wheel. This module filters them again, because a packaging change
that quietly started including them would otherwise be invisible.
"""

from __future__ import annotations

import json
import time
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from . import paths

EXCLUDED = ("onehr",)

# The playbook repository. Overridable in config, so pointing somewhere else
# -- a fork, a private mirror, a branch -- is a setting rather than a release.
DEFAULT_REPO = "https://github.com/skssmd/ABT-Playbooks"
DEFAULT_SOURCE = "https://raw.githubusercontent.com/skssmd/ABT-Playbooks/main"

# Once a day, and only for domains already trusted. It never pulls anything
# new on its own.
CHECK_INTERVAL = 24 * 60 * 60

LOCAL, TRUSTED, PENDING, PACKAGED = "local", "trusted", "pending", "packaged"
PRECEDENCE = (LOCAL, TRUSTED, PACKAGED)


# -- configuration --------------------------------------------------------


def config() -> dict:
    try:
        return json.loads(paths.config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_config(**values) -> dict:
    current = config()
    current.update(values)
    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def lookup_enabled() -> bool:
    return bool(config().get("guidelines_lookup", True))


def source_url() -> str:
    return str(config().get("guidelines_source", DEFAULT_SOURCE)).rstrip("/")


def repo_url() -> str:
    return str(config().get("guidelines_repo", DEFAULT_REPO)).rstrip("/")


# -- layout ---------------------------------------------------------------


def domain_of(url: str) -> str | None:
    """The domain a URL belongs to, as playbooks name it.

    `www.` is stripped because nobody writes a playbook per subdomain prefix,
    and `www.messenger.com` and `messenger.com` are the same site.
    """
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _packaged_root() -> Path | None:
    """The copy inside the wheel, or the checkout's own while developing.

    A checkout wins: editing `guidelines/foo.com/bar.md` and having
    `abt guidelines show` still print the installed copy would be its own
    small trap.
    """
    if paths.in_source_checkout():
        local = Path.cwd() / "guidelines"
        if local.is_dir():
            return local
    try:
        packaged = files("abt") / "guidelines"
        if packaged.is_dir():
            return Path(str(packaged))
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    return None


def _layer_root(layer: str) -> Path | None:
    if layer == PACKAGED:
        return _packaged_root()
    return paths.guidelines_home() / layer


def _allowed(name: str) -> bool:
    return bool(name) and not any(part in EXCLUDED for part in Path(name).parts)


def _resolve_within(root: Path, name: str) -> Path | None:
    """`name` under `root`, or None if it escapes.

    `name` reaches this from an HTTP path parameter, and "../../etc/passwd" is
    the obvious thing to try against a server that serves files by name.
    """
    try:
        resolved = (root / name).resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return resolved


def _meta(root: Path, domain: str) -> dict:
    path = _resolve_within(root, f"{domain}/meta.json")
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# -- what this machine has ------------------------------------------------


def installed() -> dict[str, dict]:
    """Every domain this machine holds, and from which layer.

    Highest precedence wins; a pending copy of something already held is
    reported as an offered update rather than replacing it.
    """
    found: dict[str, dict] = {}
    for layer in (PACKAGED, TRUSTED, LOCAL):
        root = _layer_root(layer)
        if root is None or not root.is_dir():
            continue
        for directory in sorted(p for p in root.iterdir() if p.is_dir()):
            domain = directory.name
            if "." not in domain or not _allowed(domain):
                continue
            found[domain] = {
                "domain": domain,
                "source": layer,
                "version": int(_meta(root, domain).get("version", 1)),
                "files": sorted(p.name for p in directory.glob("*.md")),
                "trusted": True,
            }

    pending_root = _layer_root(PENDING)
    if pending_root is not None and pending_root.is_dir():
        for directory in sorted(p for p in pending_root.iterdir() if p.is_dir()):
            domain = directory.name
            if not _allowed(domain):
                continue
            version = int(_meta(pending_root, domain).get("version", 1))
            if domain in found:
                found[domain]["pending_version"] = version
            else:
                found[domain] = {
                    "domain": domain,
                    "source": PENDING,
                    "version": version,
                    "files": sorted(p.name for p in directory.glob("*.md")),
                    "trusted": False,
                }
    return dict(sorted(found.items()))


def general() -> list[str]:
    """Playbooks that are not about a site, so never fetched or versioned."""
    root = _packaged_root()
    if root is None:
        return []
    return sorted(p.stem for p in root.glob("*.md"))


def read(name: str, allow_pending: bool = False) -> str:
    """One playbook's markdown, from the highest layer that has it.

    `name` is `domain/file` for a site playbook, or a bare stem for a general
    one. Raises KeyError rather than returning None, so a caller cannot
    mistake a missing playbook for an empty one. Pending content is refused
    unless asked for explicitly -- that refusal is the trust boundary.
    """
    if not _allowed(name):
        raise KeyError(name)
    order = PRECEDENCE + ((PENDING,) if allow_pending else ())
    for layer in order:
        root = _layer_root(layer)
        if root is None or not root.is_dir():
            continue
        resolved = _resolve_within(root, name if name.endswith(".md") else name + ".md")
        if resolved is not None and resolved.is_file():
            return resolved.read_text(encoding="utf-8")
    raise KeyError(name)


# -- the source -----------------------------------------------------------


def fetch_index(timeout: float = 10.0) -> dict:
    """The source's index.json. Raises on any network or parse failure."""
    import httpx

    response = httpx.get(f"{source_url()}/index.json", timeout=timeout)
    response.raise_for_status()
    return response.json()


def lookup(domain: str, timeout: float = 10.0) -> dict | None:
    """What the source has for a domain, next to what this machine has.

    Returns None when lookup is switched off, the domain is unknown, or the
    source cannot be reached -- a site visit must never fail because a
    playbook server is down.
    """
    if not lookup_enabled() or not _allowed(domain):
        return None
    try:
        index = fetch_index(timeout=timeout)
    except Exception:
        return None

    entry = index.get(domain)
    if not entry:
        return None

    held = installed().get(domain)
    return {
        "domain": domain,
        "available_version": int(entry.get("version", 1)),
        "files": entry.get("files", []),
        "held_version": held["version"] if held else None,
        "source": held["source"] if held else None,
        "trusted": bool(held and held["trusted"]),
        "update_available": bool(held and int(entry.get("version", 1)) > held["version"]),
    }


def pull(domain: str, only: list[str] | None = None, timeout: float = 30.0) -> list[Path]:
    """Fetch a domain's playbooks into `pending/`. Never into use.

    Deliberately not `trusted/`: see this module's docstring. The caller has
    to run `trust()` before anything here is readable.
    """
    import httpx

    if not _allowed(domain):
        raise KeyError(domain)
    index = fetch_index(timeout=timeout)
    entry = index.get(domain)
    if not entry:
        raise KeyError(f"no playbook for {domain}")

    root = _layer_root(PENDING)
    target = _resolve_within(root, domain)
    if target is None:
        raise KeyError(domain)
    target.mkdir(parents=True, exist_ok=True)

    wanted = entry.get("files", []) if only is None else list(only)
    written = []
    for filename in wanted:
        if not filename.endswith(".md") or "/" in filename or "\\" in filename:
            continue
        response = httpx.get(f"{source_url()}/{domain}/{filename}", timeout=timeout)
        response.raise_for_status()
        path = target / filename
        path.write_text(response.text, encoding="utf-8")
        written.append(path)

    # The ref matters as much as the version. A version says "the author
    # thinks this changed"; a commit says exactly which upstream state this
    # copy is, which is the only thing that survives a version somebody forgot
    # to bump.
    meta = {
        "version": int(entry.get("version", 1)),
        "files": entry.get("files", []),
        "source": source_url(),
        "ref": source_ref(),
        "pulled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (target / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return written


def source_ref(timeout: float = 10.0) -> str | None:
    """The commit the source is currently at, when it is a GitHub raw URL.

    Best effort: a source that is not GitHub, or a network that is down, gets
    None rather than failing the pull. The version is still recorded.
    """
    import httpx

    prefix = "https://raw.githubusercontent.com/"
    url = source_url()
    if not url.startswith(prefix):
        return None
    parts = url[len(prefix) :].split("/")
    if len(parts) < 3:
        return None
    owner, repo, branch = parts[0], parts[1], parts[2]
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}",
            timeout=timeout,
        )
        response.raise_for_status()
        return str(response.json()["sha"])
    except Exception:
        return None


def trust(domain: str) -> Path:
    """Promote a pulled domain from pending to trusted.

    The deliberate act the whole design hangs on: until this runs, the pulled
    content is inert.
    """
    pending_root = _layer_root(PENDING)
    source = _resolve_within(pending_root, domain)
    if source is None or not source.is_dir():
        raise KeyError(f"{domain} is not pending")

    target = _resolve_within(_layer_root(TRUSTED), domain)
    if target is None:
        raise KeyError(domain)
    target.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file():
            (target / path.name).write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            path.unlink()
    try:
        source.rmdir()
    except OSError:
        pass
    return target


def check_updates(force: bool = False, timeout: float = 10.0) -> list[dict]:
    """Domains whose source version is ahead of the trusted copy.

    Reports; never pulls. Rate-limited to once a day because it runs on server
    start, and a toolkit that reaches out on every launch is a toolkit people
    turn off.
    """
    if not lookup_enabled():
        return []
    last = float(config().get("guidelines_checked_at", 0))
    if not force and time.time() - last < CHECK_INTERVAL:
        return []
    try:
        index = fetch_index(timeout=timeout)
    except Exception:
        return []

    set_config(guidelines_checked_at=time.time())
    behind = []
    for domain, held in installed().items():
        entry = index.get(domain)
        if not entry:
            continue
        available = int(entry.get("version", 1))
        if held["trusted"] and available > held["version"]:
            behind.append(
                {
                    "domain": domain,
                    "held_version": held["version"],
                    "available_version": available,
                }
            )
    return behind


# -- writing your own -----------------------------------------------------


def save(domain: str, filename: str, text: str) -> Path:
    """Write a playbook of your own. Never touched by a pull."""
    if not _allowed(domain) or not filename.endswith(".md"):
        raise KeyError(f"{domain}/{filename}")
    target = _resolve_within(_layer_root(LOCAL), f"{domain}/{filename}")
    if target is None:
        raise KeyError(domain)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")

    meta = target.parent / "meta.json"
    if not meta.is_file():
        meta.write_text(json.dumps({"version": 1}, indent=2), encoding="utf-8")
    return target


def submission_paths(domain: str) -> tuple[Path, str]:
    """Where a local playbook lives, and the branch name to submit it under."""
    root = _resolve_within(_layer_root(LOCAL), domain)
    if root is None or not root.is_dir():
        raise KeyError(f"no local playbook for {domain}")
    return root, f"playbook/{domain}"


# -- searching ------------------------------------------------------------


def _normalise_query(query: str) -> tuple[str, str]:
    """Split a query into (domain-ish, file-ish).

    Accepts anything a person or an agent is likely to have: a bare word, a
    host, a full URL, or `domain/path`. `sheets`, `sheets.google.com`,
    `https://docs.google.com/spreadsheets/d/abc` all arrive here.
    """
    import re

    text = query.strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    if text.startswith("www."):
        text = text[4:]
    domain, _, rest = text.partition("/")
    return domain, rest.strip("/")


def _score(needle: str, hay: str) -> float:
    """How well `needle` matches `hay`. 1.0 is exact.

    Substring beats similarity on purpose: someone typing `sheets` means the
    thing with `sheets` in the name, even when a different entry happens to
    score higher on edit distance.
    """
    from difflib import SequenceMatcher

    if not needle:
        return 0.0
    if needle == hay:
        return 1.0
    if needle in hay:
        return 0.9
    if any(needle in part for part in hay.replace("-", ".").split(".")):
        return 0.85
    return SequenceMatcher(None, needle, hay).ratio()


def search(query: str, limit: int = 8, timeout: float = 10.0) -> dict:
    """Find playbooks for anything domain-ish, exactly or approximately.

    An exact domain is the fast path and returns every file that domain has
    in one answer -- no "which one did you mean" round trip, which is the
    whole point when an agent has just landed somewhere.

    Anything else is fuzzy, across both domain names and file names, so
    `sheets` finds `docs.google.com/sheets.md` and a hypothetical
    `sheets.google.com` alike. `domain/file` narrows the file search to that
    domain.
    """
    try:
        index = fetch_index(timeout=timeout)
    except Exception:
        return {"query": query, "exact": False, "matches": [], "source": None}

    domain, rest = _normalise_query(query)
    held = installed()

    def entry(name: str, files: list[str], matched_on: str, score: float) -> dict:
        local = held.get(name)
        return {
            "domain": name,
            "version": int(index[name].get("version", 1)),
            "files": files,
            "matched_on": matched_on,
            "score": round(score, 3),
            "held_version": local["version"] if local else None,
            "trusted": bool(local and local["trusted"]),
            "update_available": bool(
                local and int(index[name].get("version", 1)) > local["version"]
            ),
        }

    # Fast path: the domain is known. Return everything it has at once.
    if domain in index:
        files = index[domain].get("files", [])
        if rest:
            narrowed = [
                f for f in files if _score(rest, Path(f).stem.lower()) >= 0.6
            ] or files
        else:
            narrowed = files
        return {
            "query": query,
            "exact": True,
            "source": source_url(),
            "matches": [entry(domain, narrowed, "domain", 1.0)],
        }

    needle = domain or rest
    scored: list[tuple[float, dict]] = []
    for name, meta in index.items():
        files = meta.get("files", [])
        best = _score(needle, name)
        matched_on = "domain"
        for filename in files:
            file_score = _score(needle, Path(filename).stem.lower())
            if file_score > best:
                best, matched_on = file_score, f"file:{filename}"
        if best >= 0.5:
            hits = [
                f for f in files if _score(needle, Path(f).stem.lower()) >= 0.6
            ] or files
            scored.append((best, entry(name, hits, matched_on, best)))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["domain"]))
    return {
        "query": query,
        "exact": False,
        "source": source_url(),
        "matches": [match for _, match in scored[:limit]],
    }


def trust_files(domain: str, filenames: list[str]) -> Path:
    """Trust some of a domain's pulled files and leave the rest pending.

    Reviewing a folder file by file only means something if declining one
    actually leaves it out -- otherwise the per-file prompt is theatre.
    """
    pending_root = _layer_root(PENDING)
    source = _resolve_within(pending_root, domain)
    if source is None or not source.is_dir():
        raise KeyError(f"{domain} is not pending")

    target = _resolve_within(_layer_root(TRUSTED), domain)
    if target is None:
        raise KeyError(domain)
    target.mkdir(parents=True, exist_ok=True)

    for filename in filenames:
        if "/" in filename or "\\" in filename:
            continue
        path = source / filename
        if path.is_file():
            (target / filename).write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            path.unlink()

    # The meta travels with whatever was accepted, so a partial trust still
    # records a version -- and the pending copy keeps its own for the rest.
    meta = source / "meta.json"
    if meta.is_file():
        (target / "meta.json").write_text(
            meta.read_text(encoding="utf-8"), encoding="utf-8"
        )
        if not any(p.suffix == ".md" for p in source.iterdir()):
            meta.unlink()
            try:
                source.rmdir()
            except OSError:
                pass
    return target
