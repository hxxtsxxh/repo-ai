"""The frozen system under test for skill-vet-fresh-v2 (PREREGISTRATION.md, status 2026-11-02): the git tree of
`src/repo_ai` (every module the vetter, `skills vet` and their helpers use), `pyproject.toml` and the harness,
recorded before any v2 case exists. The run job checks them, and that nothing but the delivery changed since the
freeze commit it is given.

    python benchmarks/skill-vet-fresh-v2/sut.py --record          # once, when freezing
    python benchmarks/skill-vet-fresh-v2/sut.py --check FREEZE_SHA
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FROZEN = ["src/repo_ai", "pyproject.toml", "benchmarks/skill-vet-fresh-v2/run.py",
          "benchmarks/skill-vet-fresh-v2/constraints.txt", "benchmarks/skill-vet-fresh-v2/validate_corpus.py"]
DELIVERY_DIR = "benchmarks/skill-vet-fresh-v2/corpus/"
DELIVERY_FILES = {"benchmarks/skill-vet-fresh-v2/labels.json", "benchmarks/skill-vet-fresh-v2/AUTHOR.md",
                  "benchmarks/skill-vet-fresh-v2/MANIFEST.sha256"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def objects(rev: str = "HEAD") -> dict[str, str]:
    return {rel: git("rev-parse", f"{rev}:{rel}") for rel in FROZEN}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--check", metavar="FREEZE_SHA")
    args = ap.parse_args()
    path = HERE / "SUT.json"
    if args.record:
        if path.exists():
            raise SystemExit("SUT.json exists: the system under test is frozen once")
        path.write_text(json.dumps({"objects": objects()}, indent=1, sort_keys=True) + "\n")
        return 0
    if not args.check:
        raise SystemExit("--record or --check FREEZE_SHA")
    problems = []
    sut = "benchmarks/skill-vet-fresh-v2/SUT.json"
    added = git("log", "--diff-filter=A", "--format=%H", "--", sut).splitlines()
    if git("rev-parse", f"{args.check}^{{commit}}") not in added:
        problems.append(f"{args.check} is not the commit that added SUT.json")
    frozen = json.loads(git("show", f"{args.check}:{sut}"))["objects"]
    for rel, oid in frozen.items():
        if objects()[rel] != oid:
            problems.append(f"changed since the freeze: {rel}")
    changed = [p for p in git("diff", "--name-only", args.check, "HEAD").splitlines() if p]
    problems += [f"not part of the delivery: {p}" for p in changed
                 if not (p.startswith(DELIVERY_DIR) or p in DELIVERY_FILES)]
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
