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

**Steadiness** (C16: speed-v1 run 5 recorded the same suite choosing
differently between calls on estimates a few tenths of a second apart).
Only when nothing forces a shape (`basis` "forced": the change requires the
full suite, `--full`, a command that cannot be split or run whole, a full
suite whose result cannot be attributed, an empty selection) does the shape
chosen for the same suite in the same environment (`cache.suite_key`, kept
in `Timings`) count as `previous`. It is kept unless the other shape wins by
a margin beyond today's rule: `max(SWITCH_FLOOR_S, SWITCH_FRACTION x` the
kept shape's estimate`)`. There time alone already decides between the two,
so keeping one picks nothing the rule above could not pick under other
timings; the forcing conditions are checked first and always win. Without a
previous choice the rule is exactly the one above.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runner import TestRunner

TIE_MARGIN_S = 0.25   # the full suite wins a near tie: same wait, more evidence
# a shape chosen before for the same suite is kept unless the other wins by this much beyond the rule above
SWITCH_FLOOR_S = 0.25
SWITCH_FRACTION = 0.2
STEADY_KINDS = ("targeted", "full")       # the shapes between which only time decides
# basis: "forced" (the case decides), "no-estimates" (nothing to compare: the selection), "compared" (the
# estimates, no earlier choice), "kept" (the earlier choice for this suite, not beaten by the margin),
# "switched" (the earlier choice, beaten by the margin)
_STEADY_BASES = ("no-estimates", "compared", "kept", "switched")


@dataclass(slots=True)
class Decision:
    kind: str                      # "targeted" | "full" | "none"
    reason: str
    batches: list[list[str]] = field(default_factory=list)
    est_targeted_s: float | None = None
    est_full_s: float | None = None
    est_full_source: str = ""      # "measured" | "estimated from per-file times" | ""
    basis: str = "forced"          # see `_STEADY_BASES`
    previous: str | None = None    # the shape chosen before for the same suite, when it was consulted
    margin_s: float | None = None  # the margin a switch away from `previous` needed

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "reason": self.reason, "batches": len(self.batches),
                "est_targeted_s": _r(self.est_targeted_s), "est_full_s": _r(self.est_full_s),
                "est_full_source": self.est_full_source, "basis": self.basis, "previous": self.previous,
                "margin_s": _r(self.margin_s)}


def steady(d: Decision) -> bool:
    """The decision is one only time made, so it may be remembered as the suite's shape."""
    return d.kind in STEADY_KINDS and d.basis in _STEADY_BASES


def switch_margin(kept_estimate: float) -> float:
    return max(SWITCH_FLOOR_S, SWITCH_FRACTION * kept_estimate)


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
           full_unusable: str = "", previous: str | None = None) -> Decision:
    """The run shape for this plan, and why. `previous`: the shape chosen
    before for the same suite in the same environment (see the module's
    "Steadiness"); it is consulted only after every forcing condition."""
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
    prev = previous if previous in STEADY_KINDS else None
    if est_t is None or est_f is None:
        missing = "per-file durations" if est_t is None else "full-suite time"
        if prev == "full":
            return Decision("full", f"no {missing} to compare the two; the full suite was chosen before for this "
                                    "unchanged suite and environment and is kept", [], est_t, est_f, src,
                            "kept", prev)
        if prev == "targeted":
            return Decision("targeted", f"no {missing} to compare the two; the selection was chosen before for "
                                        "this unchanged suite and environment and is kept", batches, est_t, est_f,
                            src, "kept", prev)
        return Decision("targeted", f"no {missing} yet to compare the two (`repo-ai verify --record` measures "
                                    "them); running the selection", batches, est_t, est_f, src, "no-estimates")
    full_reason = (f"the full suite ({src} {est_f:.1f}s as one process) is expected to be no slower than the "
                   f"selection (~{est_t:.1f}s in {len(batches)} process(es)); it also runs every other test")
    targeted_reason = (f"the selection (~{est_t:.1f}s in {len(batches)} process(es)) is expected to be faster "
                       f"than the full suite ({src} {est_f:.1f}s)")
    # > 0: today's rule prefers the full suite by this much; < 0: the selection
    lead = est_t + TIE_MARGIN_S - est_f
    if prev is None:
        if lead >= 0:
            return Decision("full", full_reason, [], est_t, est_f, src, "compared")
        return Decision("targeted", targeted_reason, batches, est_t, est_f, src, "compared")
    margin = switch_margin(est_f if prev == "full" else est_t)
    switch = lead < -margin if prev == "full" else lead > margin
    kind = ("targeted" if prev == "full" else "full") if switch else prev
    if switch:
        why = (f"{targeted_reason if kind == 'targeted' else full_reason}; it beats the "
               f"{'full suite' if prev == 'full' else 'selection'} chosen before for this suite by more than the "
               f"switching margin ({margin:.2f}s)")
    else:
        why = (f"{'the full suite' if prev == 'full' else 'the selection'} chosen before for this unchanged suite "
               f"and environment is kept: with the selection at ~{est_t:.1f}s in {len(batches)} process(es) and "
               f"the full suite {src} {est_f:.1f}s, the other is not ahead by the switching margin ({margin:.2f}s)")
    return Decision(kind, why, batches if kind == "targeted" else [], est_t, est_f, src,
                    "switched" if switch else "kept", prev, margin)


def process_limit(estimate: float | None, cap: float, explicit: bool, floor: float = 30.0) -> float:
    """A process's time limit. With a measured estimate, a few times that
    (a run that loops forever is cut early, not after the generic limit);
    an explicit `--timeout` is always used as given. A time-out is reported
    as a failure, never as a pass."""
    if explicit or not estimate:
        return cap
    return min(cap, max(floor, 5.0 * estimate + 10.0))
