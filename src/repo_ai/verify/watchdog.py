"""Per-test progress watchdog (docs/VERIFY-WATCHDOG.md, Phase 1).

A hung test used to cost its process's whole time limit (5x measured time
plus 10 s, at least 30 s). The watchdog watches the run's own per-test
report while it is written and ends the run early when no test has started
or ended for longer than the slowest plausible gap:

- with a test open: that test file's budget, max(FLOOR_S, 3 x its slowest
  recent run + 2 s), or the largest budget of the files the process has
  already reported (a session fixture is torn down in a later file's test);
- before the first event (imports and collection): the same formula over
  the measured times of all the files the process runs, added together;
- between tests: the largest budget of the files the process was asked to
  run.

Every budget is capped at the process's own limit, so the watchdog can only
make a run shorter. A missing measurement turns that check off (the hard
limit applies). A stalled run ends exactly like a time-out: the process
group is killed and the result is a time-out, never a pass; the open test
is reported as the one that did not finish.

The report is written by the process under test, so it is read as
untrusted data: incrementally, size-bounded, never following a link. A
test can only make the watchdog wait for the hard limit (by writing
events) or end its own run as a time-out (by staying silent).
"""

from __future__ import annotations

import json
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path

FLOOR_S = 5.0
FACTOR = 3.0
MAX_READ = 32 * 1024 * 1024
MAX_OPEN = 10_000        # tests open at once; more is a forged report: stop watching
MAX_LINE = 64 * 1024     # one event line


def budget(seconds: float | None, cap: float) -> float | None:
    if seconds is None or seconds <= 0:
        return None
    return min(cap, max(FLOOR_S, FACTOR * seconds + 2.0))


class Watch:
    """Called about every 0.5 s by the sandbox while the process runs;
    returns why it stalled, or ""."""

    def __init__(self, report: Path, inside_root: str, budgets: dict[str, float | None],
                 start_budget: float | None, cap: float, clock: Callable[[], float] = time.monotonic):
        self.report = report
        self.run_dir = os.path.realpath(report.parent)  # created before the tests started
        self.prefix = inside_root.rstrip("/") + "/"
        self.budgets = budgets
        self.start_budget = start_budget
        self.cap = cap
        self.clock = clock
        self.last = clock()
        self.appeared = False  # the clock starts when the reporter has created the report
        self.offset = 0
        self.partial = b""
        self.open: dict[tuple[str, str], float] = {}
        self.touched: set[str] = set()  # files this process has reported a test of
        self.seen = False
        self.broken = False  # the report was replaced, or is too large to follow: stop watching
        self.dir_fd: int | None = None
        if os.open in getattr(os, "supports_dir_fd", set()):
            try:
                self.dir_fd = os.open(report.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                      | getattr(os, "O_NOFOLLOW", 0))
            except OSError:
                self.dir_fd = None

    def close(self) -> None:
        if self.dir_fd is not None:
            try:
                os.close(self.dir_fd)
            except OSError:
                pass
            self.dir_fd = None

    def __call__(self) -> str:
        if self.broken:
            return ""
        self._read()
        if self.broken or not self.appeared:
            return ""  # before the report exists (a container still starting) only the hard limit applies
        silent = self.clock() - self.last
        where = ""
        if self.open:
            path, tid = next(iter(self.open))  # the oldest test still open
            where = self._file(path, tid)
            limit = self.budgets.get(where) if where else None
            # the open test may be paying for an earlier file: a session or package fixture is torn
            # down in the last test that uses its scope, so the largest budget of the files already
            # seen applies, and none (the hard limit) when one of them is unmeasured
            if limit is not None:
                seen = [self.budgets.get(f) for f in self.touched]
                limit = None if any(b is None for b in seen) else max([limit, *seen])  # type: ignore[type-var]
        elif not self.seen:
            limit = self.start_budget
        else:
            known = list(self.budgets.values())
            limit = max(known) if known and all(b is not None for b in known) else None  # type: ignore[type-var]
        if limit is None:
            return ""
        limit = min(limit, self.cap)
        if silent > limit:
            return (f"no test started or finished for {silent:.0f}s (budget {limit:.0f}s"
                    + (f", in {where}" if where else "") + ")")
        return ""

    def _file(self, path: str, tid: str) -> str:
        """The test file an event belongs to. pytest's node id names the file
        that collected the test (an inherited test's `path` is the file that
        defines it); otherwise the reported path inside the workspace."""
        head = tid.split("::", 1)[0] if "::" in tid else ""
        if head and head in self.budgets:
            return head
        path = path.replace("\\", "/")
        prefix = self.prefix.replace("\\", "/")
        if os.name == "nt":
            path, prefix = path.lower(), prefix.lower()
            return next((f for f in self.budgets if f.lower() == path[len(prefix):]), "") \
                if path.startswith(prefix) else ""
        return path[len(prefix):] if path.startswith(prefix) else ""

    def _read(self) -> None:
        if self.offset >= MAX_READ:  # events may still be flowing, unseen: never judge silence from here
            self.broken = True
            return
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            if self.dir_fd is not None:  # relative to the run directory opened once: a swapped directory
                fd = os.open(self.report.name, flags, dir_fd=self.dir_fd)  # is never followed
            else:
                if os.path.realpath(self.report.parent) != self.run_dir:
                    self.broken = True
                    return
                fd = os.open(self.report, flags)
        except FileNotFoundError:
            return  # not written yet
        except OSError:
            self.broken = True
            return
        if not self.appeared:
            self.appeared, self.last = True, self.clock()
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                self.broken = True
                return
            os.lseek(fd, self.offset, os.SEEK_SET)
            chunk = os.read(fd, min(1 << 20, MAX_READ - self.offset))
        finally:
            os.close(fd)
        if not chunk:
            return
        self.offset += len(chunk)
        data = self.partial + chunk
        lines = data.split(b"\n")
        self.partial = lines.pop()
        if len(self.partial) > MAX_LINE:
            self.broken = True
            return
        now = self.clock()
        for line in lines:
            if len(line) > MAX_LINE:
                continue
            try:
                ev = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(ev, dict):
                continue
            self.seen = True
            self.last = now
            kind, key = ev.get("e"), (str(ev.get("path") or ""), str(ev.get("id") or ""))
            f = self._file(*key)
            if f:
                self.touched.add(f)
            if kind == "start":
                self.open.setdefault(key, now)
                if len(self.open) > MAX_OPEN:
                    self.broken = True
                    return
            elif kind == "end":
                self.open.pop(key, None)
