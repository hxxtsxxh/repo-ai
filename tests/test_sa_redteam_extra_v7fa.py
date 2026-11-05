# Vendored from Session A's red team (PR #24, comments 6401610438 and 6402441378;
# scratchpad/redteam/v7fa), unchanged except the helper import and two lint fixes. Each test asserts the safe result.
"""ADAPTED for 7fa342d (v7fa): only two changes vs ../test_redteam_extra.py:
(1) the canonical fixture pins with `--subject calc/__init__.py` (7fa342d requires a declared
    subject for supported_by_controlled_comparison; without it the level is behavior_observed);
(2) AI_AGENT is stripped from the terminal environment (7fa342d treats AI_AGENT as an agent shell).
All assertions are unchanged.

Red-team checks beyond F1-F5 (contract 1.1, docs/PROOF-EVIDENCE-CONTRACT.md).
Each test asserts the contract-correct behaviour; a failing test is a defect on
the tested head, a passing one shows the property holds.

X1  list-mode `prove status` (several claims) checks freshness like `prove status ID`
    (verify's environment key included)
X2  verify `nothing-selected` never supports a claim (contract §6, 1.1)
X3  `supported_by_controlled_comparison` needs >= 2 agreeing control observations (§7, 1.1)
X4  repeats run sequentially, each in a fresh workspace (§7)
X5  an expected failure is counted under `expected_failures` (§4 rule 3)
X6  reproduction.engine names a commit or wheel sha256, environment names the platform (§8);
    the record says which contract version it implements
X7  `prove report` (md, json, in-toto) agrees with the passport and with `prove status`
X8  a negative control that never executes the code (the base hangs: time-out) does not
    count as a reproduction

Run: cd rvP2 && PYTHONPATH=$PWD/src python -m pytest -q test_redteam_extra.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import repo_ai

_TESTS = Path(repo_ai.__file__).resolve().parents[2] / "tests"
sys.path.insert(0, str(_TESTS))
from conftest import cli_env  # noqa: E402
from test_verify_engine import _host_sandbox  # noqa: E402

AGENT_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "REPO_AI_IN_HOOK", "REPO_AI_AGENT",
              "CI", "GITHUB_ACTIONS", "AI_AGENT")
pytestmark = pytest.mark.skipif(not _host_sandbox(), reason="no sandbox backend to run tests in")


def cli(root: Path, *args: str, agent: bool) -> subprocess.CompletedProcess:
    env = {k: v for k, v in cli_env().items() if k not in AGENT_VARS}
    if agent:
        env["CLAUDECODE"] = "1"
    return subprocess.run([sys.executable, "-m", "repo_ai", *args, "-C", str(root)], capture_output=True, text=True,
                          env=env, timeout=600, check=False)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                   env={**cli_env(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def make_repo(root: Path, files: dict[str, str]) -> Path:
    """A committed base with `repo-ai init` done, as `prove` needs it."""
    write(root, files)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    assert cli(root, "init", "--agent", "none", "-q", agent=False).returncode == 0
    git(root, "add", "-A")
    git(root, "commit", "-qm", "repo-ai init")
    return root


def pin_and_run(root: Path, scenario: str, outside: Path | None, *pin_extra: str, run_extra: tuple[str, ...] = (),
                agent: bool = False) -> tuple[int, dict]:
    """Pin from a terminal (or an agent shell), then `prove run --json`."""
    where = ["--file", str(outside)] if outside is not None else []
    pin = cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", scenario, *where, *pin_extra, agent=agent)
    assert pin.returncode == 0, pin.stderr
    proc = cli(root, "prove", "run", "c", "--json", *run_extra, agent=agent)
    assert proc.stdout.strip(), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


import re  # noqa: E402
import shutil  # noqa: E402

from test_verify_adaptive import NODE_SANDBOX  # noqa: E402

BUGGY = "def mean(xs):\n    return sum(xs) / len(xs)\n"
FIXED = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n"
EXISTING = ("import unittest\nfrom calc import mean\n\n\nclass T(unittest.TestCase):\n"
            "    def test_mean(self):\n        self.assertEqual(mean([1, 2, 3]), 2)\n")
UT = ["--test-command", "python -m unittest discover -s tests -t ."]
# the target records the wall-clock window it ran in (in its failure message, at the base and the control),
# and the scenario has one @expectedFailure test
CANONICAL = ("import time\nimport unittest\nfrom calc import mean\n\n\nclass A(unittest.TestCase):\n"
             "    def test_empty(self):\n        t0 = time.time()\n        time.sleep(1.5)\n        try:\n"
             "            r = mean([])\n        except ZeroDivisionError:\n"
             "            self.fail('window %.3f %.3f' % (t0, time.time()))\n        self.assertEqual(r, 0)\n\n"
             "    @unittest.expectedFailure\n    def test_known_gap(self):\n        self.assertEqual(mean([1]), 2)\n")


@pytest.fixture(scope="module")
def canonical(tmp_path_factory) -> tuple[Path, dict]:
    """The textbook controlled comparison: a terminal pin of a file kept outside the
    repository, a real fix, nothing else changed."""
    tmp = tmp_path_factory.mktemp("canon")
    root = make_repo(tmp / "canon", {"calc/__init__.py": BUGGY, "tests/__init__.py": "",
                                     "tests/test_calc.py": EXISTING})
    outside = tmp / "reviewer" / "test_accept.py"
    write(outside.parent, {"test_accept.py": CANONICAL})
    write(root, {"calc/__init__.py": FIXED})
    code, pp = pin_and_run(root, "tests/test_accept.py", outside, *UT, "--subject", "calc/__init__.py")  # v7fa: declared subject
    assert code == 0 and pp["verdict"]["state"] == "supported", pp["verdict"]  # fixture sanity
    assert pp["evidence"][0]["claim"]["level"] == "supported_by_controlled_comparison", pp["evidence"][0]["claim"]
    return root, pp


def test_x3_a_controlled_comparison_needs_two_agreeing_control_observations(canonical):
    _, pp = canonical
    rec = pp["evidence"][0]
    control = rec["sides"]["control"]["observations"]
    assert len(control) >= 2, (f"X3: level {rec['claim']['level']} with {len(control)} control observation(s); "
                               "contract 1.1 §7 needs at least 2 conclusive, agreeing ones")


def test_x4_repeats_run_sequentially(canonical):
    """Contract §7: repeats run sequentially. Checked per side (the base's repeats among
    themselves, the control's among themselves); sides may still overlap each other."""
    _, pp = canonical
    base = pp["observations"]["baseline"]

    def windows(reps: list[dict]) -> list[tuple[float, float]]:
        out = []
        for rep in reps:
            for msg in rep["failures"].values():
                m = re.search(r"window (\d+\.\d+) (\d+\.\d+)", msg)
                if m:
                    out.append((float(m.group(1)), float(m.group(2))))
        return sorted(out)
    sides = {"base": windows(base["repeats"]), "control": windows(base["control"])}
    assert len(sides["base"]) == len(base["repeats"]) >= 2 and len(sides["control"]) == len(base["control"]), sides
    for side, w in sides.items():
        overlaps = [(a, b) for a, b in zip(w, w[1:], strict=False) if b[0] < a[1]]
        assert not overlaps, f"X4: {side} repeats ran concurrently (overlapping windows {overlaps})"


def test_x5_an_expected_failure_is_counted_as_one(canonical):
    _, pp = canonical
    cand = pp["evidence"][0]["sides"]["candidate"]["observations"]
    assert all(o["tests"]["expected_failures"] == 1 for o in cand), (
        f"X5: the scenario's @expectedFailure test is not counted: {[o['tests'] for o in cand]}")


def test_x6_the_record_names_its_engine_and_platform(canonical):
    _, pp = canonical
    rep = pp["evidence"][0]["reproduction"]
    assert rep["engine"].get("commit") or rep["engine"].get("wheel_sha256"), (
        f"X6: reproduction.engine has neither commit nor wheel_sha256: {rep['engine']}")


def test_x6a_the_record_names_its_platform(canonical):
    _, pp = canonical
    env = pp["evidence"][0]["reproduction"]["environment"]
    assert env.get("platform"), f"X6a: reproduction.environment has no platform: {env}"


def test_x6b_the_record_writes_the_contract_version_it_implements(canonical):
    _, pp = canonical
    # the producer applies 1.1 rules (the D10 cap, nothing-selected, the control as a side) only if it says 1.1
    assert pp["evidence"][0]["contract_version"] == "1.1", (
        f"X6b: contract_version {pp['evidence'][0]['contract_version']!r}; the contract in force is 1.1")


def test_x7_reports_agree_with_the_passport_fresh_and_stale(canonical):
    root, pp = canonical
    v = pp["verdict"]
    md = cli(root, "prove", "report", "c", agent=False)
    js = cli(root, "prove", "report", "c", "--format", "json", agent=False)
    it = cli(root, "prove", "report", "c", "--format", "in-toto", agent=False)
    assert md.returncode == js.returncode == it.returncode == 0, (md.stderr, js.stderr, it.stderr)
    assert v["headline"] in md.stdout
    rj = json.loads(js.stdout)
    assert rj["verdict"] == v and rj["evidence"][0]["claim"]["level"] == v["level"]
    assert json.loads(it.stdout)["predicate"]["verdict"] == v
    # stale: the working tree moves on. Every export must say so, or not say "supported"
    write(root, {"calc/__init__.py": FIXED + "# later\n"})
    try:
        st = cli(root, "prove", "status", "c", "--json", agent=False)
        assert json.loads(st.stdout)["state"] == "stale"
        md = cli(root, "prove", "report", "c", agent=False)
        assert md.returncode == 2 and "STALE" in md.stdout
        it = cli(root, "prove", "report", "c", "--format", "in-toto", agent=False)
        pred = json.loads(it.stdout)["predicate"]
        assert it.returncode == 2
        assert pred.get("freshness", {}).get("state") == "stale" or not pred["verdict"]["supported"], (
            "X7: the in-toto statement of a stale passport says verdict supported and carries no freshness: "
            f"{pred['verdict']['state']}, keys {sorted(pred)}")
    finally:
        write(root, {"calc/__init__.py": FIXED})


def test_x2_nothing_selected_never_supports_a_claim(tmp_path: Path):
    root = make_repo(tmp_path / "x2", {
        "mathx.py": BUGGY, "strs.py": "def shout(s):\n    return s.upper()\n", "tests/__init__.py": "",
        "tests/test_strs.py": "import unittest\nfrom strs import shout\n\n\nclass T(unittest.TestCase):\n"
                              "    def test_shout(self):\n        self.assertEqual(shout('a'), 'A')\n"})
    # runtime evidence: no recorded test executes mathx.py, so verify needs no full suite and selects nothing
    rec = cli(root, "verify", "--record", *UT, agent=False)
    assert rec.returncode == 0, rec.stderr[-600:]
    outside = tmp_path / "reviewer" / "test_accept.py"
    write(outside.parent, {"test_accept.py": "import unittest\nfrom mathx import mean\n\n\nclass A(unittest.TestCase):"
                                             "\n    def test_empty(self):\n        self.assertEqual(mean([]), 0)\n"})
    write(root, {"mathx.py": FIXED})
    code, pp = pin_and_run(root, "tests/test_accept.py", outside, *UT)
    reg = pp["regressions"] or {}
    # fixture sanity: the case the rule is about (verify selects no test file and runs no full suite)
    assert reg.get("selected") == 0 and reg.get("full_suite") in {None, "not-run"}, reg
    # (the embedded record may keep the scenario comparison's own level, as for any non-supported verdict:
    # it is about the scenario alone and names the verdict in not_established[])
    assert pp["verdict"]["state"] != "supported" and reg.get("state") != "none-detected", (
        f"X2: verify selected nothing ({reg.get('verdict')}, regressions {reg.get('state')}) and the passport is "
        f"{pp['verdict']['state']} at level {pp['evidence'][0]['claim']['level']}")


@pytest.mark.skipif(not NODE_SANDBOX or not shutil.which("node"), reason="the sandbox cannot start node here")
@pytest.mark.xfail(strict=True, reason="by design since the corrective phase (Session B, 2026-10-25): a node claim is "
                   "never supported, because JavaScript scenarios are not parsed (the seventh review's CommonJS re-export)")
def test_x1_list_mode_status_checks_the_environment_like_single_status(tmp_path: Path):
    root = make_repo(tmp_path / "x1", {
        ".gitignore": "node_modules/\n",
        "package.json": '{"name": "x1", "version": "1.0.0", "type": "module"}\n',
        "node_modules/dep/package.json": '{"name": "dep", "version": "1.0.0"}\n',
        "lib/m.js": "export function clamp(x, lo, hi) { if (x < lo) return lo; if (x > hi) return hi; return x; }\n",
        "test/clamp.test.js": ("import { test } from 'node:test';\nimport assert from 'node:assert';\n"
                               "import { clamp } from '../lib/m.js';\n"
                               "test('clamp low', () => { assert.strictEqual(clamp(-1, 0, 5), 0); });\n")})
    outside = tmp_path / "reviewer" / "accept.test.js"
    write(outside.parent, {"accept.test.js": (
        "import { test } from 'node:test';\nimport assert from 'node:assert';\nimport { clamp } from '../lib/m.js';\n"
        "test('clamp rejects NaN', () => { assert.throws(() => clamp(NaN, 0, 1)); });\n")})
    write(root, {"lib/m.js": "export function clamp(x, lo, hi) { if (Number.isNaN(x)) throw new Error('NaN'); "
                             "if (x < lo) return lo; if (x > hi) return hi; return x; }\n"})
    code, pp = pin_and_run(root, "test/accept.test.js", outside, "--test-command", "node --test")
    assert code == 0 and pp["verdict"]["state"] == "supported", pp["verdict"]
    # a second claim, so that `prove status` without an id lists them
    pin2 = cli(root, "prove", "pin", "d", "--claim", "y", "--scenario", "test/clamp.test.js", "--test-command",
               "node --test", agent=False)
    assert pin2.returncode == 0, pin2.stderr
    single = json.loads(cli(root, "prove", "status", "c", "--json", agent=False).stdout)
    assert single["state"] == "fresh", single
    # the test environment changes (a package appears in node_modules); the working tree does not
    write(root, {"node_modules/other/package.json": '{"name": "other", "version": "1.0.0"}\n'})
    single = json.loads(cli(root, "prove", "status", "c", "--json", agent=False).stdout)
    assert single["state"] == "stale", single  # sanity: verify's environment key moved
    listed = {r["claim"]: r for r in json.loads(cli(root, "prove", "status", "--json", agent=False).stdout)["claims"]}
    assert listed["c"]["state"] == single["state"], (
        f"X1: `prove status` (list) says {listed['c']['state']} ({listed['c'].get('verdict')}) while "
        f"`prove status c` says {single['state']}: {single['reasons']}")


def test_x8_a_control_that_times_out_is_not_a_reproduction(tmp_path: Path):
    root = make_repo(tmp_path / "x8", {
        "calc/__init__.py": "def wait_for(n):\n    while n < 0:\n        pass\n    return n\n",
        "tests/__init__.py": "",
        "tests/test_calc.py": "import unittest\nfrom calc import wait_for\n\n\nclass T(unittest.TestCase):\n"
                              "    def test_one(self):\n        self.assertEqual(wait_for(1), 1)\n"})
    outside = tmp_path / "reviewer" / "test_accept.py"
    write(outside.parent, {"test_accept.py": "import unittest\nfrom calc import wait_for\n\n\n"
                                             "class A(unittest.TestCase):\n    def test_negative(self):\n"
                                             "        with self.assertRaises(ValueError):\n            wait_for(-1)\n"})
    write(root, {"calc/__init__.py": "def wait_for(n):\n    if n < 0:\n        raise ValueError(n)\n    return n\n"})
    code, pp = pin_and_run(root, "tests/test_accept.py", outside, *UT, run_extra=("--timeout", "6"))
    rec = pp["evidence"][0]
    assert all(o["state"] == "timeout" for o in rec["sides"]["control"]["observations"]), rec["sides"]["control"]
    assert pp["verdict"]["state"] != "supported"
    assert rec["claim"]["level"] not in {"regression_reproduced", "supported_by_controlled_comparison"}, rec["claim"]
