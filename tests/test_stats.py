"""Synthetic fixtures for the experiment statistics (edge cases first)."""

from __future__ import annotations

import math

import pytest

from repo_ai import stats


def test_wilson_never_collapses_at_the_boundaries():
    lo, hi = stats.wilson(6, 6)
    assert hi == 1.0 and 0.60 < lo < 0.62  # 6/6 is compatible with ~61%
    lo, hi = stats.wilson(0, 10)
    assert lo == 0.0 and 0.27 < hi < 0.29
    lo, hi = stats.wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)


def test_six_perfect_pairs_are_not_zero_uncertainty_or_equivalence():
    c = stats.compare_binary([(1, 1)] * 6, label_a="baseline", label_b="core")
    assert c["diff"] == 0
    lo, hi = c["ci95"]
    assert -0.45 < lo < -0.3 and 0.3 < hi < 0.45  # wide, not [0, 0]
    assert not c["equivalent"] and c["verdict_class"] == "inconclusive"
    assert "ceiling" in c["verdict"] and "pilot" in c["verdict"]
    assert "no meaningful difference" not in c["verdict"]


def test_twelve_perfect_pairs_are_still_not_equivalence():
    c = stats.compare_binary([(1, 1)] * 12)
    assert c["verdict_class"] == "inconclusive" and not c["equivalent"]
    assert "equivalence is not shown" in c["verdict"] and "ceiling" in c["verdict"]


def test_many_agreeing_pairs_do_show_equivalence():
    c = stats.compare_binary([(1, 1)] * 150 + [(0, 0)] * 150)
    assert c["equivalent"] and c["verdict_class"] == "equivalent"
    assert c["ci90"][0] > -0.10 and c["ci90"][1] < 0.10


def test_clear_improvement_and_regression():
    better = stats.compare_binary([(0, 1)] * 15 + [(0, 0)] * 10 + [(1, 1)] * 5)
    assert better["verdict_class"] == "improvement" and better["ci95"][0] > 0
    assert better["mcnemar_p"] < 0.001
    worse = stats.compare_binary([(1, 0)] * 15 + [(0, 0)] * 10 + [(1, 1)] * 5)
    assert worse["verdict_class"] == "regression" and worse["ci95"][1] < 0


def test_balanced_discordance_is_inconclusive_not_equivalent():
    c = stats.compare_binary([(1, 0)] * 5 + [(0, 1)] * 5 + [(1, 1)] * 10)
    assert c["diff"] == 0 and c["mcnemar_p"] == 1.0
    assert c["verdict_class"] == "inconclusive" and not c["equivalent"]


def test_floor_and_empty_and_single_pair():
    floor = stats.compare_binary([(0, 0)] * 12)
    assert floor["floor"] and "floor" in floor["verdict"]
    assert stats.compare_binary([])["verdict"] == "not evaluated"
    one = stats.compare_binary([(0, 1)])
    assert one["verdict_class"] == "inconclusive" and one["ci95"][0] < 0 < one["ci95"][1]


@pytest.mark.parametrize("pairs", [
    [(1, 1)] * 3 + [(0, 1)] * 2, [(1, 0)] * 4 + [(0, 0)] * 9, [(0, 1)] * 7, [(1, 1), (0, 0), (1, 0), (0, 1)] * 5,
])
def test_newcombe_properties(pairs):
    c = stats.compare_binary(pairs)
    lo, hi = c["ci95"]
    assert -1 <= lo <= c["diff"] <= hi <= 1
    l90, h90 = c["ci90"]
    assert lo <= l90 and h90 <= hi  # 90% interval inside the 95% one


def test_newcombe_shrinks_with_more_pairs():
    w = [stats.compare_binary([(1, 1)] * n)["ci95"] for n in (6, 30, 300)]
    widths = [hi - lo for lo, hi in w]
    assert widths[0] > widths[1] > widths[2] > 0


def test_mcnemar_exact_values():
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(0, 6) == pytest.approx(0.03125)
    assert stats.mcnemar_exact(3, 3) == 1.0


def test_wilcoxon_exact_and_ties():
    assert stats.wilcoxon_signed_rank([1, 2, 3, 4, 5]) == pytest.approx(2 / 32)
    assert stats.wilcoxon_signed_rank([0, 0, 0]) == 1.0
    assert stats.wilcoxon_signed_rank([1, -1, 2, -2]) == 1.0
    tied = stats.wilcoxon_signed_rank([2, 2, 2, -1])
    assert 0 < tied <= 1
    big = stats.wilcoxon_signed_rank([float(i) for i in range(1, 41)])
    assert big < 1e-6  # normal approximation above 25 pairs


