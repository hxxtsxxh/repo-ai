#!/usr/bin/env python3
"""ProofLab demonstrations on two real, upstream bug fixes, with negative
controls. Reproducible by anyone: it clones the public repositories at pinned
commits and drives the installed `repo-ai` CLI, exactly as a developer would.

    python benchmarks/prooflab/demo.py --work /tmp/prooflab-demo --out results/
    python benchmarks/prooflab/demo.py --mirror DIR ...   # clone from local copies (offline)

Each control runs in a fresh clone checked out at the fix's parent (the
original code), with repo-ai initialised and committed as the base. The
candidate is built in the working tree from the upstream fix, plus the
control's edits. The expected verdict of every control is fixed below, before
anything runs; the script reports each observed verdict next to it and
exits 1 when any differs.

These are demonstrations, not a held-out evaluation: the cases were picked by
a scout that had already checked that each upstream test fails at the parent
and passes at the fix.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

CASES = {
    "json-pointer": {
        "url": "https://github.com/stefankoegl/python-json-pointer",
        "licence": "BSD-3-Clause",
        "parent": "f15abacd371a3415fb874634687d1619aa5a6fe4",
        "fix": "16c4c8e33a30e364d94f7a870a6c79916b5f870d",  # PR #76 merge
        "runner": "unittest",
        "command": "python -m unittest tests",
        "source": ["jsonpointer.py"],
        "tests": ["tests.py"],
        "claim": "Resolving a JSON pointer token against a string raises JsonPointerException instead of indexing "
                 "into the string (/foo/0 on {'foo': 'abc'} must not return 'a').",
        "scenario": "tests.py",
        "targets": ["tests.WrongInputTests.test_string_not_indexable"],
        "existing_target": "tests.AltTypesTests.test_alttypes",
        "acceptance": ("tests_accept.py",
                       "import unittest\n\nfrom jsonpointer import JsonPointer, JsonPointerException, resolve_pointer\n"
                       "\n\nclass StringNotIndexable(unittest.TestCase):\n"
                       "    # verbatim from upstream tests.py at 16c4c8e (WrongInputTests.test_string_not_indexable)\n"
                       "    def test_string_not_indexable(self):\n"
                       "        doc = {\"foo\": \"should-not-be-indexable\"}\n"
                       "        self.assertRaises(JsonPointerException, resolve_pointer, doc, \"/foo/0\")\n\n"
                       "        ptr = JsonPointer(\"/foo/0\")\n"
                       "        self.assertRaises(JsonPointerException, ptr.resolve, doc)\n"),
        "edits": {
            "partial": [("jsonpointer.py", "elif isinstance(doc, str):",
                         "elif isinstance(doc, str) and not str(part).isdigit():")],
            "breakage": [("jsonpointer.py", "elif isinstance(doc, str):",
                          "elif isinstance(doc, str) or not isinstance(doc, Sequence):")],
            "hang": [("jsonpointer.py", "elif isinstance(doc, str):\n",
                      "elif isinstance(doc, str):\n            __import__('time').sleep(3600)\n")],
            "weaken": [("tests.py", 'self.assertRaises(JsonPointerException, resolve_pointer, doc, "/foo/0")',
                        'resolve_pointer(doc, "/foo")')],
            "touch": [("jsonpointer.py", "elif isinstance(doc, str):", "elif isinstance(doc, str):  # reviewed")],
        },
        "skip_marker": ("    def {name}(", "    @unittest.skip('obsolete')\n    def {name}("),
    },
    "ipaddr.js": {
        "url": "https://github.com/whitequark/ipaddr.js",
        "licence": "MIT",
        "parent": "40708ee",
        "fix": "74ee4c5751afbb998247696539065c78d274d631",
        "runner": "node",
        "command": "node --test",
        "source": ["lib/ipaddr.js"],
        "tests": ["test/ipaddr.test.js"],
        "claim": "IPv4/IPv6 match() and subnetMatch() reject invalid CIDR prefix lengths (negative, fractional, "
                 "NaN, infinite or longer than the address).",
        "scenario": "test/ipaddr.test.js",
        "targets": ["ipaddr > rejects invalid IPv4 CIDR prefix lengths in match",
                    "ipaddr > rejects invalid IPv6 CIDR prefix lengths in match",
                    "ipaddr > subnetMatch rejects invalid CIDR prefix lengths"],
        "existing_target": "ipaddr > matches IPv4 CIDR correctly",
        "acceptance": None,  # filled from the upstream test at run time (see _node_acceptance)
        "edits": {
            "partial": [("lib/ipaddr.js", "        !Number.isInteger(cidrBits) ||\n", "")],
            "breakage": [("lib/ipaddr.js", "cidrBits > maxCidrBits", "cidrBits >= maxCidrBits")],
            "hang": [("lib/ipaddr.js", "        throw new Error('ipaddr: invalid CIDR prefix length');",
                      "        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0);")],
            "weaken": [("test/ipaddr.test.js", "throws(() => address.match(network, 33));", "")],
            "touch": [("lib/ipaddr.js", "const maxCidrBits = first.length * partSize;",
                       "const maxCidrBits = first.length * partSize; // reviewed")],
        },
        "skip_marker": ("    it('{name}'", "    it.skip('{name}'"),
    },
}

# control -> (expected verdict.state, what it shows); fixed before anything runs
CONTROLS = {
    "fix": ("supported", "the upstream fix, its upstream test pinned from the fix commit"),
    "partial": ("candidate-failed", "a partial fix: the targeted failure is still there"),
    "breakage": ("regressions-detected", "fixes the target but breaks related existing behaviour"),
    "weaken": ("scenario-changed", "the candidate weakens the pinned acceptance test"),
    "baseline": ("baseline-not-reproduced", "the pinned target is an existing test that already passes"),
    "hang": ("incomplete", "the candidate hangs on the claimed path: missing evidence is not a pass"),
    "stale": ("stale", "a supported passport after a later edit"),
    "separate-fix": ("supported", "the same fix, with the acceptance test as a separate file outside the tree"),
    # declared after the first run, where "breakage" was rejected as candidate-failed: upstream keeps the related
    # tests in the pinned file itself. This is the same breakage with the separate acceptance file
    "separate-breakage": ("regressions-detected", "fixes the target but breaks related behaviour (separate "
                                                  "acceptance file)"),
    "hidden": ("regressions-detected", "breaks related behaviour and skips the existing tests that show it"),
}


# the evidence level (Session A's contract) expected for the supported controls; declared before run 3
EXPECTED_LEVEL = {"fix": "behavior_observed",  # the scenario is the fix commit's own test: part of the change
                  "separate-fix": "supported_by_controlled_comparison"}  # kept outside the repository


def sh(argv: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: float = 900,
       check: bool = False) -> subprocess.CompletedProcess:
    res = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
                         stdin=subprocess.DEVNULL)
    if check and res.returncode != 0:
        raise SystemExit(f"{shlex.join(argv)} failed ({res.returncode}): {res.stderr[-800:]}")
    return res


GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "demo", "GIT_AUTHOR_EMAIL": "demo@example.invalid",
           "GIT_COMMITTER_NAME": "demo", "GIT_COMMITTER_EMAIL": "demo@example.invalid"}


def _edit(root: Path, edits: list[tuple[str, str, str]]) -> None:
    for rel, old, new in edits:
        text = (root / rel).read_text("utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"{rel}: the control's edit does not apply ({old!r} found {text.count(old)} times)")
        (root / rel).write_text(text.replace(old, new), "utf-8")


def _node_acceptance(case: dict, root: Path) -> tuple[str, str]:
    """The upstream fix's three new tests, verbatim, in a file of their own."""
    diff = sh(["git", "show", "--format=", case["fix"], "--", "test/ipaddr.test.js"], root, check=True).stdout
    blocks, cur = [], []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            cur.append(line[1:])
        elif cur:
            blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))
    body = "\n".join(b for b in blocks if "it(" in b)
    head = ("import { throws } from 'node:assert';\nimport { describe, it } from 'node:test';\n\n"
            "import { IPv4, IPv6, subnetMatch } from '../lib/ipaddr.js';\n\n"
            f"// verbatim from upstream test/ipaddr.test.js at {case['fix'][:7]}\n")
    return "test/accept-cidr.test.js", head + "describe('ipaddr', () => {\n" + body + "\n});\n"


