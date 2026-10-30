"""Build / verify the immutable abc-v5 manifests.

Two freezes, in this order (PREREGISTRATION.md section 4.3):

  ``python make_manifest.py write --stage W``     manifest.w.json: task statements, repo/, acceptance/, requirement maps
                                                  and follow-up pools, frozen BEFORE any candidate or hidden test exists.
  ``python make_manifest.py write --stage FULL``  manifest.json: everything (hidden oracle, candidates, grader, harness),
                                                  linked to the W freeze by its sha256, frozen BEFORE any arm is run.
  ``python make_manifest.py verify``              exit 1 on any schema, self-hash, file-hash or W-link mismatch.

``write`` refuses to overwrite an existing manifest: a frozen manifest is never regenerated. A change after a freeze is a
dated amendment plus a new manifest version (or a new study id), never a silent rewrite. Deterministic: sorted walks,
no timestamps, canonical JSON.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"
SEED = 20261029
STUDY = "abc-v5"
W_PATH, FULL_PATH = HERE / "manifest.w.json", HERE / "manifest.json"
PROTOCOL_FILES = ["PREREGISTRATION.md", "power.py", "manifest.schema.json", "make_manifest.py"]
HARNESS_FILES = ["grade.py", "run_offline.py", "selfcheck.py"]
W_PARTS = ("task.json", "requirements.json", "repo", "acceptance", "followup")
SKIP = {"__pycache__", ".pytest_cache", "node_modules", ".DS_Store"}
POLICY = ("Calibration only. Nothing in this manifest is confirmatory and no calibration task, cluster, candidate or "
          "hidden test may be reused in a confirmatory split. No live model or provider is invoked by any file here. "
          "Any change after a freeze is a dated amendment with a new manifest version.")

ARMS = {
    "A": "naive developer decision: run the task's test_command in the candidate's own workspace (W plus every file "
         "the candidate wrote, test edits included); accept iff exit code 0",
    "A0": "secondary: as A but W without the developer acceptance tests (shipped tests only); context for the "
          "'better tests' effect, not a repo-ai comparison",
    "A_clean": "secondary: careful developer: overlay only the candidate's write_paths files onto a clean W; "
               "accept iff test_command exits 0",
    "B": "repo-ai evidence: `repo-ai do --agent replay --replay P --run --allow-write <write_paths>` on a git repo of W, "
         "then `repo-ai coverage ID --requirements requirements.json --json`",
    "B_plus": "exploratory: B, then for every requirement B names as not verified, the pre-written follow-up pool "
              "test(s) for that requirement are added to W and the map, and B is re-run once",
    "A_plus": "exploratory: A with the same number of follow-up pool tests as B_plus added, requirements chosen "
              "uniformly at random (seeded) without looking at B's report",
    "A_plus_plus": "exploratory: A with every follow-up pool test added (the 'just write better tests' ceiling)",
}
DECISION_RULES = {
    "A": "ACCEPT if exit 0 else REJECT",
    "B": "ACCEPT iff mission state COMPLETE, effective_verdict PASS, freshness fresh and coverage headline "
         "ACCEPTANCE_MAPPED_ALL; REJECT if the proposal is refused, the verdict is not PASS, or any requirement is "
         "FAILING or MISSING_TEST; otherwise ABSTAIN. ABSTAIN counts as not-accepted for false greens and as a cost "
         "(non-acceptance) on correct candidates.",
    "B_plus": "same rule as B on the re-run",
}


def _h(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _walk(p: Path):
    if p.is_file():
        yield p
        return
    for q in sorted(p.rglob("*")):
        if q.is_file() and not (SKIP & set(q.parts)) and not q.is_symlink():
            yield q


def task_ids() -> list[str]:
    return sorted(p.name for p in TASKS.iterdir() if p.is_dir() and not p.name.startswith("."))


def file_set(stage: str) -> list[Path]:
    files: list[Path] = []
    for t in task_ids():
        if stage == "W":
            for part in W_PARTS:
                if (TASKS / t / part).exists():
                    files.extend(_walk(TASKS / t / part))
        else:
            files.extend(_walk(TASKS / t))
    files.extend(HERE / f for f in PROTOCOL_FILES)
    if stage == "FULL":
        files.extend(HERE / f for f in HARNESS_FILES)
    return files


def digests(stage: str) -> dict[str, str]:
    return {str(p.relative_to(HERE)).replace("\\", "/"): _h(p) for p in file_set(stage)}


def task_summary(t: str) -> dict:
    tj = json.loads((TASKS / t / "task.json").read_text())
    prov = tj["provenance"]
    return {"cluster": tj["cluster"], "language": tj["language"], "split": tj["split"],
            "write_paths": tj["write_paths"], "test_command": tj["test_command"],
            "requirement_ids": [r["id"] for r in tj["requirements"]], "provenance_kind": prov["kind"],
            "upstream_url": prov.get("upstream_url"), "upstream_commit": prov.get("upstream_commit"),
            "licence": prov["licence"]}


def candidates(t: str) -> dict:
    return json.loads((TASKS / t / "candidates.json").read_text())


def primary_draw() -> dict[str, str]:
    """One semantic-stratum decoy per task, drawn by a per-task seeded RNG (the primary pair of PREREGISTRATION 8.1)."""
    out = {}
    for t in task_ids():
        pool = sorted(n for n, c in candidates(t).items() if c["stratum"] == "semantic")
        if pool:
            out[t] = random.Random(f"{SEED}:{t}").choice(pool)
    return out


def build(stage: str) -> dict:
    m = {"study": STUDY, "manifest_version": 1, "stage": stage, "seed": SEED, "policy": POLICY,
         "status": "W_FROZEN_BEFORE_CANDIDATES" if stage == "W" else "CALIBRATION_FROZEN_BEFORE_ANY_ARM_RUN",
         "tasks": {t: task_summary(t) for t in task_ids()}, "sha256": digests(stage)}
    if stage == "FULL":
        m["w_manifest_sha256"] = _h(W_PATH)
        m["arms"] = ARMS
        m["decision_rules"] = DECISION_RULES
        m["grader_outcomes"] = ["CORRECT", "FALSE_GREEN", "FAIL", "INVALID"]
        m["primary_candidate_draw"] = primary_draw()
        m["expected_control_grades"] = {t: {n: c["expected_grade"] for n, c in sorted(candidates(t).items())}
                                        for t in task_ids()}
    m["content_sha256"] = hashlib.sha256(canonical(m)).hexdigest()
    return m


# ---------------------------------------------------------------- minimal JSON-Schema subset validator (no deps)
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _type_ok(v, t) -> bool:
    if isinstance(t, list):
        return any(_type_ok(v, x) for x in t)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def validate(v, s: dict, path: str = "$") -> list[str]:
    errs: list[str] = []
    if "type" in s and not _type_ok(v, s["type"]):
        return [f"{path}: expected {s['type']}"]
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: expected const {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} not in enum")
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: does not match {s['pattern']}")
        if len(v) < s.get("minLength", 0):
            errs.append(f"{path}: too short")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            errs.append(f"{path}: too few items")
        for i, x in enumerate(v):
            if "items" in s:
                errs += validate(x, s["items"], f"{path}[{i}]")
    if isinstance(v, dict):
        if len(v) < s.get("minProperties", 0):
            errs.append(f"{path}: too few properties")
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}: missing {k}")
        props, pats, extra = s.get("properties", {}), s.get("patternProperties", {}), s.get("additionalProperties", True)
        for k, x in v.items():
            matched = False
            if k in props:
                errs += validate(x, props[k], f"{path}.{k}")
                matched = True
            for pat, sub in pats.items():
                if re.search(pat, k):
                    errs += validate(x, sub, f"{path}.{k}")
                    matched = True
            if not matched:
                if extra is False:
                    errs.append(f"{path}: unexpected key {k!r}")
                elif isinstance(extra, dict):
                    errs += validate(x, extra, f"{path}.{k}")
    return errs


def check(path: Path) -> list[str]:
    """All problems with one manifest file (empty list == OK)."""
    if not path.is_file():
        return [f"{path.name}: missing"]
    m = json.loads(path.read_text())
    schema = json.loads((HERE / "manifest.schema.json").read_text())
    problems = [f"{path.name}: schema: {e}" for e in validate(m, schema)]
    body = {k: v for k, v in m.items() if k != "content_sha256"}
    if hashlib.sha256(canonical(body)).hexdigest() != m.get("content_sha256"):
        problems.append(f"{path.name}: content_sha256 does not match the manifest body (edited after freeze)")
    want, got = m.get("sha256", {}), digests(m.get("stage", "FULL"))
    for k in sorted(set(want) | set(got)):
        if want.get(k) != got.get(k):
            problems.append(f"{path.name}: file hash mismatch: {k}")
    if m.get("stage") == "FULL":
        if not W_PATH.is_file() or _h(W_PATH) != m.get("w_manifest_sha256"):
            problems.append("manifest.json: w_manifest_sha256 does not match manifest.w.json")
        else:
            w = json.loads(W_PATH.read_text())["sha256"]
            for k, v in w.items():
                if want.get(k) != v:
                    problems.append(f"manifest.json: W file changed between the W and FULL freezes: {k}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "write" and argv[1] == "--stage" and argv[2] in ("W", "FULL"):
        target = W_PATH if argv[2] == "W" else FULL_PATH
        if target.exists():
            print(f"REFUSED: {target.name} exists and is immutable; amend with a new manifest version instead")
            return 2
        if argv[2] == "FULL" and check(W_PATH):
            print("REFUSED: the W freeze does not verify:", check(W_PATH))
            return 2
        target.write_text(json.dumps(build(argv[2]), indent=2, sort_keys=True) + "\n")
        print("wrote", target.name)
        return 0
    if argv == ["verify"]:
        problems = []
        for p in (W_PATH, FULL_PATH):
            if p.exists():
                problems += check(p)
        if not W_PATH.exists():
            problems.append("manifest.w.json: missing")
        print("OK" if not problems else "MISMATCH\n  " + "\n  ".join(problems))
        return 1 if problems else 0
    print("usage: make_manifest.py write --stage W|FULL | verify")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
