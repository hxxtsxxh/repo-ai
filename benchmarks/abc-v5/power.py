"""Planning arithmetic for abc-v5 (exact, enumerated; no simulation, no randomness).

``python power.py``          print the tables quoted in PREREGISTRATION.md section 9
``python power.py --json``   the same numbers as JSON

Everything here is planning arithmetic. The study reports what it observes, not these numbers.

P1 (false-green acceptance, primary pair per task). Under phase 1 every primary candidate is an authored decoy that the
naive rule A accepts by construction, so c (A rejects, B accepts) is 0 and the exact two-sided McNemar test reduces to
p = 2 * 0.5**b, where b is the number of tasks whose primary decoy B does NOT accept. p < 0.05 needs b >= 6. The
decision rule additionally needs the Bonett-Price 95% interval of the task differences to exclude 0 (the repo's
``repo_ai.stats.compare_clustered`` rule), which with c = 0 holds whenever b >= 6 for n <= 40 (checked below).

P2 (cost on correct candidates). B's non-acceptance rate (REJECT + ABSTAIN) on the reference candidate of each task must
have a point estimate <= 0.20 AND a one-sided 95% Clopper-Pearson upper bound <= 0.40.
"""
from __future__ import annotations

import json
import math
import sys

ALPHA = 0.05
NS = (12, 16, 20, 24, 30, 40)


def binom_pmf(k: int, n: int, p: float) -> float:
    return math.comb(n, k) * p ** k * (1 - p) ** (n - k)


