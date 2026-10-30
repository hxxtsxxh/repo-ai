"""Validation of the implemented interval (stats.clustered_diff_ci) against
the 0.7.3 method (Newcombe on fractional counts), on fresh seeds, at 95% and
90%, under two data-generating models. Synthetic data only.

Model "logit": logit p_A,t = mu + u_t, logit p_B,t = mu + u_t + beta + v_t.
Model "mixture": each task is one of five kinds drawn with fixed
probabilities: always solved by both (1,1); never solved (0,0); solved by B
only, deterministically (0,1); by A only (1,0); or flaky (pA, pB in (0,1)).
This is the "deterministic tasks" regime real coding benchmarks show.

    python coverage_validate.py <repo>/src 5000 > coverage_validate.json

Needs numpy (analysis-only; not a repo-ai dependency).
"""
import itertools
import json
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, sys.argv[1])
from repo_ai import stats  # noqa: E402

SIMS = int(sys.argv[2])
LEVELS = {"95": stats.Z95, "90": stats.Z90}
MIXES = {  # (w11, w00, w01, w10, w_flaky, flaky pA, flaky pB)
    "ceiling-null": (0.80, 0.05, 0.00, 0.00, 0.15, 0.6, 0.6),
    "ceiling-gain": (0.75, 0.05, 0.10, 0.00, 0.10, 0.5, 0.7),
    "mid-null": (0.35, 0.35, 0.05, 0.05, 0.20, 0.5, 0.5),
    "mid-gain": (0.30, 0.30, 0.20, 0.05, 0.15, 0.4, 0.7),
    "floor-gain": (0.05, 0.80, 0.08, 0.00, 0.07, 0.2, 0.4),
    "all-flaky": (0.0, 0.0, 0.0, 0.0, 1.0, 0.5, 0.6),
}


def expit(x):
    return 1 / (1 + np.exp(-x))


def draw_tasks(rng, model, params, n):
    if model == "logit":
        mu, beta, sd_task, sd_eff = params
        u, v = rng.normal(0, sd_task, n), rng.normal(0, sd_eff, n)
        return expit(mu + u), expit(mu + u + beta + v)
    w11, w00, w01, w10, wf, fa, fb = MIXES[params]
    kind = rng.choice(5, n, p=[w11, w00, w01, w10, wf])
    pa = np.choose(kind, [1.0, 0.0, 0.0, 1.0, fa])
    pb = np.choose(kind, [1.0, 0.0, 1.0, 0.0, fb])
    return pa, pb


def truth(model, params):
    if model == "logit":
        rng = np.random.default_rng(99)
        pa, pb = draw_tasks(rng, model, params, 2_000_000)
        return float(np.mean(pb - pa))
    w11, w00, w01, w10, wf, fa, fb = MIXES[params]
    return w01 - w10 + wf * (fb - fa)


def cell(job):
    model, params, n, reps, seed = job
    rng = np.random.default_rng(seed)
    target = truth(model, params)
    maxk = 3 if reps == "mixed" else reps
    res = {f"{m}{lv}": [0, 0.0] for m in ("new", "nf") for lv in LEVELS}
    for _ in range(SIMS):
        pa, pb = draw_tasks(rng, model, params, n)
        k = rng.choice([1, 2, 2, 3], n) if reps == "mixed" else np.full(n, reps)
        xa = rng.random((n, maxk)) < pa[:, None]
        xb = rng.random((n, maxk)) < pb[:, None]
        mask = np.arange(maxk)[None, :] < k[:, None]
        cells = [((p & q) & mask).sum(1) / k for p, q in ((xa, xb), (xa, ~xb), (~xa, xb), (~xa, ~xb))]
        d = cells[2] - cells[1]
        a, b, c, dd = (float(x.sum()) for x in cells)
        for lv, z in LEVELS.items():
            for m, (lo, hi) in (("new", stats.clustered_diff_ci(d.tolist(), z)),
                                ("nf", stats.newcombe_paired(a, b, c, dd, z))):
                res[f"{m}{lv}"][0] += lo - 1e-12 <= target <= hi + 1e-12
                res[f"{m}{lv}"][1] += hi - lo
    return {"model": model, "params": params, "n": n, "reps": reps, "truth": round(target, 4),
            **{key: {"coverage": h / SIMS, "width": w / SIMS} for key, (h, w) in res.items()}}


if __name__ == "__main__":
    logit = list(itertools.product([-2.2, 0.0, 1.4, 2.9], [0.0, 0.5, 1.5], [0.0, 1.5, 4.0], [0.0, 1.0]))
    designs = list(itertools.product([10, 25, 50], [1, 2, 3, "mixed"]))
    jobs = [("logit", p, n, r) for p in logit for n, r in designs] + \
           [("mixture", m, n, r) for m in MIXES for n, r in designs]
    jobs = [(*j, 50_000 + i) for i, j in enumerate(jobs)]  # fresh seeds (the exploration used 1000+)
    with Pool(12) as pool:
        json.dump(pool.map(cell, jobs, chunksize=2), sys.stdout)
