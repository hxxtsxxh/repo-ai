"""A steady run shape (C16): close estimates measured run to run must not flip
`verify --run` between the selection and the full suite for an unchanged
suite. The choice is remembered per environment and per suite identity, and
kept unless the other shape wins by a clear margin; anything that forces a
shape today still forces it.

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
    assert kinds == ["targeted"] * (len(CLOSE_FULL_TIMES) + 1)


def test_a_first_run_without_measurements_anchors_the_next_close_comparison(tmp_path: Path):
    """speed-v1 run 5, more-itertools e7331924: targeted without durations, then full at 1.4 s against 1.3 s."""
    assert _repeat(None, [0.58, 0.55], tmp_path) == ["targeted", "targeted", "targeted"]


def test_the_recorded_choice_is_kept_and_says_so():
    kept = _decide(0.65, previous="full")
    assert kept.kind == "full" and kept.basis == "kept" and kept.previous == "full"
    assert "kept" in kept.reason and "margin" in kept.reason
    data = kept.to_json()
    assert data["basis"] == "kept" and data["previous"] == "full" and data["margin_s"] == 0.25
    for k in ("kind", "reason", "batches", "est_targeted_s", "est_full_s", "est_full_source"):
        assert k in data                                     # the existing fields stay
    kept_t = _decide(0.55, previous="targeted")
    assert kept_t.kind == "targeted" and kept_t.basis == "kept" and kept_t.batches


def test_a_clear_win_still_switches():
    to_targeted = _decide(5.0, previous="full")
    assert to_targeted.kind == "targeted" and to_targeted.basis == "switched" and to_targeted.batches
    to_full = _decide(0.2, previous="targeted")
    assert to_full.kind == "full" and to_full.basis == "switched" and not to_full.batches
    # the edges of the band: 0.25 s past today's turning point either way is not yet a clear win
    assert _decide(0.85, previous="full").kind == "full"
    assert _decide(0.86, previous="full").kind == "targeted"
    assert _decide(0.36, previous="targeted").kind == "targeted"
    assert _decide(0.34, previous="targeted").kind == "full"


def test_the_margin_grows_with_the_estimates():
    """At 10 s a 0.3 s difference is noise: the margin is a fraction of the kept shape's estimate."""
    d = {f: 5.0 for f in UNIVERSE}
    base = _decide(10.0, durations=d)  # 6 files of 5 s in 4 processes: ~9.75 s
    est_t = base.est_targeted_s
    assert est_t is not None and 9 < est_t < 11
    assert base.kind == "full"                                 # within today's 0.25 s tie margin
    later = _decide(est_t + 0.25 + 1.5, previous="full", durations=d)
    assert later.kind == "full" and later.basis == "kept"      # 1.5 s past the turning point: < 20 %
    assert later.to_json()["margin_s"] >= 2.0
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


def test_without_estimates_the_recorded_choice_is_kept():
    kept = _decide(None, previous="full", durations={})
    assert kept.kind == "full" and kept.basis == "kept"
    fresh = _decide(None, durations={})
    assert fresh.kind == "targeted" and fresh.basis == "no-estimates" and strategy.steady(fresh)


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


def test_too_large_a_suite_is_not_identified(tmp_path: Path, monkeypatch):
    root = _suite(tmp_path)
    monkeypatch.setattr(cache, "MAX_SUITE_FILES", 5)
    assert cache.suite_key(root, SELECTED, UNIVERSE, 4) == ""
