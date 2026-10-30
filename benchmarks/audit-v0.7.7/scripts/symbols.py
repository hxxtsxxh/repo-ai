# ruff: noqa  (one-off audit measurement scripts, kept verbatim as run)
"""Symbol lookup: repo-ai `symbol` vs ripgrep, against AST ground truth (definitions)."""
import ast, json, random, re, statistics, subprocess, sys, time, os
from pathlib import Path
RA = sys.argv[1]; root = Path(sys.argv[2]); env = {**os.environ, "HOME": sys.argv[3]}
out = {}
for repo in sorted(p for p in root.iterdir() if p.is_dir()):
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=repo, capture_output=True, text=True).stdout.split()
    defs = {}
    for f in files:
        try: tree = ast.parse((repo / f).read_text("utf-8", "replace"))
        except SyntaxError: continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs.setdefault(n.name, set()).add((f, n.lineno))
    if not defs: continue
    names = sorted(n for n, s in defs.items() if len(s) <= 3 and not n.startswith("__") and len(n) > 3)
    random.Random(0).shuffle(names); names = names[:40]
    m = {"ra": [0, 0, 0, 0], "rg": [0, 0, 0, 0]}  # true found, true total, returned, returned-true
    lat = {"ra": [], "rg": []}; top1 = {"ra": 0, "rg": 0}
    for name in names:
        truth = defs[name]
        t = time.perf_counter()
        r = subprocess.run([RA, "symbol", name, "--format", "json", "--limit", "50"], cwd=repo, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        lat["ra"].append(time.perf_counter() - t)
        try: got_ra = [(x["path"], x["line"]) for x in json.loads(r.stdout or "[]") if x.get("name") == name]
        except ValueError: got_ra = []
        t = time.perf_counter()
        g = subprocess.run(["rg", "-n", "--no-heading", "-g", "*.py", rf"^\s*(async\s+)?(def|class)\s+{re.escape(name)}\b", "."], cwd=repo, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        lat["rg"].append(time.perf_counter() - t)
        got_rg = [(l.split(":")[0].removeprefix("./"), int(l.split(":")[1])) for l in g.stdout.splitlines() if l.count(":") >= 2]
        for k, got in (("ra", got_ra), ("rg", got_rg)):
            gs = set(got)
            m[k][0] += len(truth & gs); m[k][1] += len(truth); m[k][2] += len(gs); m[k][3] += len(truth & gs)
            top1[k] += bool(got) and got[0] in truth
    out[repo.name] = {"names": len(names), **{k: {"recall": round(m[k][0] / m[k][1], 3), "precision": round(m[k][3] / max(m[k][2], 1), 3),
                      "top1": round(top1[k] / len(names), 3), "p50_ms": round(statistics.median(lat[k]) * 1000)} for k in m}}
    print(repo.name, out[repo.name], flush=True)
json.dump(out, open(sys.argv[4], "w"), indent=1)
