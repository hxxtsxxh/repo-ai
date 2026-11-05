"""Exploration: frequentist coverage of candidate task-clustered intervals for
paired success-rate differences (repo-ai 0.7.4). Synthetic data only: no
experiment outcomes are read. Needs numpy and scipy (analysis-only; not
repo-ai dependencies). The chosen method is re-checked on fresh seeds by
coverage_validate.py; see docs/STATISTICS_COVERAGE.md.

    python coverage_explore.py <repo>/src 2000 newcombe_fractional,t_task,am_cluster_z,am_cluster_t,bp_cluster_z,bp_cluster_t

Model: task t has logit p_A,t = mu + u_t and logit p_B,t = mu + u_t + beta + v_t,
with u_t ~ N(0, sd_task^2) (difficulty) and v_t ~ N(0, sd_eff^2) (effect
heterogeneity). Each repetition draws A and B independently given (p_A,t, p_B,t).
Estimand: the superpopulation mean E[p_B,t - p_A,t] (tasks are a sample).
"""
import itertools
import json
import math
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, sys.argv[1])  # repo src: repo_ai.stats (stdlib only)
from repo_ai import stats  # noqa: E402

Z = stats.Z95
SIMS = int(sys.argv[2]) if len(sys.argv) > 2 else 2000


def expit(x):
    return 1 / (1 + np.exp(-x))


def truth(mu, beta, sd_task, sd_eff):
    rng = np.random.default_rng(12345)
    u = rng.normal(0, sd_task, 2_000_000)
    v = rng.normal(0, sd_eff, 2_000_000)
    return float(np.mean(expit(mu + u + beta + v) - expit(mu + u)))


def fractional_table(xa, xb, k):
    """xa, xb: (n, maxk) 0/1 arrays; k: reps per task (n,). Fractional 2x2."""
    mask = np.arange(xa.shape[1])[None, :] < k[:, None]
    both = ((xa & xb) & mask).sum(1) / k
    aonly = ((xa & ~xb) & mask).sum(1) / k
    bonly = ((~xa & xb) & mask).sum(1) / k
    neither = ((~xa & ~xb) & mask).sum(1) / k
    d = bonly - aonly
    return both.sum(), aonly.sum(), bonly.sum(), neither.sum(), d


def t_interval(d):
    from scipy.stats import t as tdist
    n = len(d)
    m, s = d.mean(), d.std(ddof=1)
    q = tdist.ppf(0.975, n - 1)
    return m - q * s / math.sqrt(n), m + q * s / math.sqrt(n)


def am_cluster(d, m):
    """Agresti-Min adjusted Wald on task-level differences: pseudo-tasks with
    d=+1 (weight 1/2), d=-1 (1/2) and d=0 (1); variance from the empirical
    between-task spread. Equals Agresti-Min (2005) with one run per task."""
    n = len(d)
    n2 = n + 2
    mean = d.sum() / n2
    ss = ((d - mean) ** 2).sum() + 0.5 * (1 - mean) ** 2 + 0.5 * (1 + mean) ** 2 + mean ** 2
    se = math.sqrt(ss / n2 / n2)
    q = Z
    if m == "am_cluster_t":
        from scipy.stats import t as tdist
        q = tdist.ppf(0.975, n - 1)
    return max(-1.0, mean - q * se), min(1.0, mean + q * se)


def bp_cluster(d, m):
    """Bonett-Price (2012) adjusted Wald on task-level differences: one
    pseudo-task with d=+1 and one with d=-1. Equals Bonett-Price with one run
    per task."""
    n = len(d)
    n2 = n + 2
    mean = d.sum() / n2
    ss = ((d - mean) ** 2).sum() + (1 - mean) ** 2 + (1 + mean) ** 2
    se = math.sqrt(ss / n2 / n2)
    q = Z
    if m == "bp_cluster_t":
        from scipy.stats import t as tdist
        q = tdist.ppf(0.975, n - 1)
    return max(-1.0, mean - q * se), min(1.0, mean + q * se)



def cell(args):
    n, reps, mu, beta, sd_task, sd_eff, seed, methods = args
    rng = np.random.default_rng(seed)
    target = truth(mu, beta, sd_task, sd_eff)
    hit = {m: 0 for m in methods}
    width = {m: 0.0 for m in methods}
    lo_miss = {m: 0 for m in methods}
    maxk = 3 if reps == "mixed" else reps
    for _ in range(SIMS):
        u = rng.normal(0, sd_task, n)
        v = rng.normal(0, sd_eff, n)
        pa, pb = expit(mu + u), expit(mu + u + beta + v)
        if reps == "mixed":  # budget stops / invalid exclusions: 1-3 reps per task
            k = rng.choice([1, 2, 2, 3], n)
        else:
            k = np.full(n, reps)
        xa = rng.random((n, maxk)) < pa[:, None]
        xb = rng.random((n, maxk)) < pb[:, None]
        a, b, c, dd, d = fractional_table(xa, xb, k)
        for m in methods:
            if m == "newcombe_fractional":
                lo, hi = stats.newcombe_paired(a, b, c, dd, Z)
            elif m == "t_task":
                lo, hi = t_interval(d)
            elif m.startswith("bp_cluster"):
                lo, hi = bp_cluster(d, m)
            elif m.startswith("am_cluster"):
                lo, hi = am_cluster(d, m)
            else:
                continue
            hit[m] += lo - 1e-12 <= target <= hi + 1e-12
            lo_miss[m] += target < lo - 1e-12
            width[m] += hi - lo
    return {"n": n, "reps": reps, "mu": mu, "beta": beta, "sd_task": sd_task, "sd_eff": sd_eff,
            "truth": round(target, 4),
            "coverage": {m: hit[m] / SIMS for m in methods},
            "miss_low": {m: lo_miss[m] / SIMS for m in methods},
            "width": {m: width[m] / SIMS for m in methods}}


if __name__ == "__main__":
    methods = sys.argv[3].split(",") if len(sys.argv) > 3 else ["newcombe_fractional", "t_task"]
    grid = list(itertools.product([10, 25, 50], [1, 2, 3, "mixed"],
                                  [-2.2, 0.0, 1.4, 2.9],       # base success ~0.10, 0.50, 0.80, 0.95
                                  [0.0, 0.5, 1.5],             # effect on the logit scale
                                  [0.0, 1.5, 4.0],             # task difficulty spread (4 = near-deterministic tasks)
                                  [0.0, 1.0]))                 # effect heterogeneity
    jobs = [(*g, 1000 + i, methods) for i, g in enumerate(grid)]
    with Pool(12) as pool:
        out = pool.map(cell, jobs, chunksize=4)
    json.dump(out, sys.stdout)
