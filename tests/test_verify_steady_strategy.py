"""A steady run shape (C16): close estimates measured run to run must not flip
`verify --run` between the selection and the full suite for an unchanged
suite. The choice is remembered per environment and per suite identity. A
remembered full suite is kept unless the selection is clearly faster; a
remembered selection never stands in the way of the full suite (it reports
more: failing files outside the selection, `selected-and-full-suite-passed`),
and a selection run only because nothing was measured is not remembered.
Anything that forces a shape today still forces it.

Unit tests only: the decision and the cache, no sandbox and no test run.
"""

from __future__ import annotations

from pathlib import Path

from repo_ai.verify import cache, strategy
from repo_ai.verify.runner import parse_command

RUNNER = parse_command("python -m unittest discover -s tests -t .")
UNIVERSE = [f"tests/test_{i}.py" for i in range(10)]
SELECTED = UNIVERSE[:6]
DURATIONS = {f: 0.3 for f in UNIVERSE}
# six 0.3 s files in four processes with a 0.25 s process cost: the selection is estimated at 0.35 s, so
# today's rule (full when est_full <= est_targeted + 0.25) turns at a full suite of 0.6 s
KW = dict(full_required=False, full_requested=False, workers=4, measured_startup=0.25, full_runnable=True)
CLOSE_FULL_TIMES = [0.55, 0.65, 0.58, 0.7, 0.52, 0.68]   # tenths of a second around the turning point


def _decide(measured_full: float | None, previous: str | None = None, **over) -> strategy.Decision:
    return strategy.decide(RUNNER, over.pop("selected", SELECTED), UNIVERSE, over.pop("durations", DURATIONS),
                           measured_full=measured_full, previous=previous, **{**KW, **over})


def test_without_a_recorded_choice_close_estimates_flip_the_shape():
    """What speed-v1 run 5 recorded: the same suite, shapes alternating on tenths of a second."""
    kinds = {_decide(t).kind for t in CLOSE_FULL_TIMES}
    assert kinds == {"full", "targeted"}
    assert all(_decide(t).basis == "compared" for t in CLOSE_FULL_TIMES)


def _repeat(first: float | None, times: list[float], tmp_path: Path, key: str = "suite") -> list[str]:
    """Consecutive runs on one unchanged suite, each recording its choice the way the engine does."""
    kinds = []
    for t in [first, *times]:
        timings = cache.Timings(tmp_path, "env")
        d = _decide(t, previous=timings.choice(key)) if t is not None else \
            _decide(None, previous=timings.choice(key), durations={})
        if strategy.steady(d):
            timings.note_choice(key, d.kind)
        timings.save()
        kinds.append(d.kind)
    return kinds


def test_close_estimates_no_longer_flip_the_shape_across_runs(tmp_path: Path):
    kinds = _repeat(CLOSE_FULL_TIMES[0], CLOSE_FULL_TIMES[1:], tmp_path)
    assert kinds == ["full"] * len(CLOSE_FULL_TIMES)
    other = tmp_path / "other"
    kinds = _repeat(CLOSE_FULL_TIMES[1], CLOSE_FULL_TIMES, other)   # starts on the selection's side
    # the first close call that favours the full suite moves to it, and it stays there
    assert kinds == ["targeted"] + ["full"] * len(CLOSE_FULL_TIMES)


def test_a_run_without_measurements_is_not_remembered(tmp_path: Path):
    """A selection run only because nothing was measured yet must not hold back the full suite later
    (speed-v1 run 5, more-itertools e7331924: targeted without durations, then full at 1.4 s against 1.3 s)."""
    first = _decide(None, durations={})
    assert first.kind == "targeted" and first.basis == "no-estimates" and not strategy.steady(first)
    assert _repeat(None, [0.58, 0.55], tmp_path) == ["targeted", "full", "full"]
    assert cache.Timings(tmp_path, "env").choice("suite") == "full"
    # the review's case: 5 s files, a full suite 0.5 s faster than the selection after a no-estimates run
    d = {f: 5.0 for f in UNIVERSE}
    assert _repeat(None, [], tmp_path / "big") == ["targeted"]
    t = cache.Timings(tmp_path / "big", "env")
    assert t.choice("suite") is None
    later = _decide(None, durations=d, previous=t.choice("suite"))
    assert later.kind == "targeted"                         # still nothing to compare: the selection
    est_t = _decide(100.0, durations=d).est_targeted_s
    assert est_t is not None
    assert _decide(est_t - 0.5, durations=d, previous=t.choice("suite")).kind == "full"


