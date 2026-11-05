# ruff: noqa  (one-off audit measurement scripts, kept verbatim as run)
"""Score test selection against mutation ground truth (host side)."""
import json, os, re, subprocess, sys
from pathlib import Path
RA, A, HOME = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
env = {**os.environ, "HOME": HOME}
summary = {}
for spec_path in sorted((A / "mut").glob("*.result.json")):
    name = spec_path.name.split(".result")[0]; repo = A / "repos" / name
    res = json.loads(spec_path.read_text()); args = json.loads((A / "mut" / f"{name}.spec.json").read_text())["test_args"]
    if args[0] == "discover":
        start = args[args.index("-s") + 1]
        universe = sorted(p.relative_to(repo).as_posix() for p in (repo / start).rglob("test*.py"))
    else:
        universe = [m.replace(".", "/") + ".py" for m in args]
    uni = set(universe)
    def mod2file(m):
        f = m.replace(".", "/") + ".py"
        return f if f in uni else None
    texts = {u: (repo / u).read_text("utf-8", "replace") for u in universe}
    rows = []
    for m in res["mutations"]:
        fail = {mod2file(x) for x in m["failing_modules"]} - {None}
        if not fail: continue
        mod = m["file"][:-3].replace("/", "."); 
        if mod.endswith(".__init__"): mod = mod[:-9]
        leaf = mod.rsplit(".", 1)[-1]; pkg = mod.rsplit(".", 1)[0] if "." in mod else ""
        imp = re.compile(rf"(import\s+{re.escape(mod)}\b|from\s+{re.escape(mod)}\s+import|from\s+{re.escape(pkg)}\s+import\s+[^\n]*\b{re.escape(leaf)}\b)" if pkg else rf"(import\s+{re.escape(mod)}\b|from\s+{re.escape(mod)}\s+import)")
        grep_import = {u for u, t in texts.items() if imp.search(t)}
        name_match = {u for u in universe if leaf.lower().strip("_") in Path(u).stem.lower()}
        sym = {u for u, t in texts.items() if re.search(rf"\b{re.escape(m['func'])}\b", t)}
        r = subprocess.run([RA, "impact", m["file"], "--format", "json"], cwd=repo, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        try: ra = {t["path"] for t in json.loads(r.stdout)["tests"]} & uni
        except (ValueError, KeyError): ra = set()
        rs = subprocess.run([RA, "impact", m["func"], "--format", "json"], cwd=repo, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        try: ras = {t["path"] for t in json.loads(rs.stdout)["tests"]} & uni
        except (ValueError, KeyError): ras = set()
        rows.append({"fail": fail, "sel": {"repo-ai impact <file>": ra, "repo-ai impact <symbol>": ras, "grep: test imports module": grep_import,
                     "test filename matches module": name_match, "grep: test mentions function": sym, "union grep import|mention": grep_import | sym, "all tests": uni}})
    if not rows: continue
    summary[name] = {"mutations_detected": len(rows), "of": len(res["mutations"]), "test_files": len(uni), "methods": {}}
    for k in rows[0]["sel"]:
        rec = [len(r["fail"] & r["sel"][k]) / len(r["fail"]) for r in rows]
        full = sum(1 for r in rows if r["fail"] <= r["sel"][k])
        size = [len(r["sel"][k]) / len(uni) for r in rows]
        summary[name]["methods"][k] = {"mean_recall": round(sum(rec) / len(rec), 3), "no_miss": f"{full}/{len(rows)}", "mean_selected_frac": round(sum(size) / len(size), 3)}
json.dump(summary, open(A / "mut" / "score.json", "w"), indent=1)
agg = {}
for name, s in summary.items():
    for k, v in s["methods"].items():
        a = agg.setdefault(k, [0, 0, 0.0, 0.0, 0]); n = s["mutations_detected"]
        a[0] += int(v["no_miss"].split("/")[0]); a[1] += n; a[2] += v["mean_recall"] * n; a[3] += v["mean_selected_frac"] * n
print("repos:", {k: f'{v["mutations_detected"]}/{v["of"]} detected, {v["test_files"]} test files' for k, v in summary.items()})
for k, a in agg.items():
    print(f"{k:32s} no-miss {a[0]}/{a[1]} ({a[0]/a[1]:.0%})  mean recall {a[2]/a[1]:.3f}  mean selected {a[3]/a[1]:.0%} of test files")
