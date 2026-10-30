# ruff: noqa  (one-off audit measurement scripts, kept verbatim as run)
"""Host side: pick mutations (seeded) from AST; write spec for the sandbox."""
import ast, json, random, subprocess, sys
from pathlib import Path
repo, test_args, out = Path(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3]
files = subprocess.run(["git", "ls-files", "*.py"], cwd=repo, capture_output=True, text=True).stdout.split()
src = [f for f in files if "test" not in f.lower() and not f.startswith(("doc", "setup", "bench", "script", "example"))]
cands = []
for f in src:
    try: tree = ast.parse((repo / f).read_text("utf-8"))
    except SyntaxError: continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(node.body) >= 2:
            body = node.body[1:] if isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant) else node.body
            cands.append({"file": f, "func": node.name, "start": body[0].lineno, "end": body[-1].end_lineno, "indent": body[0].col_offset})
random.Random(0).shuffle(cands)
json.dump({"test_args": test_args, "mutations": cands[:16]}, open(out, "w"), indent=1)
print(len(cands), "candidates;", min(16, len(cands)), "chosen")