def test_a_remembered_selection_yields_to_the_full_suite_at_the_plain_tie_rule():
    for full in CLOSE_FULL_TIMES + [0.6, 0.61, 0.2, 5.0]:
        fresh, remembered = _decide(full), _decide(full, previous="targeted")
        assert (remembered.kind, remembered.basis) == (fresh.kind, fresh.basis) == (fresh.kind, "compared")
        assert remembered.previous == "targeted" and remembered.margin_s is None
    assert _decide(0.6, previous="targeted").kind == "full"           # est_full <= est_targeted + 0.25
    assert _decide(0.61, previous="targeted").kind == "targeted"


def test_a_remembered_full_suite_is_kept_and_says_so():
    kept = _decide(0.65, previous="full")
    assert kept.kind == "full" and kept.basis == "kept" and kept.previous == "full" and not kept.batches
    assert "kept" in kept.reason and "0.30s faster" in kept.reason and "0.50s needed" in kept.reason
    assert "these unchanged test files" in kept.reason
    data = kept.to_json()
    assert data["basis"] == "kept" and data["previous"] == "full" and data["margin_s"] == 0.5
    for k in ("kind", "reason", "batches", "est_targeted_s", "est_full_s", "est_full_source"):
        assert k in data                                     # the existing fields stay
    plain = _decide(0.55, previous="full")                   # the rule alone picks the full suite
    assert plain.kind == "full" and plain.basis == "compared"


def test_a_clearly_faster_selection_still_replaces_a_remembered_full_suite():
    to_targeted = _decide(5.0, previous="full")
    assert to_targeted.kind == "targeted" and to_targeted.basis == "switched" and to_targeted.batches
    assert strategy.steady(to_targeted)                      # remembered: it replaces the full suite
    # the edge: the selection must be more than 0.25 s + max(0.25 s, 20 %) faster, by the raw difference
    assert _decide(0.85, previous="full").kind == "full"
    assert _decide(0.86, previous="full").kind == "targeted"


def test_the_reason_states_the_raw_difference_and_the_threshold_it_was_compared_with():
    """The review's cases, at 5 s: the stated numbers are the ones the decision compared."""
    d = {f: 5.0 for f in UNIVERSE}
    sel = [UNIVERSE[0]]
    est_t = _decide(100.0, durations=d, selected=sel).est_targeted_s
    assert est_t == 5.0
    to_full = _decide(4.2, durations=d, selected=sel, previous="targeted")
    assert to_full.kind == "full" and to_full.basis == "compared" and "beats" not in to_full.reason
    kept = _decide(6.4, durations=d, selected=sel, previous="full")
    need = 0.25 + 0.2 * 6.4
    assert kept.kind == "full" and kept.basis == "kept" and kept.to_json()["margin_s"] == round(need, 2)
    assert "1.40s faster" in kept.reason and f"{need:.2f}s needed" in kept.reason
    switched = _decide(6.6, durations=d, selected=sel, previous="full")
    assert switched.kind == "targeted" and switched.basis == "switched"
    assert "by 1.60s" in switched.reason and f"{0.25 + 0.2 * 6.6:.2f}s needed" in switched.reason


def test_the_margin_grows_with_the_estimates():
    """At 10 s a 0.3 s difference is noise: the margin is a fraction of the kept shape's estimate."""
    d = {f: 5.0 for f in UNIVERSE}
    base = _decide(10.0, durations=d)  # 6 files of 5 s in 4 processes: ~9.75 s
    est_t = base.est_targeted_s
    assert est_t is not None and 9 < est_t < 11
    assert base.kind == "full"                                 # within today's 0.25 s tie margin
    later = _decide(est_t + 0.25 + 1.5, previous="full", durations=d)
    assert later.kind == "full" and later.basis == "kept"      # 1.5 s past the turning point: < 20 %
    assert later.to_json()["margin_s"] >= 2.25
    assert _decide(est_t + 0.25 + 3.0, previous="full", durations=d).kind == "targeted"


def test_a_condition_that_forces_a_shape_overrides_the_recorded_choice():
    unusable = _decide(0.55, previous="full", full_unusable="interrupted at collection")
    assert unusable.kind == "targeted" and unusable.basis == "forced" and "cannot be attributed" in unusable.reason
    required = _decide(30.0, previous="targeted", full_required=True)
    assert required.kind == "full" and required.basis == "forced"
    requested = _decide(30.0, previous="targeted", full_requested=True)
    assert requested.kind == "full" and requested.basis == "forced"
    not_runnable = _decide(0.55, previous="full", full_runnable=False)
    assert not_runnable.kind == "targeted" and not_runnable.basis == "forced"
    nothing = _decide(0.55, previous="full", selected=[])
    assert nothing.kind == "none"
    opaque = strategy.decide(parse_command("npm test"), [], [], {}, measured_full=None, previous="targeted", **KW)
    assert opaque.kind == "full" and opaque.basis == "forced"
    for d in (unusable, required, requested, not_runnable, nothing, opaque):
        assert not strategy.steady(d)                        # never recorded as the suite's choice


