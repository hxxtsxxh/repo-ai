"""Statistics for paired coding experiments (pure Python, deterministic).

What each comparison reports, and why:

* **Per-arm success rates** with Wilson score intervals. Unlike the normal
  approximation, these never collapse to zero width at 0% or 100% (6/6 is
  compatible with a true rate as low as ~61%).
* **Paired difference in success** with Newcombe's hybrid score interval for
  paired proportions (Newcombe 1998, method 10). It stays honest when every
  pair agrees: six all-success pairs give about ±39 points, not [0, 0]. The
  bootstrap percentile interval this replaces did collapse.
* **Exact McNemar test** on the discordant pairs (the only pairs that carry
  information about a difference).
* **Repeated tasks** (`compare_clustered`): the task is the unit. Each
  task's repetitions are averaged; the interval is a task-clustered
  Bonett-Price adjusted Wald interval (`clustered_diff_ci`), whose coverage
  was verified by simulation, and the test is a sign-flip permutation test.
* **Equivalence** only via TOST (two one-sided tests): the 90% interval must
  lie inside ±margin. *Observing* equal rates is not evidence
  of equivalence. With few tasks, equal rates are expected even when the
  arms differ.
* **Ceiling and floor flags**: when both arms solve nearly everything (or
  nothing), the task set cannot discriminate, and the verdict says so.
* **Continuous paired metrics** (tokens, cost, tool calls, runtime): mean and
  median paired difference, its standard deviation, a seeded bootstrap 95%
  interval for the median difference, and an exact Wilcoxon signed-rank
  p-value (normal approximation above 25 non-zero pairs).
"""

from __future__ import annotations

import math
import random
from typing import Any

Z95 = 1.959963984540054
Z90 = 1.6448536269514722
MIN_PAIRS = 10            # below this, a comparison is a pilot: never "supported"
EQUIVALENCE_MARGIN = 0.10  # ±10 percentage points
CEILING = 0.95


def wilson(k: float, n: float, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe_paired(a: float, b: float, c: float, d: float, z: float = Z95) -> tuple[float, float]:
    """Interval for p_B - p_A from a 2x2 paired table:
    a = both succeed, b = only A succeeds, c = only B succeeds, d = both fail."""
    n = a + b + c + d
    if n == 0:
        return (-1.0, 1.0)
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n, z)
    l2, u2 = wilson(a + c, n, z)
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    phi = (a * d - b * c) / math.sqrt(denom) if denom > 0 else 0.0
    diff = p2 - p1
    dl = math.sqrt(max(0.0, (p2 - l2) ** 2 - 2 * phi * (p2 - l2) * (u1 - p1) + (u1 - p1) ** 2))
    du = math.sqrt(max(0.0, (u2 - p2) ** 2 - 2 * phi * (u2 - p2) * (p1 - l1) + (p1 - l1) ** 2))
    return (max(-1.0, diff - dl), min(1.0, diff + du))