def test_continuous_paired_comparison():
    base = [172.0, 167, 143, 337, 91, 116]
    core = [120.0, 123, 73, 281, 127, 71]
    c = stats.compare_continuous(base, core, seed=1)
    assert c["pairs"] == 6 and c["lower_in_b"] == 5 and c["higher_in_b"] == 1
    lo, hi = c["median_diff_ci95"]
    assert lo <= c["median_diff"] <= hi
    assert c["wilcoxon_p"] > 0.05  # 5 of 6 lower is not significant at n=6
    assert stats.compare_continuous(base, core, seed=1) == c  # deterministic


def test_mcnemar_sample_size_planning():
    n = stats.mcnemar_pairs_needed(0.15, 0.30)
    assert 95 <= n <= 120  # a 15-point difference with 30% discordance needs ~100 paired tasks
    assert stats.mcnemar_pairs_needed(0.30, 0.40) < n  # larger effects need fewer
    with pytest.raises(ValueError):
        stats.mcnemar_pairs_needed(0.5, 0.3)


def test_detectable_effect_inverts_sample_size():
    n = stats.mcnemar_pairs_needed(0.2, 0.3)
    assert abs(stats.mcnemar_detectable_effect(n, 0.3) - 0.2) < 0.01
    assert stats.mcnemar_detectable_effect(25, 0.3) > stats.mcnemar_detectable_effect(100, 0.3)


def test_repetitions_are_clustered_by_task():
    one_rep = stats.compare_clustered({f"t{i}": [(1, 1)] for i in range(25)})
    two_reps = stats.compare_clustered({f"t{i}": [(1, 1), (1, 1)] for i in range(25)})
    naive_50 = stats.compare_binary([(1, 1)] * 50)
    assert two_reps["tasks"] == 25 and two_reps["pairs"] == 50
    # the interval is a 25-task interval, never the narrower 50-independent-pairs one
    assert two_reps["ci95"] == one_rep["ci95"]
    assert (two_reps["ci95"][1] - two_reps["ci95"][0]) > (naive_50["ci95"][1] - naive_50["ci95"][0])


def test_clustered_effect_and_sign_flip():
    # 12 tasks where B wins both repetitions, 13 where both arms always pass
    data = {**{f"w{i}": [(0, 1), (0, 1)] for i in range(12)}, **{f"s{i}": [(1, 1), (1, 1)] for i in range(13)}}
    c = stats.compare_clustered(data, label_a="baseline", label_b="core")
    assert c["verdict_class"] == "improvement" and c["permutation_p"] < 0.001 and c["ci95"][0] > 0
    assert stats.sign_flip_p([1.0] * 6) == pytest.approx(2 / 64)
    assert stats.sign_flip_p([0.5, -0.5]) == 1.0
    mixed = stats.compare_clustered({"a": [(0, 1), (1, 0)], "b": [(1, 1), (1, 1)]})
    assert mixed["verdict_class"] == "inconclusive"


def test_holm_adjustment():
    adj = stats.holm({"x": 0.01, "y": 0.04, "z": 0.03})
    assert adj == {"x": 0.03, "z": 0.06, "y": 0.06}


# -- task-clustered interval (0.7.4): coverage-verified replacement for -------
# -- Newcombe on fractional counts (docs/STATISTICS_COVERAGE.md) -------------

def test_clustered_interval_all_success_and_all_failure_never_collapse():
    for outcome in (1, 0):
        c = stats.compare_clustered({f"t{i}": [(outcome, outcome)] * 2 for i in range(25)})
        lo, hi = c["ci95"]
        assert c["diff"] == 0 and lo < 0 < hi and hi - lo > 0.15  # honest width, not [0, 0]
        assert lo == pytest.approx(-hi)  # symmetric: nothing favours either arm
        assert c["ceiling" if outcome else "floor"] and c["permutation_p"] == 1.0
    # all-success over 25 tasks: about ±10 points; the 90% interval sits just inside ±10
    assert stats.clustered_diff_ci([0.0] * 25) == pytest.approx((-0.1027, 0.1027), abs=1e-4)
    # with few tasks the interval is wide, and a pilot is never "equivalent"
    small = stats.compare_clustered({f"t{i}": [(1, 1), (1, 1)] for i in range(6)})
    assert small["ci95"][1] > 0.3 and small["verdict_class"] == "inconclusive"