def mcnemar_two_sided(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def bonett_price_lower(n: int, b: int, c: int, z: float = 1.959963984540054) -> float:
    """Lower 95% bound of mean(B_not_accept - ...) as in repo_ai.stats.clustered_diff_ci, one run per task.
    Task difference = +1 if only A accepts the false green (B avoids it), -1 if only B accepts, else 0."""
    diffs = [1.0] * b + [-1.0] * c + [0.0] * (n - b - c)
    n2 = n + 2
    mean = sum(diffs) / n2
    ss = sum((x - mean) ** 2 for x in diffs) + (1 - mean) ** 2 + (1 + mean) ** 2
    return mean - z * math.sqrt(ss) / n2


def p1_success(n: int, b: int, c: int) -> bool:
    return mcnemar_two_sided(b, c) < ALPHA and bonett_price_lower(n, b, c) > 0


def p1_power(n: int, p10: float, p01: float = 0.0) -> float:
    """Exact power: multinomial over (b, c, rest) with P(b-cell) = p10, P(c-cell) = p01."""
    total = 0.0
    for b in range(n + 1):
        for c in range(n - b + 1):
            if not p1_success(n, b, c):
                continue
            rest = n - b - c
            total += (math.factorial(n) / (math.factorial(b) * math.factorial(c) * math.factorial(rest))
                      * p10 ** b * p01 ** c * (1 - p10 - p01) ** rest)
    return total


def min_b(n: int) -> int | None:
    for b in range(n + 1):
        if p1_success(n, b, 0):
            return b
    return None


def beta_cdf_upper(x: int, n: int, conf: float = 0.95) -> float:
    """One-sided Clopper-Pearson upper bound for x successes out of n (bisection on the binomial tail)."""
    if x >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        tail = sum(binom_pmf(k, n, mid) for k in range(x + 1))   # P(X <= x | p = mid)
        if tail > 1 - conf:
            lo = mid
        else:
            hi = mid
    return hi


def p2_pass(x: int, n: int) -> bool:
    return x / n <= 0.20 and beta_cdf_upper(x, n) <= 0.40


def p2_power(n: int, phi: float) -> float:
    return sum(binom_pmf(x, n, phi) for x in range(n + 1) if p2_pass(x, n))


def p2_max_x(n: int) -> int:
    return max(x for x in range(n + 1) if p2_pass(x, n)) if any(p2_pass(x, n) for x in range(n + 1)) else -1


def coupled_joint_power(n: int, g: float, q: float, s: float = 0.0) -> dict:
    """Exact power of P1 AND P2 when they share a cause (section 6 of the preregistration).

    Per task: with probability g the task's requirement map has a gap (an UNMAPPED / NOT_DISCRIMINATING requirement);
    then B abstains on every candidate of that task, so it 'catches' the decoy AND abstains on the reference.
    Without a gap, B catches the primary decoy while accepting the reference with probability s + (1 - s) * q, where
    s is the share of process-type primaries (always caught) and q the probability of a candidate-dependent catch of
    a semantic decoy. Under a pure gap mechanism q = 0 and, in the semantic stratum (s = 0), b == x on every task."""
    pg, pc = g, (1 - g) * (s + (1 - s) * q)
    p0 = 1 - pg - pc
    xmax = p2_max_x(n)
    total = 0.0
    for ng in range(n + 1):
        for nc in range(n - ng + 1):
            b = ng + nc
            if ng > xmax or not p1_success(n, b, 0):
                continue
            n0 = n - ng - nc
            total += (math.factorial(n) / (math.factorial(ng) * math.factorial(nc) * math.factorial(n0))
                      * pg ** ng * pc ** nc * p0 ** n0)
    return {"n": n, "g": g, "q": q, "s": s, "P1_and_P2": round(total, 3)}


def phase2(candidates: int, prevalence: float, catch: float) -> dict:
    """Model-generated candidates: expected A-false-greens and expected discordant b."""
    fg = candidates * prevalence
    return {"candidates": candidates, "fg_prevalence": prevalence, "b_catch": catch,
            "expected_A_false_greens": round(fg, 1), "expected_b": round(fg * catch, 1)}


def tables() -> dict:
    out: dict = {"alpha_two_sided": ALPHA}
    out["min_b_for_P1_with_c0"] = {n: min_b(n) for n in NS}
    out["P1_power"] = {f"p10={p}": {n: round(p1_power(n, p), 3) for n in NS} for p in (0.2, 0.3, 0.4, 0.5, 0.7)}
    out["P1_power_with_p01=0.05"] = {f"p10={p}": {n: round(p1_power(n, p, 0.05), 3) for n in NS} for p in (0.3, 0.5)}
    out["P2_max_nonaccept_allowed"] = {n: p2_max_x(n) for n in NS}
    out["P2_cp_upper_examples_n24"] = {x: round(beta_cdf_upper(x, 24), 3) for x in range(0, 7)}
    out["P2_power"] = {f"phi={p}": {n: round(p2_power(n, p), 3) for n in NS} for p in (0.05, 0.10, 0.15, 0.20, 0.30)}
    out["coupled_P1_and_P2_semantic_stratum"] = [coupled_joint_power(n, g, q) for n in (24, 40)
                                                 for g in (0.1, 0.2, 0.3) for q in (0.0, 0.1, 0.25, 0.4)]
    out["coupled_P1_and_P2_with_process_primaries_s0.25"] = [coupled_joint_power(24, g, 0.0, 0.25) for g in (0.1, 0.2, 0.3)]
    out["H2_examples_n24"] = {f"G={G},t={t},k/m={km}": {"p10": round(G * t * (1 - km), 3),
                                                          "power": round(p1_power(24, G * t * (1 - km)), 3)}
                              for G, t, km in ((0.5, 0.8, 0.2), (0.25, 1.0, 0.2), (0.5, 0.5, 0.2))}
    out["phase2"] = [phase2(144, pi, k) for pi in (0.03, 0.07, 0.15) for k in (0.3, 0.5)]
    return out


if __name__ == "__main__":
    t = tables()
    if sys.argv[1:] == ["--json"]:
        print(json.dumps(t, indent=2))
        sys.exit(0)
    for k, v in t.items():
        print(f"{k}:")
        if isinstance(v, list):
            for row in v:
                print("  ", row)
        elif isinstance(v, dict):
            for kk, vv in v.items():
                print(f"   {kk}: {vv}")
        else:
            print("  ", v)
