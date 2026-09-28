"""Named profiles and the Chrome processes on them, with no real Chrome.

`spawn` is faked with a process that writes the DevToolsActivePort file Chrome
would, so launch, reuse, the cap, idle detection and crash recovery are all
checked in milliseconds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from abt.errors import OpError
from abt.profiles import DEFAULT, ProfileRegistry, check_name, launch_argv


class FakeProcess:
    _next_port = 9300

    def __init__(self, argv, write_port=True):
        self.argv = argv
        self.returncode = None
        profile = next(a for a in argv if a.startswith("--user-data-dir="))
        self.dir = Path(profile.split("=", 1)[1])
        if write_port:
            FakeProcess._next_port += 1
            (self.dir / "DevToolsActivePort").write_text(
                f"{FakeProcess._next_port}\n/devtools/browser/x", encoding="utf-8"
            )

    def poll(self):
        return self.returncode

    def die(self):
        self.returncode = 1

    def wait(self, timeout=None):
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def spawned():
    return []


@pytest.fixture
def make(tmp_path, spawned):
    def build(**kw):
        def spawn(argv):
            process = FakeProcess(argv)
            spawned.append(process)
            return process

        kw.setdefault("spawn", spawn)
        kw.setdefault("find_binary", lambda browser: Path("/bin/chrome"))
        kw.setdefault("http_get", lambda url: [])
        return ProfileRegistry(root=tmp_path / "profiles", **kw)

    return build


@pytest.mark.parametrize(
    "bad", ["", "..", "../x", "/abs", "C:\\x", "a/b", "a\\b", ".hidden", "x" * 65, "a b"]
)
def test_names_that_are_paths_are_refused(bad):
    with pytest.raises(OpError) as exc:
        check_name(bad)
    assert exc.value.type == "invalid_op"


@pytest.mark.parametrize("good", ["work", "a.b-c_1", "A1", "x" * 64])
def test_ordinary_names_pass(good):
    assert check_name(good) == good


def test_default_lives_where_serve_was_told(make, tmp_path):
    reg = make(default_dir=tmp_path / "custom")
    assert reg.path(DEFAULT) == (tmp_path / "custom").resolve()
    assert reg.path("work") == (tmp_path / "profiles" / "work").resolve()


def test_create_list_remove(make):
    reg = make()
    reg.create("work")
    names = [p["name"] for p in reg.list()]
    assert names == ["default", "work"]
    with pytest.raises(OpError) as exc:
        reg.create("work")
    assert exc.value.type == "invalid_op"
    reg.remove("work", in_use=False)
    assert [p["name"] for p in reg.list()] == ["default"]


def test_a_bad_name_touches_nothing(make, tmp_path):
    reg = make()
    with pytest.raises(OpError):
        reg.create("../escape")
    assert not (tmp_path / "escape").exists()


def test_remove_is_refused_for_default_in_use_or_missing(make):
    reg = make()
    reg.create("work")
    with pytest.raises(OpError) as exc:
        reg.remove(DEFAULT, in_use=False)
    assert exc.value.type == "invalid_op"
    with pytest.raises(OpError) as exc:
        reg.remove("work", in_use=True)
    assert exc.value.type == "profile_in_use"
    with pytest.raises(OpError) as exc:
        reg.remove("ghost", in_use=False)
    assert exc.value.type == "profile_not_found"


def test_remove_is_refused_while_its_browser_runs(make):
    reg = make()
    reg.create("work")
    reg.attach("work", "s")
    with pytest.raises(OpError) as exc:
        reg.remove("work", in_use=False)
    assert exc.value.type == "profile_in_use"


def test_headed_persists(make):
    reg = make()
    reg.create("work")
    reg.set_headed("work", True)
    assert reg.meta("work")["headed"] is True


def test_default_headed_follows_the_server_until_set(make):
    assert make(default_headed=True).meta(DEFAULT)["headed"] is True
    assert make(default_headed=False).meta(DEFAULT)["headed"] is False


def test_launch_argv_hides_and_unthrottles(tmp_path):
    argv = launch_argv(Path("/bin/chrome"), tmp_path, headed=False)
    assert f"--user-data-dir={tmp_path}" in argv
    assert "--remote-debugging-port=0" in argv
    assert "--headless=new" in argv
    for flag in (
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
    ):
        assert flag in argv
    assert "--headless=new" not in launch_argv(Path("/bin/chrome"), tmp_path, headed=True)


def test_attach_launches_once_and_detach_stops_after_the_last(make, spawned):
    reg = make()
    url = reg.attach(DEFAULT, "a")
    assert url.startswith("http://127.0.0.1:")
    assert reg.attach(DEFAULT, "b") == url
    assert len(spawned) == 1
    reg.detach(DEFAULT, "a")
    assert reg.running(DEFAULT) is not None
    reg.detach(DEFAULT, "b")
    assert reg.running(DEFAULT) is None
    assert spawned[0].returncode is not None


def test_the_cap_refuses_and_never_evicts(make):
    reg = make(max_running=1)
    reg.create("other")
    reg.attach(DEFAULT, "a")
    with pytest.raises(OpError) as exc:
        reg.attach("other", "b")
    assert exc.value.type == "profile_limit"
    assert reg.running(DEFAULT) is not None


def test_a_dead_chrome_is_relaunched_with_its_tabs_forgotten(make, spawned):
    reg = make()
    reg.attach(DEFAULT, "a")
    reg.tabs(DEFAULT).opened("T1", "a")
    spawned[0].die()
    reg.attach(DEFAULT, "a")
    assert len(spawned) == 2
    assert reg.tabs(DEFAULT).owner_of("T1") is None


def test_a_profile_held_by_another_chrome_fails_fast(make, tmp_path):
    """Review focus 5: Chrome's single-instance handoff exits at once."""
    def spawn(argv):
        process = FakeProcess(argv, write_port=False)
        (process.dir / "SingletonLock").write_text("", encoding="utf-8")
        process.die()
        return process

    reg = make(spawn=spawn, launch_timeout=30.0)
    with pytest.raises(OpError) as exc:
        reg.attach(DEFAULT, "a")
    assert exc.value.type == "browser_dead"
    assert "holding the profile" in exc.value.message


def test_no_browser_installed(make):
    reg = make(find_binary=lambda browser: None)
    with pytest.raises(OpError) as exc:
        reg.attach(DEFAULT, "a")
    assert exc.value.type == "browser_not_found"


def test_idle_skips_watched_and_disabled(make):
    now = [100.0]
    reg = make(clock=lambda: now[0], idle_minutes=1)
    reg.create("watched")
    reg.attach(DEFAULT, "a")
    reg.attach("watched", "b")
    reg.watch("watched", +1)
    now[0] += 61
    assert reg.idle() == [DEFAULT]
    reg.touch(DEFAULT)
    assert reg.idle() == []
    assert make(idle_minutes=0).idle() == []


def test_targets_are_pages_only(make):
    rows = [{"id": "A", "type": "page"}, {"id": "B", "type": "service_worker"}]
    reg = make(http_get=lambda url: rows)
    reg.attach(DEFAULT, "a")
    assert [r["id"] for r in reg.targets(DEFAULT)] == ["A"]
