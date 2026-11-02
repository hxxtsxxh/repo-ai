"""The frozen system under test for skill-vet-fresh-v2 (PREREGISTRATION.md, status 2026-11-02): the git blob of each
vetting source file, recorded before any v2 case exists. `--check` (the CI run job) fails if any has changed.

    python benchmarks/skill-vet-fresh-v2/sut.py --record   # once, when freezing
    python benchmarks/skill-vet-fresh-v2/sut.py --check
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FILES = ["src/repo_ai/firewall.py", "src/repo_ai/capbundle.py", "src/repo_ai/autonomy.py", "src/repo_ai/pluginvet.py",
         "src/repo_ai/skillcheck.py", "src/repo_ai/security.py", "benchmarks/skill-vet-fresh-v2/run.py"]


def blobs() -> dict[str, str]:
    out = {}
    for rel in FILES:
        proc = subprocess.run(["git", "hash-object", rel], cwd=ROOT, capture_output=True, text=True, check=True)
        out[rel] = proc.stdout.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    path = HERE / "SUT.json"
    if args.record:
        if path.exists():
            raise SystemExit("SUT.json exists: the system under test is frozen once")
        path.write_text(json.dumps({"files": blobs()}, indent=1, sort_keys=True) + "\n")
        return 0
    frozen = json.loads(path.read_text())["files"]
    now = blobs()
    changed = sorted(k for k in frozen if now.get(k) != frozen[k])
    for rel in changed:
        print(f"changed since the freeze: {rel}", file=sys.stderr)
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