class Demo:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.work = Path(args.work).resolve()
        self.out = Path(args.out).resolve()
        self.cli = shlex.split(args.repo_ai)
        self.rows: list[dict] = []

    def repo_ai(self, root: Path, *argv: str, timeout: float = 900) -> subprocess.CompletedProcess:
        # the demonstration stands in for a person at a terminal: no agent-shell variable reaches repo-ai
        agent = {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "REPO_AI_IN_HOOK", "REPO_AI_AGENT",
                 "AI_AGENT", "CI", "GITHUB_ACTIONS"}
        env = {k: v for k, v in os.environ.items() if k not in agent}
        return sh([*self.cli, *argv, "-C", str(root)], root, env=env, timeout=timeout)

    def checkout(self, name: str, case: dict, label: str) -> Path:
        src = str(Path(self.args.mirror, case["url"].rsplit("/", 1)[-1])) if self.args.mirror else case["url"]
        root = self.work / f"{name}-{label}"
        if root.exists():
            shutil.rmtree(root)
        sh(["git", "clone", "-q", "--no-checkout", src, str(root)], self.work, env=GIT_ENV, check=True)
        sh(["git", "checkout", "-q", "-B", "prooflab-demo", case["parent"]], root, env=GIT_ENV, check=True)
        init = self.repo_ai(root, "init", "--agent", "none", "-q")
        if init.returncode != 0:
            raise SystemExit(f"repo-ai init failed in {root}: {init.stderr[-500:]}")
        sh(["git", "add", "-A"], root, env=GIT_ENV, check=True)
        sh(["git", "commit", "-qm", "repo-ai init (the base: the original code)"], root, env=GIT_ENV, check=True)
        return root

    def candidate(self, root: Path, case: dict, with_tests: bool = True) -> None:
        files = case["source"] + (case["tests"] if with_tests else [])
        sh(["git", "checkout", case["fix"], "--", *files], root, env=GIT_ENV, check=True)
        sh(["git", "reset", "-q"], root, env=GIT_ENV, check=True)  # the candidate is uncommitted work

    def pin(self, root: Path, case: dict, *extra: str) -> str:
        res = self.repo_ai(root, "prove", "pin", "claim", "--claim", case["claim"], "--test-command",
                           case["command"], *extra, "--json")
        if res.returncode != 0:
            raise SystemExit(f"pin failed: {res.stderr[-600:]}")
        return json.loads(res.stdout)["id"]

    def prove(self, root: Path, case: dict, *extra: str) -> tuple[int, dict, float]:
        started = time.monotonic()
        res = self.repo_ai(root, "prove", "run", "claim", "--json", "--test-command", case["command"], *extra)
        took = time.monotonic() - started
        try:
            return res.returncode, json.loads(res.stdout), took
        except ValueError:
            raise SystemExit(f"prove run printed no passport (exit {res.returncode}): {res.stderr[-800:]}") from None

    def record(self, name: str, control: str, code: int, pp: dict | None, took: float, state: str = "",
               extra: dict | None = None) -> None:
        want, what = CONTROLS[control]
        got = state or (pp or {}).get("verdict", {}).get("state", "")
        row = {"case": name, "control": control, "what": what, "expected": want, "observed": got,
               "as_expected": got == want, "false_proof": got == "supported" and want != "supported",
               "exit_code": code, "seconds": round(took, 1),
               "passport_digest": (pp or {}).get("digest"), **(extra or {})}
        if pp is not None:
            row["reasons"] = pp["verdict"]["reasons"][:3]
            row["level"] = (pp["evidence"][0]["claim"]["level"] if pp.get("evidence") else None)
            if control in EXPECTED_LEVEL:
                row["expected_level"] = EXPECTED_LEVEL[control]
                row["as_expected"] = row["as_expected"] and row["level"] == EXPECTED_LEVEL[control]
        self.rows.append(row)
        mark = "ok " if row["as_expected"] else "UNEXPECTED"
        print(f"  {mark} {control:17s} expected {want:24s} observed {got:24s} exit {code}  {took:5.1f}s"
              + (f"  level {row.get('level')}" if row.get("level") else ""), flush=True)

    def export(self, root: Path, name: str, control: str) -> None:
        dest = self.out / name
        dest.mkdir(parents=True, exist_ok=True)
        for fmt, suffix in (("md", "md"), ("json", "json")):
            res = self.repo_ai(root, "prove", "report", "claim", "--format", fmt)
            (dest / f"{control}.{suffix}").write_text(res.stdout, "utf-8")

    def run_case(self, name: str, case: dict) -> None:
        print(f"{name}: {case['url']} parent {case['parent'][:7]} -> fix {case['fix'][:7]} ({case['licence']})",
              flush=True)
        targets = [x for t in case["targets"] for x in ("--target", t)]
        upstream = ["--scenario", case["scenario"], "--from", case["fix"], *targets]
        # A: the upstream test file, pinned from the fix commit
        root = self.checkout(name, case, "fix")
        self.pin(root, case, *upstream)
        self.candidate(root, case)
        code, pp, took = self.prove(root, case)
        self.record(name, "fix", code, pp, took)
        self.export(root, name, "fix")
        _edit(root, case["edits"]["touch"])
        st = self.repo_ai(root, "prove", "status", "claim", "--json")
        self.record(name, "stale", st.returncode, None, 0.0, json.loads(st.stdout)["state"])
        for control in ("partial", "breakage", "hang"):
            root = self.checkout(name, case, control)
            self.pin(root, case, *upstream)
            self.candidate(root, case)
            _edit(root, case["edits"][control])
            code, pp, took = self.prove(root, case, *(["--timeout", "20"] if control == "hang" else []))
            self.record(name, control, code, pp, took)
            self.export(root, name, control)
        root = self.checkout(name, case, "weaken")
        self.pin(root, case, *upstream)
        self.candidate(root, case)
        _edit(root, case["edits"]["weaken"])
        code, pp, took = self.prove(root, case)
        self.record(name, "weaken", code, pp, took)
        root = self.checkout(name, case, "baseline")
        self.pin(root, case, "--scenario", case["scenario"], "--from", case["fix"], "--target",
                 case["existing_target"])
        self.candidate(root, case)
        code, pp, took = self.prove(root, case)
        self.record(name, "baseline", code, pp, took)
        # B: the acceptance test as a separate file, kept outside the repository (a reviewer's)
        accept_rel, accept_text = case["acceptance"] or _node_acceptance(case, root)
        outside = self.work / f"{name}-acceptance" / Path(accept_rel).name
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text(accept_text, "utf-8")
        # a reviewer's pin: the test kept outside the repository, and the code under test named (the upstream fix's
        # source files), so that no other edit of the change can reach the scenario's run
        separate = ["--scenario", accept_rel, "--file", str(outside), *[x for f in case["source"]
                                                                         for x in ("--subject", f)]]
        root = self.checkout(name, case, "separate-fix")
        self.pin(root, case, *separate)
        self.candidate(root, case, with_tests=False)
        code, pp, took = self.prove(root, case)
        self.record(name, "separate-fix", code, pp, took)
        self.export(root, name, "separate-fix")
        root = self.checkout(name, case, "separate-breakage")
        self.pin(root, case, *separate)
        self.candidate(root, case, with_tests=False)
        _edit(root, case["edits"]["breakage"])
        code, pp, took = self.prove(root, case)
        self.record(name, "separate-breakage", code, pp, took)
        self.export(root, name, "separate-breakage")
        broken = [t for r in (pp.get("regressions") or {}).get("new_failures") or [] for t in r["tests"]]
        root = self.checkout(name, case, "hidden")
        self.pin(root, case, *separate)
        self.candidate(root, case, with_tests=False)
        _edit(root, case["edits"]["breakage"])
        old, new = case["skip_marker"]
        names = sorted({t.split(".")[-1] if case["runner"] == "unittest" else t.split(" > ")[-1] for t in broken})
        for test in names:
            _edit(root, [(case["tests"][0], old.format(name=test), new.format(name=test))])
        verify = self.repo_ai(root, "verify", "--run", "--json", "--test-command", case["command"])
        verify_verdict = json.loads(verify.stdout)["summary"]["verdict"] if verify.stdout.strip() else "error"
        code, pp, took = self.prove(root, case)
        self.record(name, "hidden", code, pp, took, extra={
            "skipped_existing_tests": names, "verify_alone": {"exit_code": verify.returncode,
                                                              "verdict": verify_verdict}})
        self.export(root, name, "hidden")

    def main(self) -> int:
        self.work.mkdir(parents=True, exist_ok=True)
        self.out.mkdir(parents=True, exist_ok=True)
        version = self.repo_ai(self.work, "--version").stdout.strip()
        for name in self.args.cases or list(CASES):
            self.run_case(name, CASES[name])
        summary = {"repo_ai": version, "python": sys.version.split()[0],
                   "node": sh(["node", "--version"], self.work).stdout.strip(),
                   "platform": sys.platform, "controls": CONTROLS,
                   "cases": {n: {k: CASES[n][k] for k in ("url", "licence", "parent", "fix", "command")}
                             for n in self.args.cases or list(CASES)},
                   "rows": self.rows, "all_as_expected": all(r["as_expected"] for r in self.rows),
                   "false_proofs": sum(r["false_proof"] for r in self.rows)}
        (self.out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", "utf-8")
        print(f"{sum(r['as_expected'] for r in self.rows)} of {len(self.rows)} controls as expected, "
              f"{summary['false_proofs']} false proof(s); "
              f"summary in {self.out / 'summary.json'}")
        return 0 if summary["all_as_expected"] and not summary["false_proofs"] else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", required=True, help="scratch directory for the clones")
    ap.add_argument("--out", required=True, help="where passports and summary.json go")
    ap.add_argument("--mirror", help="a directory with local clones named like the cases (offline)")
    ap.add_argument("--repo-ai", default="repo-ai", help="how to invoke repo-ai (default: the installed CLI)")
    ap.add_argument("--cases", nargs="*", choices=list(CASES))
    raise SystemExit(Demo(ap.parse_args()).main())