def test_clustered_interval_all_discordant():
    c = stats.compare_clustered({f"t{i}": [(0, 1), (0, 1)] for i in range(25)})
    lo, hi = c["ci95"]
    assert c["diff"] == 1.0 and hi == 1.0 and 0.7 < lo < 0.9  # bounded by 1, shrunk below it
    assert c["verdict_class"] == "improvement"
    rev = stats.compare_clustered({f"t{i}": [(1, 0), (1, 0)] for i in range(25)})
    assert rev["ci95"] == [-hi, -lo] and rev["verdict_class"] == "regression"


def test_clustered_interval_mixed_repetitions():
    # some tasks lost a repetition (budget stop, invalid attempt): each task still counts once
    data = {**{f"w{i}": [(0, 1), (0, 1)] for i in range(5)}, **{f"h{i}": [(0, 1)] for i in range(3)},
            **{f"f{i}": [(0, 1), (1, 1), (0, 0)] for i in range(4)}, **{f"s{i}": [(1, 1)] for i in range(13)}}
    c = stats.compare_clustered(data)
    diffs = [1.0] * 8 + [1 / 3] * 4 + [0.0] * 13
    assert c["tasks"] == 25 and c["pairs"] == 5 * 2 + 3 + 4 * 3 + 13
    assert c["diff"] == pytest.approx(sum(diffs) / 25, abs=1e-4)
    assert c["ci95"] == [round(v, 4) for v in stats.clustered_diff_ci(diffs)]
    assert c["mcnemar_p"] is None  # McNemar needs one run per task
    lo, hi = c["ci95"]
    assert lo > 0 and lo < c["diff"] < hi
    # the width follows the between-task spread: the same mean from tasks that each split
    # their repetitions is more precise than from a few all-or-nothing tasks
    flaky = stats.clustered_diff_ci([0.5] * 10 + [0.0] * 15)
    split = stats.clustered_diff_ci([1.0] * 5 + [0.0] * 20)
    assert flaky[1] - flaky[0] < split[1] - split[0]  # same mean, less between-task spread


def test_clustered_interval_with_one_run_per_task_is_bonett_price():
    # Bonett & Price (2012): p12~ = (n12+1)/(n+2), p21~ = (n21+1)/(n+2)
    n, n12, n21 = 30, 3, 9
    p12, p21 = (n12 + 1) / (n + 2), (n21 + 1) / (n + 2)
    se = math.sqrt((p12 + p21 - (p21 - p12) ** 2) / (n + 2))
    diffs = [-1.0] * n12 + [1.0] * n21 + [0.0] * (n - n12 - n21)
    lo, hi = stats.clustered_diff_ci(diffs)
    assert lo == pytest.approx(p21 - p12 - stats.Z95 * se) and hi == pytest.approx(p21 - p12 + stats.Z95 * se)
    pairs = {f"t{i}": [(int(x < 0), int(x > 0))] for i, x in enumerate(diffs)}
    c = stats.compare_clustered(pairs)
    assert c["mcnemar_p"] == round(stats.mcnemar_exact(n12, n21), 4)
    assert c["permutation_p"] == pytest.approx(c["mcnemar_p"], abs=1e-3)  # the same exact test


def test_clustered_interval_coverage_where_newcombe_fractional_failed():
    # seeded, pure-Python miniature of the coverage study: 10 near-deterministic
    # tasks, one run each, true difference about +0.13 (the study's worst cell
    # for the 0.7.3 method, which covered about 85% there)
    import random
    rng = random.Random(2026)

    def expit(x):
        return 1 / (1 + math.exp(-x))
    truth_draws = [rng.gauss(0, 4) for _ in range(200_000)]
    truth = sum(expit(u + 1.5) - expit(u) for u in truth_draws) / len(truth_draws)
    hits_new = hits_old = 0
    sims = 3000
    for _ in range(sims):
        diffs, cells = [], [0, 0, 0, 0]
        for _ in range(10):
            u = rng.gauss(0, 4)
            x, y = rng.random() < expit(u), rng.random() < expit(u + 1.5)
            diffs.append(float(y) - float(x))
            cells[(not x) * 2 + (not y)] += 1  # both, A only, B only, neither
        lo, hi = stats.clustered_diff_ci(diffs)
        hits_new += lo <= truth <= hi
        lo, hi = stats.newcombe_paired(cells[0], cells[1], cells[2], cells[3])
        hits_old += lo <= truth <= hi
    assert hits_new / sims >= 0.94 and hits_old / sims < 0.90
