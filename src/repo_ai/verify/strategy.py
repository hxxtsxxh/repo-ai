"""How to run a plan: the selected test files in a few parallel processes,
or the project's own full suite as one process, whichever is expected to
finish first. Both run in the same sandbox, in disposable copies, with the
same checks; only the shape of the run differs.

The full suite runs every selected test and more, so when it is not
expected to be slower it is the better choice: more evidence for the same
wait. It is also the only run when the plan requires the full suite anyway
(running the selection first would execute the same tests twice).

**Cost model** (seconds of wall time, measured, never assumed):
- `d(f)`: test file `f` run alone in one process: the latest measured run
  (`Timings`), else its `--record` run;
- `s`: the fixed cost of one sandboxed process (copy, sandbox, interpreter
  start, imports), measured from batched runs; before that,
  `0.8 * min d(f)`;
- a batch of files as one process: `s + sum(max(d(f) - s, 0))`;
- the selection: the slowest of its parallel batches, times the measured
  ratio of actual to estimated time of earlier passing selection runs
  (parallel processes contend for the machine);
- the full suite: its measured time as one process (`--record` measures it
  once), else the same formula over every test file (only when every file
  has a duration).

Without durations (no `--record` yet, no earlier run) the selection runs
as before, and the decision says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runner import TestRunner

TIE_MARGIN_S = 0.25   # the full suite wins a near tie: same wait, more evidence


@dataclass(slots=True)
class Decision:
    kind: str                      # "targeted" | "full" | "none"
    reason: str
    batches: list[list[str]] = field(default_factory=list)
    est_targeted_s: float | None = None
    est_full_s: float | None = None
    est_full_source: str = ""      # "measured" | "estimated from per-file times" | ""

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "reason": self.reason, "batches": len(self.batches),
                "est_targeted_s": _r(self.est_targeted_s), "est_full_s": _r(self.est_full_s),
                "est_full_source": self.est_full_source}


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 2)


def groupable(runner: TestRunner) -> bool:
    """Files can share one process: unittest module lists need the top-level
    directory to be the working directory; pytest and node take paths."""
    return runner.kind in {"pytest", "node"} or (runner.kind == "unittest" and runner.top in {"", "."})


def startup_estimate(durations: dict[str, float | None], measured: float | None) -> float:
    if measured:
        return measured
    known = [d for d in durations.values() if d]
    return 0.8 * min(known) if known else 0.3


def batch_cost(files: list[str], d: dict[str, float | None], s: float, default: float) -> float:
    return s + sum(max((d.get(f) or default) - s, 0.0) for f in files)


def make_batches(runner: TestRunner, files: list[str], d: dict[str, float | None], workers: int) -> list[list[str]]:
    """Balanced groups, at most `workers` of them, longest files first.
    `node --test` already runs each file in its own child process, in
    parallel: one invocation for all of them is the natural batch."""
    if not files:
        return []
    if not groupable(runner):
        return [[f] for f in files]
    if runner.kind == "node":
        return [sorted(files)]
    k = max(1, min(workers, len(files)))
    bins: list[tuple[float, list[str]]] = [(0.0, []) for _ in range(k)]
    for f in sorted(files, key=lambda f: -(d.get(f) or 1.0)):
        i = min(range(k), key=lambda j: bins[j][0])
        load, members = bins[i]
        bins[i] = (load + (d.get(f) or 1.0), members + [f])
    return [sorted(m) for _, m in bins if m]


def decide(runner: TestRunner, selected: list[str], universe: list[str], durations: dict[str, float | None], *,
           full_required: bool, full_requested: bool, workers: int, measured_full: float | None,
           measured_startup: float | None, full_runnable: bool, targeted_ratio: float | None = None,
           full_unusable: str = "") -> Decision:
    """The run shape for this plan, and why."""
    if not runner.per_file:
        if full_runnable:
            return Decision("full", f"`{runner.command}` cannot be split per test file: the full suite runs")
        return Decision("none", "no test command that can be run")
    batches = make_batches(runner, selected, durations, workers)
    s = startup_estimate(durations, measured_startup)
    known = [durations.get(f) for f in universe]
    default = sorted(x for x in known if x)[len([x for x in known if x]) // 2] if any(known) else 1.0
    est_t = None
    if selected and all(durations.get(f) for f in selected):
        costs = [batch_cost(b, durations, s, default) for b in batches]
        # more batches than workers queue behind each other
        per_worker = max(1, workers)
        est_t = max(costs) if len(costs) <= per_worker else sum(costs) / per_worker
        est_t *= targeted_ratio or 1.0  # calibrated by earlier selection runs in this environment
    est_f, src = None, ""
    if measured_full:
        est_f, src = measured_full, "measured"
    elif universe and all(durations.get(f) for f in universe):
        est_f, src = batch_cost(universe, durations, s, default), "estimated from per-file times"
    if (full_required or full_requested) and full_runnable:
        why = "the full suite is required for this change" if full_required else "--full was requested"
        return Decision("full", why + "; it includes every selected test, so they are not run twice",
                        [], est_t, est_f, src)
    if not selected:
        return Decision("none", "no test file is linked to the change", [], None, est_f, src)
    if not full_runnable:
        return Decision("targeted", "the full suite command cannot be run as one sandboxed process",
                        batches, est_t, est_f, src)
    if full_unusable:
        return Decision("targeted", f"the full suite is not chosen for speed here: its result cannot be attributed "
                                    f"to files ({full_unusable})", batches, est_t, est_f, src)
    if est_t is None or est_f is None:
        missing = "per-file durations" if est_t is None else "full-suite time"
        return Decision("targeted", f"no {missing} yet to compare the two (`repo-ai verify --record` measures "
                                    "them); running the selection", batches, est_t, est_f, src)
    if est_f <= est_t + TIE_MARGIN_S:
        return Decision("full", f"the full suite ({src} {est_f:.1f}s as one process) is expected to be no "
                                f"slower than the selection (~{est_t:.1f}s in {len(batches)} process(es)); "
                                "it also runs every other test", [], est_t, est_f, src)
    return Decision("targeted", f"the selection (~{est_t:.1f}s in {len(batches)} process(es)) is expected to "
                                f"be faster than the full suite ({src} {est_f:.1f}s)", batches, est_t, est_f, src)


def process_limit(estimate: float | None, cap: float, explicit: bool, floor: float = 30.0) -> float:
    """A process's time limit. With a measured estimate, a few times that
    (a run that loops forever is cut early, not after the generic limit);
    an explicit `--timeout` is always used as given. A time-out is reported
    as a failure, never as a pass."""
    if explicit or not estimate:
        return cap
    return min(cap, max(floor, 5.0 * estimate + 10.0))