def test_without_estimates_a_remembered_full_suite_is_kept():
    kept = _decide(None, previous="full", durations={})
    assert kept.kind == "full" and kept.basis == "kept" and strategy.steady(kept)
    sel = _decide(None, previous="targeted", durations={})
    assert sel.kind == "targeted" and sel.basis == "no-estimates" and not strategy.steady(sel)


def _suite(tmp_path: Path) -> Path:
    for f in UNIVERSE:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text(f"# {f}\n")
    return tmp_path


def test_a_changed_suite_input_invalidates_the_recorded_choice(tmp_path: Path):
    root = _suite(tmp_path / "repo")
    key = cache.suite_key(root, SELECTED, UNIVERSE, 4)
    assert key and key == cache.suite_key(root, list(reversed(SELECTED)), UNIVERSE, 4)
    t = cache.Timings(tmp_path / "state", "env")
    t.note_choice(key, "full")
    t.save()
    assert cache.Timings(tmp_path / "state", "env").choice(key) == "full"
    assert cache.Timings(tmp_path / "state", "other-env").choice(key) is None   # another environment
    others = [cache.suite_key(root, SELECTED[:5], UNIVERSE, 4),                  # another selection
              cache.suite_key(root, SELECTED, UNIVERSE[:9], 4),                  # a test file fewer
              cache.suite_key(root, SELECTED, UNIVERSE, 2)]                      # other parallelism
    (root / UNIVERSE[8]).write_text("# edited\n")                                 # a test file's content
    others.append(cache.suite_key(root, SELECTED, UNIVERSE, 4))
    assert len(set(others) | {key}) == len(others) + 1
    for k in others:
        assert cache.Timings(tmp_path / "state", "env").choice(k) is None
        d = _decide(0.65, previous=cache.Timings(tmp_path / "state", "env").choice(k))
        assert d.kind == "targeted" and d.basis == "compared"                     # today's rule again


def test_recorded_choices_are_bounded_and_ignore_bad_values(tmp_path: Path):
    t = cache.Timings(tmp_path, "env")
    for i in range(cache.MAX_STRATEGY_CHOICES + 5):
        t.note_choice(f"k{i}", "full")
    t.note_choice("bad", "none")                             # only the two speed-equivalent shapes are kept
    t.save()
    again = cache.Timings(tmp_path, "env")
    assert again.choice("bad") is None
    assert again.choice(f"k{cache.MAX_STRATEGY_CHOICES + 4}") == "full"
    assert sum(again.choice(f"k{i}") is not None for i in range(cache.MAX_STRATEGY_CHOICES + 5)) \
        == cache.MAX_STRATEGY_CHOICES
    assert again.choice("") is None
    assert cache.suite_key(tmp_path, [], [], 4) != ""


def test_a_malformed_timings_file_is_ignored_not_fatal(tmp_path: Path):
    import json
    bad_envs = [{"choices": [1]}, {"choices": "x"}, {"choice_seq": "x"}, {"choice_seq": -3},
                {"choices": {"a": {"k": "full", "n": "x"}, "b": "x", "c": {"k": "none"}}}, {"choice_seq": True}]
    for bad in bad_envs:
        (tmp_path / cache.TIMINGS_FILE).write_text(json.dumps({"version": 1, "envs": {"e": bad}}))
        t = cache.Timings(tmp_path, "e")
        assert t.choice("a") in {None, "full"} and t.choice("b") is None and t.choice("c") is None
        for i in range(cache.MAX_STRATEGY_CHOICES + 2):
            t.note_choice(f"s{i}", "full")
        t.save()
        again = cache.Timings(tmp_path, "e")
        assert again.choice(f"s{cache.MAX_STRATEGY_CHOICES + 1}") == "full", bad
        assert len(again.env["choices"]) == cache.MAX_STRATEGY_CHOICES


def test_too_large_a_suite_is_not_identified(tmp_path: Path, monkeypatch):
    root = _suite(tmp_path)
    monkeypatch.setattr(cache, "MAX_SUITE_FILES", 5)
    assert cache.suite_key(root, SELECTED, UNIVERSE, 4) == ""