def clustered_diff_ci(diffs: list[float], z: float = Z95) -> tuple[float, float]:
    """Interval for the mean task-level difference in success, mean(p_B - p_A),
    when each task contributes the average of its repetitions (diffs in [-1, 1]).

    Bonett & Price's (2012) adjusted Wald interval for paired proportions,
    generalised to task clusters: one pseudo-task with difference +1 and one
    with -1 are added, and the variance is the between-task spread of the
    task-averaged differences (so repetitions add precision only as far as
    they actually reduce that spread, and tasks are never treated as more
    than one unit each). With one run per task it is exactly Bonett-Price.

    The pseudo-tasks keep the interval honest when every task agrees (all
    success, all failure, all discordant): it never collapses to zero width.
    Frequentist coverage was checked by simulation (docs/STATISTICS_COVERAGE.md):
    at least 94.9% for a nominal 95% across 10-50 tasks, 1-3 or mixed
    repetitions, base rates 0.1-0.95 and near-deterministic tasks, where the
    Newcombe interval on fractional counts fell to 85% with one repetition and
    was over-conservative (about 99%) with two or more."""
    n = len(diffs)
    if n == 0:
        return (-1.0, 1.0)
    n2 = n + 2
    mean = sum(diffs) / n2
    ss = sum((x - mean) ** 2 for x in diffs) + (1 - mean) ** 2 + (1 + mean) ** 2
    half = z * math.sqrt(ss) / n2
    return (max(-1.0, mean - half), min(1.0, mean + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pair counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def cohen_h(p1: float, p2: float) -> float:
    return 2 * math.asin(math.sqrt(p2)) - 2 * math.asin(math.sqrt(p1))


def compare_binary(pairs: list[tuple[int, int]], margin: float = EQUIVALENCE_MARGIN,
                   label_a: str = "A", label_b: str = "B") -> dict[str, Any]:
    """Paired success comparison of arm B against arm A."""
    n = len(pairs)
    if n == 0:
        return {"pairs": 0, "verdict": "not evaluated", "verdict_class": "not evaluated"}
    a = sum(1 for x, y in pairs if x and y)
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if y and not x)
    d = n - a - b - c
    pa, pb = (a + b) / n, (a + c) / n
    ci95 = newcombe_paired(a, b, c, d, Z95)
    ci90 = newcombe_paired(a, b, c, d, Z90)
    p = mcnemar_exact(b, c)
    equivalent = n >= MIN_PAIRS and -margin < ci90[0] and ci90[1] < margin
    ceiling = pa >= CEILING and pb >= CEILING
    floor = pa <= 1 - CEILING and pb <= 1 - CEILING
    diff = pb - pa
    if n < MIN_PAIRS:
        cls = "inconclusive"
        verdict = f"inconclusive (pilot: {n} < {MIN_PAIRS} paired tasks)"
    elif p < 0.05 and ci95[0] > 0:
        cls, verdict = "improvement", f"{label_b} better than {label_a} (statistically supported)"
    elif p < 0.05 and ci95[1] < 0:
        cls, verdict = "regression", f"{label_b} worse than {label_a} (statistically supported)"
    elif equivalent:
        cls, verdict = "equivalent", f"equivalent within ±{margin:.0%} (TOST, 90% CI inside the margin)"
    else:
        cls = "inconclusive"
        verdict = ("inconclusive: no difference observed, but equivalence is not shown"
                   if b == c else f"inconclusive: directional ({diff:+.0%}), not significant")
    if ceiling or floor:
        verdict += (f"; {'ceiling' if ceiling else 'floor'} effect: both arms "
                    f"{'≥' if ceiling else '≤'}{(CEILING if ceiling else 1 - CEILING):.0%} — "
                    "these tasks cannot discriminate between the arms")
    return {"pairs": n, "table": {"both": a, f"{label_a}_only": b, f"{label_b}_only": c, "neither": d},
            "success_a": round(pa, 4), "success_b": round(pb, 4),
            "wilson_a": [round(v, 4) for v in wilson(a + b, n)],
            "wilson_b": [round(v, 4) for v in wilson(a + c, n)],
            "diff": round(diff, 4), "ci95": [round(v, 4) for v in ci95],
            "ci90": [round(v, 4) for v in ci90], "mcnemar_p": round(p, 4),
            "cohens_h": round(cohen_h(pa, pb), 3), "equivalence_margin": margin,
            "equivalent": equivalent, "ceiling": ceiling, "floor": floor,
            "verdict": verdict, "verdict_class": cls}


# --------------------------------------------------------------------------
# continuous paired metrics
# --------------------------------------------------------------------------
def _median(values: list[float]) -> float:
    s = sorted(values)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def wilcoxon_signed_rank(diffs: list[float]) -> float:
    """Two-sided p-value. Zero differences are dropped (Wilcoxon's method);
    tied magnitudes get mid-ranks. Exact (by enumeration over doubled ranks)
    up to 25 non-zero pairs, normal approximation above."""
    nz = [x for x in diffs if x != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(nz[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(nz[order[j + 1]]) == abs(nz[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, nz, strict=True) if x > 0)
    total = sum(ranks)
    if n <= 25:
        doubled = [int(round(2 * r)) for r in ranks]
        counts: dict[int, int] = {0: 1}
        for r in doubled:
            nxt: dict[int, int] = dict(counts)
            for s, cnt in counts.items():
                nxt[s + r] = nxt.get(s + r, 0) + cnt
            counts = nxt
        observed = int(round(2 * w_plus))
        mirror = int(round(2 * total)) - observed
        lo, hi = min(observed, mirror), max(observed, mirror)
        extreme = sum(cnt for s, cnt in counts.items() if s <= lo or s >= hi)
        return min(1.0, extreme / 2 ** n)
    mean = total / 2
    sd = math.sqrt(sum(r * r for r in ranks) / 4)
    z = (abs(w_plus - mean) - 0.5) / sd if sd else 0.0
    return min(1.0, math.erfc(z / math.sqrt(2)))


def compare_continuous(a_values: list[float], b_values: list[float], seed: int = 0,
                       rounds: int = 4000) -> dict[str, Any]:
    """Paired B − A differences of a continuous metric (same task order)."""
    diffs = [b - a for a, b in zip(a_values, b_values, strict=True)]
    n = len(diffs)
    if n == 0:
        return {"pairs": 0}
    mean = sum(diffs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in diffs) / (n - 1)) if n > 1 else None
    rng = random.Random(seed)
    meds = sorted(_median([diffs[rng.randrange(n)] for _ in range(n)]) for _ in range(rounds))
    base = _median(a_values) if a_values else 0
    return {"pairs": n, "mean_diff": round(mean, 4), "median_diff": round(_median(diffs), 4),
            "sd_diff": round(sd, 4) if sd is not None else None,
            "median_diff_ci95": [round(meds[int(0.025 * rounds)], 4), round(meds[int(0.975 * rounds) - 1], 4)],
            "relative_median_diff": round(_median(diffs) / base, 4) if base else None,
            "lower_in_b": sum(1 for x in diffs if x < 0), "higher_in_b": sum(1 for x in diffs if x > 0),
            "wilcoxon_p": round(wilcoxon_signed_rank(diffs), 4)}


def mcnemar_pairs_needed(delta: float, p_discordant: float, alpha: float = 0.05,
                         power: float = 0.8) -> int:
    """Paired tasks needed to detect a success-rate difference `delta` with
    McNemar's test (Connor 1987), given the expected share of discordant
    pairs. Planning arithmetic only: a real experiment reports what it got."""
    from statistics import NormalDist
    if not 0 < abs(delta) < p_discordant <= 1:
        raise ValueError("need 0 < |delta| < p_discordant <= 1")
    za = NormalDist().inv_cdf(1 - alpha / 2)
    zb = NormalDist().inv_cdf(power)
    n = (za * math.sqrt(p_discordant) + zb * math.sqrt(p_discordant - delta * delta)) ** 2 / (delta * delta)
    return math.ceil(n)


def mcnemar_detectable_effect(pairs: int, p_discordant: float, alpha: float = 0.05,
                              power: float = 0.8) -> float:
    """Smallest success-rate difference `pairs` paired tasks can detect (the
    inverse of `mcnemar_pairs_needed`, by bisection)."""
    lo, hi = 1e-4, p_discordant - 1e-6
    if mcnemar_pairs_needed(hi, p_discordant, alpha, power) > pairs:
        return float("nan")  # even the largest possible effect needs more pairs
    for _ in range(60):
        mid = (lo + hi) / 2
        if mcnemar_pairs_needed(mid, p_discordant, alpha, power) > pairs:
            lo = mid
        else:
            hi = mid
    return round(hi, 3)


# --------------------------------------------------------------------------
# repeated measurements: the task is the unit of analysis
# --------------------------------------------------------------------------
def sign_flip_p(diffs: list[float], seed: int = 0, rounds: int = 200_000) -> float:
    """Two-sided paired permutation test of mean(diffs) == 0 (each task's
    difference may flip sign under H0). Exact for up to 20 non-zero tasks,
    seeded Monte Carlo above."""
    nz = [d for d in diffs if d != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    observed = abs(sum(nz))
    if n <= 20:
        hits = 0
        for mask in range(1 << n):
            s = sum(-d if mask >> i & 1 else d for i, d in enumerate(nz))
            hits += abs(s) >= observed - 1e-12
        return min(1.0, hits / (1 << n))
    rng = random.Random(seed)
    hits = sum(abs(sum(d if rng.random() < 0.5 else -d for d in nz)) >= observed - 1e-12
               for _ in range(rounds))
    return min(1.0, (hits + 1) / (rounds + 1))


def compare_clustered(by_task: dict[str, list[tuple[int, int]]], margin: float = EQUIVALENCE_MARGIN,
                      label_a: str = "A", label_b: str = "B", seed: int = 0) -> dict[str, Any]:
    """Paired success comparison by task (the pre-registered primary analysis).
    Repetitions of a task are averaged first, so the effective sample size is
    the number of tasks, never the number of runs. Interval: `clustered_diff_ci`;
    test: exact (or Monte Carlo) sign-flip permutation on the task differences.
    `compare_binary` (Newcombe, McNemar) is the ordinary unclustered analysis."""
    tasks = {t: pairs for t, pairs in by_task.items() if pairs}
    if not tasks:
        return {"pairs": 0, "tasks": 0, "verdict": "not evaluated", "verdict_class": "not evaluated"}
    n = len(tasks)
    # fractional 2x2 counts at the task level: each task contributes one unit
    a = b = c = d = 0.0
    diffs: list[float] = []
    succ_a = succ_b = 0.0
    for pairs in tasks.values():
        k = len(pairs)
        a += sum(1 for x, y in pairs if x and y) / k
        b += sum(1 for x, y in pairs if x and not y) / k
        c += sum(1 for x, y in pairs if y and not x) / k
        d += sum(1 for x, y in pairs if not x and not y) / k
        pa_t, pb_t = sum(x for x, _ in pairs) / k, sum(y for _, y in pairs) / k
        succ_a += pa_t
        succ_b += pb_t
        diffs.append(pb_t - pa_t)
    pa, pb = succ_a / n, succ_b / n
    ci95 = clustered_diff_ci(diffs, Z95)
    ci90 = clustered_diff_ci(diffs, Z90)
    p = sign_flip_p(diffs, seed)  # with one run per task: the exact McNemar test
    equivalent = n >= MIN_PAIRS and -margin < ci90[0] and ci90[1] < margin
    ceiling = pa >= CEILING and pb >= CEILING
    floor = pa <= 1 - CEILING and pb <= 1 - CEILING
    diff = pb - pa
    if n < MIN_PAIRS:
        cls, verdict = "inconclusive", f"inconclusive (pilot: {n} < {MIN_PAIRS} tasks)"
    elif p < 0.05 and ci95[0] > 0:
        cls, verdict = "improvement", f"{label_b} better than {label_a} (statistically supported)"
    elif p < 0.05 and ci95[1] < 0:
        cls, verdict = "regression", f"{label_b} worse than {label_a} (statistically supported)"
    elif equivalent:
        cls, verdict = "equivalent", f"equivalent within ±{margin:.0%} (TOST, 90% CI inside the margin)"
    else:
        cls = "inconclusive"
        verdict = ("inconclusive: no difference observed, but equivalence is not shown"
                   if abs(diff) < 1e-12 else
                   f"inconclusive: directional ({diff:+.0%}), not significant")
    if ceiling or floor:
        verdict += (f"; {'ceiling' if ceiling else 'floor'} effect: both arms "
                    f"{'≥' if ceiling else '≤'}{(CEILING if ceiling else 1 - CEILING):.0%}")
    runs = sum(len(p) for p in tasks.values())
    return {"pairs": runs, "tasks": n, "runs_per_task": round(runs / n, 2),
            "method": "task-clustered (repetitions averaged per task; adjusted Wald interval, "
                      "Bonett-Price; sign-flip permutation test)",
            "success_a": round(pa, 4), "success_b": round(pb, 4),
            "wilson_a": [round(v, 4) for v in wilson(succ_a, n)],
            "wilson_b": [round(v, 4) for v in wilson(succ_b, n)],
            "diff": round(diff, 4), "ci95": [round(v, 4) for v in ci95], "ci90": [round(v, 4) for v in ci90],
            "permutation_p": round(p, 4),
            "mcnemar_p": round(mcnemar_exact(round(b), round(c)), 4) if runs == n else None,
            "table": {"both": round(a, 2), f"{label_a}_only": round(b, 2), f"{label_b}_only": round(c, 2),
                      "neither": round(d, 2)},
            "cohens_h": round(cohen_h(pa, pb), 3), "equivalence_margin": margin, "equivalent": equivalent,
            "ceiling": ceiling, "floor": floor, "verdict": verdict, "verdict_class": cls}


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values (family-wise error control)."""
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ordered)
    out: dict[str, float] = {}
    running = 0.0
    for i, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - i) * p))
        out[name] = round(running, 4)
    return out
