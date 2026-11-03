"""Queue rows 27 and 30: the Linux sandbox of a live Claude or Codex run hides HOME and the host socket directories
(`/tmp`, `/run`, `/var/run`, `/var/tmp`, ...), re-exposes only the install roots, the `node` runtime and the resolver
configuration, read-only, and with bubblewrap 0.10+ binds them by pinned descriptor (`--ro-bind-fd`). Argument-level
checks here (no socket is created, no process is started); the real-bubblewrap checks are in
`test_linux_live_sockets.py` (CI only)."""
from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import pytest

from repo_ai.providers import adapters, claude_auth
from repo_ai.providers import discovery as d

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the Linux sandbox uses POSIX open flags")


def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fd_binds: bool = True) -> dict[str, Path]:
    base = tmp_path.resolve()
    home, run, outside = base / "home", base / "run", base / "usr"
    for p in (home / "inst" / "bin", run / "resolve", outside / "bin"):
        p.mkdir(parents=True)
    (home / "inst" / "bin" / "agent").write_text("#!/bin/sh\n")
    (outside / "bin" / "tool").write_text("#!/bin/sh\n")
    (run / "resolve" / "stub-resolv.conf").write_text("nameserver 127.0.0.53\n")
    etc = base / "etc"
    etc.mkdir()
    (etc / "resolv.conf").symlink_to(run / "resolve" / "stub-resolv.conf")
    monkeypatch.setattr(adapters.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(adapters, "_hidden_dirs", lambda: [str(run), str(home / ".ssh")])
    monkeypatch.setattr(adapters, "_homes", lambda: [str(home)])
    monkeypatch.setattr(adapters, "_bwrap_binds_fds", lambda bwrap: fd_binds)
    monkeypatch.setattr(adapters, "RESOLV_CONF", str(etc / "resolv.conf"))
    return {"base": base, "home": home, "run": run, "outside": outside}


def _binds(args: list[str]) -> list[tuple[str, str, str]]:
    return [(a, args[i + 1], args[i + 2]) for i, a in enumerate(args) if a in ("--ro-bind", "--ro-bind-fd", "--bind")]


def test_home_and_socket_directories_are_hidden_and_only_needed_roots_come_back(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    args, fds = adapters._live_linux_binds("/usr/bin/bwrap", [w["home"] / "inst", w["outside"] / "bin"])
    tmpfs = [args[i + 1] for i, a in enumerate(args) if a == "--tmpfs"]
    assert tmpfs == [str(w["home"]), str(w["run"])]  # ~/.ssh lies inside HOME: hidden with it
    binds = _binds(args)
    assert [dest for _, _, dest in binds] == [str(w["home"] / "inst"), str(w["run"] / "resolve" / "stub-resolv.conf")]
    assert all(kind == "--ro-bind-fd" for kind, _, _ in binds)  # pinned, never by path
    assert fds == [int(src) for _, src, _ in binds]
    for fd, (_, _, dest) in zip(fds, binds, strict=True):
        assert os.fstat(fd).st_ino == os.stat(dest).st_ino
    # every tmpfs comes before the first bind back (a later tmpfs would cover it)
    assert max(i for i, a in enumerate(args) if a == "--tmpfs") < min(i for i, a in enumerate(args) if a == "--ro-bind-fd")
    d._close_all(tuple(fds))


def test_an_older_bubblewrap_binds_by_path(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, fd_binds=False)
    args, fds = adapters._live_linux_binds("/usr/bin/bwrap", [w["home"] / "inst"])
    assert fds == []
    assert _binds(args) == [("--ro-bind", str(w["home"] / "inst"), str(w["home"] / "inst")),
                            ("--ro-bind", str(w["run"] / "resolve" / "stub-resolv.conf"),
                             str(w["run"] / "resolve" / "stub-resolv.conf"))]


def test_a_root_swapped_for_a_symlink_after_resolution_is_not_bound(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    real = w["home"] / "real"
    real.mkdir()
    (w["home"] / "swapped").symlink_to(real)  # was a directory when the root was resolved
    monkeypatch.setattr(adapters.Path, "resolve", lambda self, strict=False: Path(os.path.abspath(self)))
    args, fds = adapters._live_linux_binds("/usr/bin/bwrap", [w["home"] / "swapped"])
    assert str(w["home"] / "swapped") not in [dest for _, _, dest in _binds(args)]
    d._close_all(tuple(fds))


def test_a_bound_directory_hides_socket_directories_inside_it_again(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    inner = w["home"] / "inst" / "run-inside"
    inner.mkdir()
    monkeypatch.setattr(adapters, "_hidden_dirs", lambda: [str(w["run"]), str(inner)])
    args, fds = adapters._live_linux_binds("/usr/bin/bwrap", [w["home"] / "inst"])
    i = args.index(str(w["home"] / "inst"), args.index("--ro-bind-fd"))
    assert args[i + 1:i + 3] == ["--tmpfs", str(inner)]
    d._close_all(tuple(fds))


def _linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapters.sys, "platform", "linux")
    monkeypatch.setattr(adapters.shutil, "which", lambda name, path=None: "/usr/bin/bwrap" if name == "bwrap" else None)


@pytest.mark.parametrize("provider", ["codex", "claude", "bob"])
def test_the_live_prefix_hides_socket_directories_before_binding_the_workspace(tmp_path, monkeypatch, provider):
    w = _world(tmp_path, monkeypatch)
    _linux(monkeypatch)
    workspace, scratch = w["run"] / "ws", w["run"] / "scratch"  # e.g. under /tmp: bound back after the tmpfs
    workspace.mkdir()
    scratch.mkdir()
    exe = w["home"] / "inst" / "bin" / "agent"
    plan = claude_auth.ClaudeAuthPlan(mode="token_env", config_dir=None, env_vars=("CLAUDE_CODE_OAUTH_TOKEN",), problems=()) if provider == "claude" else None
    prefix = adapters._execution_sandbox_prefix(workspace, scratch, allow_network=True, provider=provider, live=True,
                                                executable=exe, claude_plan=plan)
    assert prefix is not None
    tmpfs_at = [i for i, a in enumerate(prefix) if a == "--tmpfs"]
    assert {prefix[i + 1] for i in tmpfs_at} >= {str(w["home"]), str(w["run"])}
    ws_at = prefix.index("--bind", prefix.index("/"))
    assert prefix[ws_at + 1] == str(workspace) and max(tmpfs_at) < ws_at
    fds = adapters.pinned_fds(prefix)
    assert fds and all(os.fstat(fd) for fd in fds)
    del prefix
    gc.collect()
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)  # closed with the prefix


def test_a_dry_run_starts_no_process_and_pins_nothing(tmp_path, monkeypatch):
    """Routing asks whether a sandbox can be built; it must not run `bwrap --help` or hold descriptors."""
    w = _world(tmp_path, monkeypatch)

    def refuse(bwrap):
        raise AssertionError("a dry run asked bubblewrap")
    monkeypatch.setattr(adapters, "_bwrap_binds_fds", refuse)
    args, fds = adapters._live_linux_binds("/usr/bin/bwrap", [w["home"] / "inst"], dry_run=True)
    assert fds == [] and "--ro-bind-fd" not in args and str(w["run"]) in args


def test_the_accounts_own_home_is_hidden_too(tmp_path, monkeypatch):
    """HOME overridden (sudo -E, a service account): the passwd home's credentials stay unreadable as well."""
    w = _world(tmp_path, monkeypatch)
    real = w["base"] / "account-home"
    real.mkdir()
    monkeypatch.setattr(adapters, "_homes", lambda: [str(w["home"]), str(real)])
    args, fds = adapters._live_linux_binds("/usr/bin/bwrap", [])
    assert str(real) in [args[i + 1] for i, a in enumerate(args) if a == "--tmpfs"]
    d._close_all(tuple(fds))


def test_login_stores_outside_home_are_hidden_but_never_a_system_or_ancestor_directory(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    store = w["base"] / "repo-ai-home"
    store.mkdir()
    args, fds = adapters._live_linux_binds("/usr/bin/bwrap", [], private=[store, Path("/"), Path("/usr"), w["base"]])
    tmpfs = [args[i + 1] for i, a in enumerate(args) if a == "--tmpfs"]
    assert str(store) in tmpfs
    assert "/" not in tmpfs and "/usr" not in tmpfs and str(w["base"]) not in tmpfs  # base holds HOME
    d._close_all(tuple(fds))


def test_an_install_directory_that_cannot_come_back_still_binds_the_executable(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(adapters, "_has_socket", lambda path, limit=2000, fd=None: True)  # e.g. too many entries
    exe = w["home"] / "inst" / "bin" / "agent"
    args, fds = adapters._live_linux_binds("/usr/bin/bwrap", [w["home"] / "inst"], files=[exe])
    dests = [dest for _, _, dest in _binds(args)]
    assert str(w["home"] / "inst") not in dests and str(exe) in dests
    d._close_all(tuple(fds))


@pytest.mark.parametrize("provider", ["codex", "claude", "bob"])
def test_live_runs_get_their_own_ipc_and_uts_namespaces(tmp_path, monkeypatch, provider):
    w = _world(tmp_path, monkeypatch)
    _linux(monkeypatch)
    plan = claude_auth.ClaudeAuthPlan(mode="token_env", config_dir=None, env_vars=(), problems=()) \
        if provider == "claude" else None
    prefix = adapters._execution_sandbox_prefix(w["run"], w["run"], allow_network=True, provider=provider, live=True,
                                                executable=w["home"] / "inst" / "bin" / "agent", claude_plan=plan,
                                                dry_run=True)
    assert "--unshare-ipc" in prefix and "--unshare-uts" in prefix
