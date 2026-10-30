# ruff: noqa  (one-off audit measurement scripts, kept verbatim as run)
"""Runs INSIDE the podman sandbox (no network). For each mutation: copy the repo,
replace one function body with `raise`, run the unittest suite, record failing test files."""
import json, os, re, shutil, subprocess, sys
src, spec, out = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]
args = spec["test_args"]
LINE = re.compile(r"^(\S+) \(([\w.]+)\)(?:\n.*?)? \.\.\. (FAIL|ERROR|unexpected success)", re.M)
HEAD = re.compile(r"^(?:ERROR|FAIL): (\S+) \(([\w.]+)\)", re.M)
def failing(work):
    argv = ["discover", "-v", *args[1:]] if args[:1] == ["discover"] else ["-v", *args]
    p = subprocess.run([sys.executable, "-m", "unittest", *argv], cwd=work, capture_output=True, text=True, timeout=900)
    text = p.stderr + p.stdout
    mods = set()
    for name, dotted in HEAD.findall(text):
        if dotted.startswith("unittest.loader._FailedTest"):
            mods.add(name)
        else:
            mods.add(".".join(dotted.split(".")[:-2]) if dotted.count(".") >= 2 else dotted)
    return sorted(mods), p.returncode
def run(mutation):
    work = "/tmp/w"
    shutil.rmtree(work, ignore_errors=True); shutil.copytree(src, work, ignore=shutil.ignore_patterns(".git", ".repo-ai", "__pycache__"))
    if mutation:
        path = os.path.join(work, mutation["file"]); lines = open(path).read().split("\n")
        s, e, ind = mutation["start"] - 1, mutation["end"], mutation["indent"]
        lines[s:e] = [" " * ind + "raise RuntimeError('repo-ai-audit mutation')"]
        open(path, "w").write("\n".join(lines))
    return failing(work)
base, rc = run(None)
res = {"baseline_failures": base, "baseline_rc": rc, "mutations": []}
for m in spec["mutations"]:
    try: mods, rc = run(m)
    except subprocess.TimeoutExpired: mods, rc = ["<timeout>"], -1
    res["mutations"].append({**m, "failing_modules": [x for x in mods if x not in base]})
    json.dump(res, open(out, "w"), indent=1)
print("done", len(res["mutations"]))
