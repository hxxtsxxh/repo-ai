"""ProofLab (`repo-ai prove`): a supported claim needs the targeted failure at
the base, the same scenario bytes passing at the candidate under the same
conditions, no regression, and an untouched source tree. Everything else,
missing or incomplete evidence included, is "not established"."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from conftest import run_cli
from repo_ai.prove import claim as cl
from repo_ai.prove import conditions, experiment, passport, render
from test_verify_adaptive import NODE_SANDBOX, _git, _write
from test_verify_engine import _host_sandbox

HOST = _host_sandbox()
needs_sandbox = pytest.mark.skipif(not HOST, reason="no sandbox backend to run tests in")
TERMINAL = {"PATH": "/usr/bin:/bin"}  # no agent-shell variable set


def obs(outcomes: dict[str, str], failures: dict[str, str] | None = None, trusted: bool = True,
        reason: str = "") -> dict:
    return {"exit_code": 1 if "fail" in outcomes.values() else 0, "timed_out": False, "seconds": 0.1,
            "trusted": trusted, "reason": reason, "tests": len(outcomes), "skipped": 0, "outcomes": outcomes,
            "failures": failures or {t: "AssertionError: 1 != 0" for t, o in outcomes.items() if o == "fail"},
            "hung": []}


# --------------------------------------------------------------------------
# judgements (no execution)
# --------------------------------------------------------------------------
def test_a_behavioural_failure_at_the_base_is_reproduced():
    b = experiment.judge_baseline([obs({"t.a": "fail", "t.b": "pass"})] * 2, [], None)
    assert b["state"] == "reproduced" and b["targets_failing"] == ["t.a"] and b["kind"] == "behaviour"


def test_a_scenario_that_passes_at_the_base_does_not_reproduce_anything():
    assert experiment.judge_baseline([obs({"t.a": "pass"})] * 2, [], None)["state"] == "not-reproduced"


def test_a_scenario_that_cannot_import_the_original_code_is_a_load_failure_not_a_reproduction():
    runs = [obs({"t.a": "fail"}, {"t.a": "ImportError: cannot import name 'mean_or_zero' from 'calc'"})] * 2
    assert experiment.judge_baseline(runs, [], None)["state"] == "load-failure"
    file_level = [obs({"<file>": "fail"}, {"<file>": "ModuleNotFoundError: No module named 'calc.new'"})]
    assert experiment.judge_baseline(file_level, [], None)["state"] == "load-failure"
    # unless the claim pins that very failure
    assert experiment.judge_baseline(runs, [], r"cannot import name")["state"] == "reproduced"


def test_the_pinned_failure_pattern_must_match_every_run():
    runs = [obs({"t.a": "fail"}, {"t.a": "TypeError: unsupported operand"})] * 2
    b = experiment.judge_baseline(runs, [], r"ZeroDivisionError")
    assert b["state"] == "not-reproduced" and b["kind"] == "unexpected"


def test_pinned_targets_must_fail_at_the_base():
    runs = [obs({"t.a": "fail", "t.b": "pass"})]
    assert experiment.judge_baseline(runs, ["t.b"], None)["state"] == "not-reproduced"
    assert experiment.judge_baseline(runs, ["t.missing"], None)["state"] == "not-reproduced"
    assert experiment.judge_baseline(runs, ["t.a"], None)["targets_failing"] == ["t.a"]


@pytest.mark.parametrize("runs", [
    [obs({"t.a": "fail"}), obs({"t.a": "pass"})],                       # flaky at the base
    [obs({"t.a": "fail"}), obs({}, trusted=False, reason="the process timed out")],
    [obs({}, trusted=False, reason="no per-test report was written")],
])
def test_an_inconsistent_or_untrusted_base_is_incomplete(runs):
    assert experiment.judge_baseline(runs, [], None)["state"] == "incomplete"


def test_the_candidate_passes_only_when_every_test_of_the_scenario_passes_every_time():
    base = [obs({"t.a": "fail", "t.b": "pass"})] * 2
    good = experiment.judge_candidate([obs({"t.a": "pass", "t.b": "pass"})] * 2, base, ["t.a"])
    assert good["state"] == "passed"
    bad = experiment.judge_candidate([obs({"t.a": "pass", "t.b": "fail"})] * 2, base, ["t.a"])
    assert bad["state"] == "failed" and bad["failing"] == ["t.b"]


@pytest.mark.parametrize("runs,why", [
    ([obs({"t.a": "pass"}), obs({"t.a": "fail"})], "candidate"),                       # a flaky failure: failed
    ([obs({"t.a": "pass"}), obs({}, trusted=False, reason="the process timed out")], "incomplete"),
    ([obs({"t.a": "skip", "t.b": "pass"})] * 2, "skipped"),                            # the target skipped
    ([obs({"t.b": "pass"})] * 2, "did not run"),                                       # the target vanished
    ([obs({})] * 2, "no test"),                                                        # nothing ran
])
def test_missing_skipped_or_incomplete_candidate_evidence_is_never_a_pass(runs, why):
    c = experiment.judge_candidate(runs, [obs({"t.a": "fail", "t.b": "pass"})], ["t.a"])
    assert c["state"] != "passed", c


def test_a_test_that_ran_at_the_base_and_is_skipped_at_the_candidate_is_incomplete():
    base = [obs({"t.a": "fail", "t.b": "pass"})]
    c = experiment.judge_candidate([obs({"t.a": "pass", "t.b": "skip"})], base, ["t.a"])
    assert c["state"] == "incomplete" and "skipped" in c["why"]


def test_base_versions_of_edited_tests_that_now_fail_are_regressions_unless_superseded():
    pair = {"path": "tests/test_calc.py", "status": "modified",
            "base": obs({"t.clamp": "pass", "t.mean": "pass"}),
            "candidate": obs({"t.clamp": "fail", "t.mean": "pass"})}
    assert experiment.judge_edited([pair], [])["state"] == "detected"
    ok = experiment.judge_edited([pair], ["t.clamp"])
    assert ok["state"] == "none-detected" and ok["files"][0]["superseded"] == ["t.clamp"]
    failing_at_base_too = {**pair, "base": obs({"t.clamp": "fail", "t.mean": "pass"})}
    assert experiment.judge_edited([failing_at_base_too], [])["state"] == "none-detected"
    untrusted = {**pair, "candidate": obs({}, trusted=False, reason="the process timed out")}
    assert experiment.judge_edited([untrusted], [])["state"] == "incomplete"


@pytest.mark.parametrize("verdict,state", [
    ("selected-passed (full suite not run)", "none-detected"),
    ("selected-and-full-suite-passed", "none-detected"),
    ("regression", "detected"),
    ("failing (all failures pre-existing at the base)", "none-detected"),
    ("failing (only next to other test files: order-dependent or flaky)", "incomplete"),
    ("selected-passed; full suite REQUIRED but not run", "incomplete"),
    ("no tests ran: the selected files define none", "incomplete"),
    ("invalid: the source tree changed during the run", "incomplete"),
])
def test_verify_verdicts_map_to_regression_states(verdict, state):
    rec = {"verdict": verdict, "results": [], "selected": [], "plan": {}}
    assert experiment.judge_regressions(rec, "", True)["state"] == state
    assert experiment.judge_regressions(None, "boom", True)["state"] == "incomplete"
    assert experiment.judge_regressions(None, "", False)["state"] == "not-checked"


def _parts(**over):
    good = {"baseline": {"state": "reproduced", "why": ""}, "candidate": {"state": "passed", "why": ""},
            "edited": {"state": "none-edited", "files": []}, "regressions": {"state": "none-detected", "why": ""},
            "integrity": {"unchanged": True}}
    good.update(over)
    return good


def test_only_a_complete_clean_experiment_is_supported():
    p = _parts()
    assert passport.decide(None, p["baseline"], p["candidate"], p["edited"], p["regressions"],
                           p["integrity"])["state"] == "supported"
    cases = {
        "candidate-failed": _parts(candidate={"state": "failed", "why": "x"}),
        "baseline-not-reproduced": _parts(baseline={"state": "load-failure", "why": "x"}),
        "regressions-detected": _parts(regressions={"state": "detected", "why": "x"}),
        "incomplete": _parts(regressions={"state": "not-checked", "why": "x"}),
    }
    for want, p in cases.items():
        v = passport.decide(None, p["baseline"], p["candidate"], p["edited"], p["regressions"], p["integrity"])
        assert v["state"] == want and not v["supported"], (want, v)
    p = _parts(integrity={"unchanged": False, "changes": ["calc.py: modified"]})
    v = passport.decide(None, p["baseline"], p["candidate"], p["edited"], p["regressions"], p["integrity"])
    assert v["state"] == "incomplete" and not v["supported"]
    p = _parts(edited={"state": "detected", "files": [{"path": "t.py", "state": "detected", "new_failures": ["x"]}]})
    v = passport.decide(None, p["baseline"], p["candidate"], p["edited"], p["regressions"], p["integrity"])
    assert v["state"] == "regressions-detected"


def test_problems_found_before_running_decide_the_verdict_and_nothing_is_supported():
    v = passport.decide([{"state": "conditions-differ", "why": "a"}, {"state": "scenario-changed", "why": "b"}],
                        None, None, None, None, None)
    assert v["state"] == "scenario-changed" and not v["supported"] and v["reasons"] == ["a", "b"]


# --------------------------------------------------------------------------
# the oracle's conditions (read-only)
# --------------------------------------------------------------------------
def _reader(files: dict[str, str]):
    return list(files), lambda rel: files[rel].encode() if rel in files else None


def test_conftest_helpers_and_data_next_to_the_scenario_are_oracle_inputs():
    base = {"tests/conftest.py": "x = 1\n", "tests/helpers.py": "def check(a, b): assert a == b\n",
            "tests/data/expected.json": "[1]\n", "tests/test_accept.py": "", "tests/test_other.py": "",
            "calc/__init__.py": "def f(): pass\n", "pyproject.toml": "[project]\nname='x'\n"}
    tests = {"tests/test_accept.py", "tests/test_other.py"}

    def diff(**changes: str) -> list[str]:
        files, read = _reader(base)
        a = conditions.inputs("tests/test_accept.py", "pytest", files, read, test_files=tests, pinned=set())
        files2, read2 = _reader({**base, **changes})
        b = conditions.inputs("tests/test_accept.py", "pytest", files2, read2, test_files=tests, pinned=set())
        return conditions.compare(a, b)
    assert diff() == []
    assert diff(**{"tests/conftest.py": "x = 2\n"}) == ["tests/conftest.py"]
    assert diff(**{"conftest.py": "import pytest\n"}) == ["conftest.py"]
    assert diff(**{"tests/helpers.py": "def check(a, b): pass\n"}) == ["tests/helpers.py"]
    assert diff(**{"tests/data/expected.json": "[2]\n"}) == ["tests/data/expected.json"]
    # the code under test, other test files and non-pytest configuration are not oracle inputs
    assert diff(**{"calc/__init__.py": "def f(): return 1\n"}) == []
    assert diff(**{"tests/test_other.py": "x"}) == []
    assert diff(**{"pyproject.toml": "[project]\nname='x'\ndependencies=['a']\n"}) == []
    assert diff(**{"pyproject.toml": "[tool.pytest.ini_options]\naddopts='-p no:x'\n"}) == ["pyproject.toml#pytest"]
    assert diff(**{"setup.cfg": "[tool:pytest]\naddopts = -q\n"}) == ["setup.cfg#pytest"]
    assert diff(**{"setup.cfg": "[metadata]\nname = x\n"}) == []


def test_a_pinned_support_file_is_not_compared_and_a_scenario_outside_test_dirs_ignores_its_neighbours():
    files, read = _reader({"tests/conftest.py": "x\n"})
    out = conditions.inputs("tests/test_a.py", "pytest", files, read, test_files=set(), pinned={"tests/conftest.py"})
    assert "tests/conftest.py" not in out
    files, read = _reader({"calc/helper.py": "x\n", "calc/test_a.py": ""})
    out = conditions.inputs("calc/test_a.py", "pytest", files, read, test_files={"calc/test_a.py"}, pinned=set())
    assert "calc/helper.py" not in out


def test_node_package_type_is_an_oracle_input_but_dependencies_are_not():
    def at(pkg: dict) -> dict:
        files, read = _reader({"package.json": json.dumps(pkg)})
        return conditions.inputs("test/a.test.js", "node", files, read, test_files=set(), pinned=set())
    assert conditions.compare(at({"type": "module"}), at({"type": "commonjs"})) == ["package.json#type,imports"]
    assert conditions.compare(at({"dependencies": {"a": "1"}}), at({"dependencies": {"a": "2"}})) == []


def test_scenario_notes_flag_skips_and_missing_assertions():
    assert conditions.scenario_notes(b"import pytest\n@pytest.mark.skip\ndef test_a():\n    assert 1\n", "pytest")
    assert conditions.scenario_notes(b"def test_a():\n    print(1)\n", "pytest")
    assert conditions.scenario_notes(b"def test_a():\n    assert f() == 1\n", "pytest") == []


# --------------------------------------------------------------------------
# pinning
# --------------------------------------------------------------------------
def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    _write(root, {"tests/test_a.py": "def test_a():\n    assert 1\n"})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def test_a_pin_keeps_the_exact_bytes_and_refuses_edits_to_its_record(tmp_path: Path):
    root = _repo(tmp_path)
    state = tmp_path / "state"
    rec = cl.pin(root, state, text="a  claim", scenario="tests/test_a.py", claim_id="c1", env=TERMINAL)
    assert rec["claim"]["text"] == "a claim" and rec["pinned_by"] == {"agent_shell": False, "signals": []}
    assert cl.load_blob(state, rec["scenario"]["sha256"]) == (root / "tests" / "test_a.py").read_bytes()
    path = state / "prove" / "claims" / "c1.json"
    data = json.loads(path.read_text())
    data["scenario"]["sha256"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(cl.ClaimError, match="edited outside"):
        cl.load(state, "c1")


def test_a_tampered_blob_is_refused(tmp_path: Path):
    root = _repo(tmp_path)
    state = tmp_path / "state"
    rec = cl.pin(root, state, text="c", scenario="tests/test_a.py", claim_id="c1", env=TERMINAL)
    (state / "prove" / "blobs" / rec["scenario"]["sha256"]).write_bytes(b"def test_a():\n    pass\n")
    with pytest.raises(cl.ClaimError, match="no longer match"):
        cl.load_blob(state, rec["scenario"]["sha256"])


def test_replacing_a_pin_needs_replace_and_a_terminal_pin_cannot_be_replaced_from_an_agent_shell(tmp_path: Path):
    root = _repo(tmp_path)
    state = tmp_path / "state"
    cl.pin(root, state, text="c", scenario="tests/test_a.py", claim_id="c1", env=TERMINAL)
    assert cl.pin(root, state, text="c", scenario="tests/test_a.py", claim_id="c1", env=TERMINAL)["history"] == []
    (root / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    with pytest.raises(cl.ClaimError, match="--replace"):
        cl.pin(root, state, text="c", scenario="tests/test_a.py", claim_id="c1", env=TERMINAL)
    with pytest.raises(cl.ClaimError) as exc:
        cl.pin(root, state, text="c", scenario="tests/test_a.py", claim_id="c1", replace=True,
               env={"CLAUDECODE": "1"})
    assert exc.value.exit_code == cl.EXIT_REFUSED
    again = cl.pin(root, state, text="c", scenario="tests/test_a.py", claim_id="c1", replace=True, env=TERMINAL)
    assert len(again["history"]) == 1


def test_a_scenario_pinned_from_a_commit_records_its_blob(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "tests" / "test_a.py").write_text("# edited in the working tree\n")
    rec = cl.pin(root, tmp_path / "s", text="c", scenario="tests/test_a.py", revision="HEAD", env=TERMINAL)
    prov = rec["scenario"]["provenance"]
    blob = subprocess.run(["git", "rev-parse", "HEAD:tests/test_a.py"], cwd=root, capture_output=True,
                          text=True).stdout.strip()
    assert prov["kind"] == "git" and prov["blob"] == blob
    assert cl.load_blob(tmp_path / "s", rec["scenario"]["sha256"]) == b"def test_a():\n    assert 1\n"


@pytest.mark.parametrize("bad", ["../x.py", "/etc/passwd", ".git/config", ".repo-ai/state/x", "~/x.py", ""])
def test_scenario_paths_stay_inside_the_repository(tmp_path: Path, bad: str):
    with pytest.raises(cl.ClaimError):
        cl.pin(_repo(tmp_path), tmp_path / "s", text="c", scenario=bad, env=TERMINAL)


def test_a_redacted_claim_keeps_only_its_hash(tmp_path: Path):
    rec = cl.pin(_repo(tmp_path), tmp_path / "s", text="secret plan", scenario="tests/test_a.py", redact=True,
                 env=TERMINAL)
    assert rec["claim"]["text"] is None and rec["claim"]["sha256"] == cl.sha256(b"secret plan")


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
def _passport(msg: str = "AssertionError: 1 != 0") -> dict:
    return {
        "schema": passport.SCHEMA, "created": "2026-10-24T00:00:00+00:00", "repo_ai_version": "0",
        "claim": {"id": "c1", "text": "mean([]) is 0 @someone <b>x</b>", "sha256": "a" * 64, "pinned": {},
                  "redacted": False},
        "scenario": {"path": "tests/test_a.py", "sha256": "b" * 64, "provenance": {"kind": "worktree"}},
        "baseline": {"revision": "HEAD", "commit": "c" * 40},
        "candidate": {"fingerprint": "d" * 64, "changed_files_total": 1},
        "conditions": {"runner": {"command": "python -m pytest"}, "command": "python -m pytest tests/test_a.py",
                       "oracle": {"checked": 1}},
        "observations": {"baseline": {"state": "reproduced", "repeats": [obs({"t.a": "fail"}, {"t.a": msg})]},
                         "candidate": {"state": "passed", "repeats": [obs({"t.a": "pass"})]}},
        "edited_tests": {"state": "none-edited", "files": []}, "regressions": {"state": "none-detected"},
        "integrity": {"unchanged": True}, "executed": True, "seconds": 1.0,
        "verdict": passport.decide(None, *[_parts()[k] for k in ("baseline", "candidate", "edited", "regressions",
                                                                 "integrity")]),
        "limitations": ["l"], "untested": ["u"], "reproduce": ["repo-ai prove run c1"], "environment": {},
        "digest": "e" * 64,
    }


def test_untrusted_output_cannot_break_out_of_the_markdown_report():
    hostile = "\x1b[31mred\x1b[0m ` ``` <img src=x onerror=alert(1)> @octocat [link](http://x) \u0007" + "A" * 5000
    md = render.markdown(_passport(hostile))
    assert "\x1b" not in md and "\u0007" not in md and "A" * 400 not in md
    line = next(ln for ln in md.splitlines() if ln.startswith("- `t.a`"))
    span = line.split(": ", 1)[1]
    assert span.startswith("`") and span.endswith("`") and span.count("`") == 2  # one closed code span
    assert "@​someone" in md and "&lt;b&gt;" in md  # the claim cannot mention people or inject HTML


def test_the_same_passport_always_renders_to_the_same_bytes():
    pp = _passport()
    assert render.markdown(pp) == render.markdown(json.loads(json.dumps(pp)))
    assert render.text(pp) == render.text(pp)


def test_the_in_toto_statement_names_the_candidate_and_the_scenario():
    st = render.in_toto(_passport())
    assert st["_type"] == "https://in-toto.io/Statement/v1"
    assert {s["name"] for s in st["subject"]} == {"candidate-working-tree", "tests/test_a.py"}
    assert all(s["digest"] for s in st["subject"]) and st["predicate"]["signed"] is False


# --------------------------------------------------------------------------
# end to end, sandboxed
# --------------------------------------------------------------------------
GOOD = "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n\n\ndef clamp(x, lo, hi):\n    return max(lo, min(x, hi))\n"
ACCEPT = ("import unittest\nfrom calc import mean\n\n\nclass Accept(unittest.TestCase):\n"
          "    def test_mean_of_empty_is_zero(self):\n        self.assertEqual(mean([]), 0)\n")


@pytest.fixture(scope="module")
def py_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("prove") / "calc"
    _write(root, {"calc/__init__.py": GOOD.replace(" if xs else 0", ""),
                  "tests/__init__.py": "",
                  "tests/test_calc.py": ("import unittest\nfrom calc import mean, clamp\n\n\n"
                                         "class T(unittest.TestCase):\n"
                                         "    def test_mean(self):\n        self.assertEqual(mean([1, 2, 3]), 2)\n\n"
                                         "    def test_clamp(self):\n        self.assertEqual(clamp(5, 0, 3), 3)\n")})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "tests" / "test_accept.py").write_text(ACCEPT)
    # the code under test declared, as a supported claim needs (an inferred subject is chosen by the change)
    pin = run_cli(root, "prove", "pin", "empty", "--claim", "mean([]) returns 0", "--scenario",
                  "tests/test_accept.py", "--subject", "calc/__init__.py")
    assert pin.returncode == 0, pin.stderr
    return root


def _prove(root: Path, *extra: str) -> tuple[int, dict]:
    proc = run_cli(root, "prove", "run", "empty", "--json", *extra)
    assert proc.stdout.strip(), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def _set(root: Path, calc: str, scenario: str = ACCEPT, test_calc: str | None = None) -> None:
    (root / "calc" / "__init__.py").write_text(calc)
    (root / "tests" / "test_accept.py").write_text(scenario)
    _git(root, "checkout", "-q", "tests/test_calc.py")
    if test_calc is not None:
        (root / "tests" / "test_calc.py").write_text(test_calc)


@needs_sandbox
def test_every_surface_says_prooflab_is_experimental_and_names_the_open_false_proof(py_repo: Path):
    """Release freeze (2026-10-26): a supported passport, its Markdown, terminal text, in-toto statement and
    evidence record all say that ProofLab is experimental and not certified, and name the open false proof."""
    _set(py_repo, GOOD)
    code, pp = _prove(py_repo)
    assert code == 0 and pp["verdict"]["state"] == "supported", pp["verdict"]
    st = pp["experimental"]
    assert st["status"] == "experimental" and st["certified"] is False
    assert [k["id"] for k in st["known_false_proofs"]] == ["always-equal-class", "swallowed-assertion",
                                                         "importorskip-zero-entry-points"]
    assert all(k["open"] for k in st["known_false_proofs"]) and "issue #59" in st["unexecuted_paths"]
    assert "EXPERIMENTAL" in pp["verdict"]["headline"] and pp["limitations"][0].startswith("EXPERIMENTAL, NOT CERTIFIED")
    assert any(x.startswith("KNOWN FALSE PROOF (open, always-equal-class)") for x in pp["limitations"])
    rec = pp["evidence"][0]["claim"]["not_established"]
    assert "ProofLab is experimental and not certified" in rec and "known false proof (open): always-equal-class" in rec
    assert "known false proof (open): swallowed-assertion" in rec
    md = run_cli(py_repo, "prove", "report", "empty").stdout
    assert "EXPERIMENTAL, NOT CERTIFIED" in md and "always-equal-class" in md
    stmt = json.loads(run_cli(py_repo, "prove", "report", "empty", "--format", "in-toto").stdout)
    assert stmt["predicate"]["experimental"]["certified"] is False
    assert stmt["predicate"]["experimental"]["known_false_proofs"][0]["id"] == "always-equal-class"
    text = run_cli(py_repo, "prove", "run", "empty").stdout
    assert text.startswith("EXPERIMENTAL, NOT CERTIFIED") and "always-equal-class" in text.splitlines()[0]


def test_a_passport_that_stopped_before_running_still_states_the_standing():
    from repo_ai.prove import passport as ppm
    lim = ppm.experimental_notes() + ["Nothing ran: the experiment stopped before execution."]
    assert lim[0].startswith("EXPERIMENTAL, NOT CERTIFIED") and "always-equal-class" in lim[1]
    assert ppm.EXPERIMENTAL["certified"] is False


@needs_sandbox
def test_a_real_fix_is_supported_and_goes_stale_after_an_edit(py_repo: Path):
    _set(py_repo, GOOD)
    code, pp = _prove(py_repo)
    assert code == 0 and pp["verdict"]["state"] == "supported", pp["verdict"]
    assert pp["observations"]["baseline"]["targets_failing"] == ["test_accept.Accept.test_mean_of_empty_is_zero"] \
        or pp["observations"]["baseline"]["targets_failing"][0].endswith("test_mean_of_empty_is_zero")
    assert "ZeroDivisionError" in json.dumps(pp["observations"]["baseline"])
    assert pp["integrity"]["unchanged"] and pp["regressions"]["state"] == "none-detected"
    assert run_cli(py_repo, "prove", "status", "empty").returncode == 0
    report = run_cli(py_repo, "prove", "report", "empty")
    assert report.returncode == 0 and "CLAIM SUPPORTED" in report.stdout
    (py_repo / "calc" / "__init__.py").write_text(GOOD + "# later edit\n")
    assert run_cli(py_repo, "prove", "status", "empty").returncode == 2
    assert run_cli(py_repo, "prove", "report", "empty").returncode == 2


@needs_sandbox
def test_a_candidate_that_does_not_fix_the_bug_is_not_supported(py_repo: Path):
    _set(py_repo, GOOD.replace(" if xs else 0", "") + "# no fix\n")
    code, pp = _prove(py_repo)
    assert code == 1 and pp["verdict"]["state"] == "candidate-failed"


@needs_sandbox
def test_a_fix_that_breaks_related_behaviour_is_not_supported(py_repo: Path):
    _set(py_repo, GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"))
    code, pp = _prove(py_repo)
    assert code == 1 and pp["verdict"]["state"] == "regressions-detected"


@needs_sandbox
def test_a_regression_hidden_by_editing_the_existing_test_is_found(py_repo: Path):
    """`verify --run` passes here: the edited test passes. The base's own
    version of that test does not."""
    edited = (py_repo / "tests" / "test_calc.py").read_text().replace("clamp(5, 0, 3), 3)", "clamp(5, 0, 3), 0)")
    _set(py_repo, GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"), test_calc=edited)
    assert run_cli(py_repo, "verify", "--run", "--json").returncode == 0  # verify alone sees nothing wrong
    code, pp = _prove(py_repo)
    assert code == 1 and pp["verdict"]["state"] == "regressions-detected"
    row = pp["edited_tests"]["files"][0]
    assert row["path"] == "tests/test_calc.py" and any(t.endswith("test_clamp") for t in row["new_failures"])
    _git(py_repo, "checkout", "-q", "tests/test_calc.py")


@needs_sandbox
def test_a_weakened_scenario_stops_the_experiment_before_anything_runs(py_repo: Path):
    _set(py_repo, GOOD, scenario=ACCEPT.replace("mean([]), 0)", "1, 1)"))
    code, pp = _prove(py_repo)
    assert code == 1 and pp["verdict"]["state"] == "scenario-changed" and pp["executed"] is False
    assert pp["observations"] == {"baseline": None, "candidate": None}


@needs_sandbox
def test_a_conftest_change_by_the_candidate_means_the_conditions_differ(py_repo: Path):
    _set(py_repo, GOOD)
    (py_repo / "tests" / "conftest.py").write_text("# the candidate's fixture\n")
    try:
        code, pp = _prove(py_repo)
    finally:
        (py_repo / "tests" / "conftest.py").unlink()
    assert code == 1 and pp["verdict"]["state"] == "conditions-differ" and pp["executed"] is False


@needs_sandbox
def test_a_hanging_scenario_is_incomplete_never_supported(py_repo: Path):
    hang = ACCEPT.replace("self.assertEqual(mean([]), 0)", "self.assertEqual(mean([]), 0)\n"
                                                             "        import time\n        while True: time.sleep(1)")
    (py_repo / "tests" / "test_hang.py").write_text(hang)
    try:
        assert run_cli(py_repo, "prove", "pin", "hang", "--claim", "x", "--scenario", "tests/test_hang.py"
                       ).returncode == 0
        _set(py_repo, GOOD)
        proc = run_cli(py_repo, "prove", "run", "hang", "--json", "--timeout", "4", "--repeat", "1")
        pp = json.loads(proc.stdout)
    finally:
        (py_repo / "tests" / "test_hang.py").unlink()
    assert proc.returncode == 1 and pp["verdict"]["state"] in {"incomplete", "baseline-not-reproduced"}
    assert pp["observations"]["candidate"]["state"] == "incomplete"


@needs_sandbox
def test_a_scenario_that_cannot_load_at_the_base_does_not_reproduce_the_bug(py_repo: Path):
    new_api = "import unittest\nfrom calc import mean_or_zero\n\n\nclass N(unittest.TestCase):\n" \
              "    def test_new(self):\n        self.assertEqual(mean_or_zero([]), 0)\n"
    (py_repo / "tests" / "test_newapi.py").write_text(new_api)
    try:
        assert run_cli(py_repo, "prove", "pin", "newapi", "--claim", "x", "--scenario", "tests/test_newapi.py"
                       ).returncode == 0
        _set(py_repo, GOOD + "\n\ndef mean_or_zero(xs):\n    return mean(xs)\n")
        proc = run_cli(py_repo, "prove", "run", "newapi", "--json", "--repeat", "1")
        pp = json.loads(proc.stdout)
    finally:
        (py_repo / "tests" / "test_newapi.py").unlink()
    assert proc.returncode == 1 and pp["verdict"]["state"] == "baseline-not-reproduced"
    assert pp["observations"]["baseline"]["state"] == "load-failure"


@needs_sandbox
def test_plan_runs_nothing_and_says_what_would_run(py_repo: Path):
    _set(py_repo, GOOD)
    proc = run_cli(py_repo, "prove", "plan", "empty", "--json")
    assert proc.returncode == 0, proc.stderr
    plan = json.loads(proc.stdout)
    assert plan["ready"] and plan["scenario"]["in_candidate_tree"] == "identical"
    assert plan["scenario"]["in_base_tree"] == "absent" and plan["oracle"]["identical"]


@pytest.mark.skipif(not NODE_SANDBOX, reason="the sandbox cannot start node here")
def test_node_scenarios_run_but_never_support_a_claim_and_their_failures_still_show(tmp_path: Path):
    """JavaScript is not parsed, so a node claim abstains (the seventh review: a CommonJS re-export fed the change's
    input to unchanged code); the experiment still runs and records what it saw."""
    root = tmp_path / "n"
    _write(root, {"src/slug.js": "exports.slug = (s) => s.toLowerCase().replace(' ', '-');\n",
                  "test/slug.test.js": ("const test = require('node:test'); const assert = require('node:assert');\n"
                                        "const { slug } = require('../src/slug');\n"
                                        "test('one space', () => assert.equal(slug('A B'), 'a-b'));\n")})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "test" / "accept.test.js").write_text(
        "const test = require('node:test'); const assert = require('node:assert');\n"
        "const { slug } = require('../src/slug');\n"
        "test('every space becomes a dash', () => assert.equal(slug('A B C'), 'a-b-c'));\n")
    assert run_cli(root, "prove", "pin", "slug", "--claim", "every space", "--scenario", "test/accept.test.js",
                   "--test-command", "node --test").returncode == 0
    (root / "src" / "slug.js").write_text("exports.slug = (s) => s.toLowerCase().replaceAll(' ', '-');\n")
    proc = run_cli(root, "prove", "run", "slug", "--json", "--test-command", "node --test")
    pp = json.loads(proc.stdout)
    assert pp["verdict"]["state"] == "incomplete" and pp["executed"], pp["verdict"]
    assert pp["observations"]["baseline"]["state"] == "reproduced" and pp["observations"]["candidate"]["state"] == "passed"
    assert any("JavaScript" in r for r in pp["verdict"]["reasons"]) and pp["evidence"][0]["claim"]["level"] == \
        "not_established"
    (root / "src" / "slug.js").write_text("exports.slug = (s) => s.toLowerCase().replace(' ', '-') + '';\n")
    proc = run_cli(root, "prove", "run", "slug", "--json", "--test-command", "node --test")
    assert proc.returncode == 1 and json.loads(proc.stdout)["verdict"]["state"] == "candidate-failed"


# --------------------------------------------------------------------------
# hardening (independent security review, 2026-10-24)
# --------------------------------------------------------------------------
def test_a_loaded_claim_with_a_path_outside_the_repository_is_refused_even_with_a_valid_digest(tmp_path: Path):
    root = _repo(tmp_path)
    state = tmp_path / "state"
    cl.pin(root, state, text="c", scenario="tests/test_a.py", claim_id="c1", env=TERMINAL)
    path = state / "prove" / "claims" / "c1.json"
    data = json.loads(path.read_text())
    data["support"] = [{"path": "../" * 12 + "tmp/evil", "sha256": data["scenario"]["sha256"]}]
    data["settings"] = cl.settings_digest(data)
    data["integrity"] = cl.record_digest(data)
    path.write_text(json.dumps(data))
    with pytest.raises(cl.ClaimError, match="invalid path"):
        cl.load(state, "c1")


def test_who_pinned_a_claim_cannot_be_rewritten_unnoticed(tmp_path: Path):
    root = _repo(tmp_path)
    state = tmp_path / "state"
    cl.pin(root, state, text="c", scenario="tests/test_a.py", claim_id="c1", env={"CLAUDECODE": "1"})
    path = state / "prove" / "claims" / "c1.json"
    data = json.loads(path.read_text())
    data["pinned_by"] = {"agent_shell": False, "signals": []}
    path.write_text(json.dumps(data))
    with pytest.raises(cl.ClaimError, match="edited outside"):
        cl.load(state, "c1")


def test_injection_never_writes_through_a_link_or_outside_the_copy(tmp_path: Path):
    from repo_ai.verify.isolate import Workspace
    ws = Workspace(tmp_path / "ws", tmp_path, [])
    (tmp_path / "ws").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "ws" / "tests").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(experiment.ProveError):
        experiment._inject(ws, "tests/test_x.py", b"x")
    with pytest.raises(cl.ClaimError):
        experiment._inject(ws, "../outside/x.py", b"x")
    assert not any((tmp_path / "outside").iterdir())
    (tmp_path / "ws" / "a.py").symlink_to(tmp_path / "outside" / "target.py")
    experiment._inject(ws, "a.py", b"pinned")
    assert not (tmp_path / "outside" / "target.py").exists()
    assert (tmp_path / "ws" / "a.py").read_bytes() == b"pinned" and not (tmp_path / "ws" / "a.py").is_symlink()


@pytest.mark.parametrize("bad", [".GIT/config", ".Repo-AI/state/x"])
def test_metadata_is_refused_whatever_its_case(tmp_path: Path, bad: str):
    with pytest.raises(cl.ClaimError):
        cl.norm_path(bad)


def test_a_scenario_reached_through_a_linked_directory_is_refused(tmp_path: Path):
    root = _repo(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "test_x.py").write_text("def test_x():\n    assert 1\n")
    (root / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(cl.ClaimError, match="not a regular file"):
        cl.pin(root, tmp_path / "s", text="c", scenario="linked/test_x.py", env=TERMINAL)


def test_an_interpreter_inside_the_repository_is_never_executed_for_its_version(tmp_path: Path):
    root = tmp_path / "r"
    (root / ".venv" / "bin").mkdir(parents=True)
    marker = tmp_path / "ran"
    py = root / ".venv" / "bin" / "python"
    py.write_text(f"#!/bin/sh\ntouch {marker}\necho 3.99.0\n")
    py.chmod(0o755)
    (root / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12.1\n")
    assert experiment.python_version(str(py), root) == "3.12.1 (from pyvenv.cfg)"
    assert not marker.exists()


def test_only_the_changed_oracle_inputs_are_read_and_none_is_missed_however_many_there_are():
    files = {f"tests/data/f{i}.json": "x" for i in range(3000)}
    files.update({"tests/zz_helper.py": "def ok(a, b): assert a == b\n", "tests/test_a.py": ""})
    base_files, read_b = _reader(files)
    cand_files, read_c = _reader({**files, "tests/zz_helper.py": "def ok(a, b): pass\n"})
    read: list[str] = []

    def spy(r):
        def inner(rel):
            read.append(rel)
            return r(rel)
        return inner
    a = conditions.inputs("tests/test_a.py", "pytest", base_files, spy(read_b), test_files={"tests/test_a.py"},
                          pinned=set(), only={"tests/zz_helper.py"})
    b = conditions.inputs("tests/test_a.py", "pytest", cand_files, spy(read_c), test_files={"tests/test_a.py"},
                          pinned=set(), only={"tests/zz_helper.py"})
    assert conditions.compare(a, b) == ["tests/zz_helper.py"]
    assert set(read) <= {"tests/zz_helper.py", "tests/test_a.py"}  # the scenario is read for its imports


def test_reports_break_links_and_mask_bare_credentials():
    md = render.markdown({**_passport("ghp_" + "A" * 36 + " at " + str(Path.home()) + "/x"),
                          "claim": {**_passport()["claim"], "text": r"see \[x\](http://evil.example) and www.evil.example"}})
    assert "](http" not in md and "http://evil" not in md and "www.evil" not in md
    assert "ghp_" not in md and str(Path.home()) not in md
    assert "|" not in render.code("a|b")


@needs_sandbox
def test_code_under_test_that_disables_assertions_is_never_supported(py_repo: Path):
    patched = (GOOD.replace(" if xs else 0", "") + "\n\nimport unittest as _u\n"
               "_u.TestCase.assertEqual = lambda self, a, b, msg=None: None\n"
               "_u.TestCase.assertTrue = lambda self, a, msg=None: None\n")
    _set(py_repo, patched.replace("return sum(xs) / len(xs)", "return sum(xs) / len(xs) if xs else None"))
    code, pp = _prove(py_repo)
    assert code == 1 and pp["verdict"]["state"] != "supported", pp["verdict"]
    # code that imports unittest is test machinery, never the code under test: refused before anything runs;
    # had it run, the canary would have caught it
    cand = (pp["observations"].get("candidate") or {}).get("repeats") or []
    assert pp["executed"] is False or any(r["canary"] == "tampered" for r in cand)


def test_committed_prooflab_state_is_refused(tmp_path: Path):
    root = _repo(tmp_path)
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    claim = root / ".repo-ai" / "state" / "prove" / "claims" / "x.json"
    claim.parent.mkdir(parents=True)
    claim.write_text("{}")
    _git(root, "add", "-f", str(claim.relative_to(root)))
    proc = run_cli(root, "prove", "status")
    assert proc.returncode != 0 and "git tracks ProofLab state" in proc.stderr


# --------------------------------------------------------------------------
# developer experience (independent review, 2026-10-24)
# --------------------------------------------------------------------------
def test_a_misspelt_target_names_the_ids_the_scenario_reported():
    b = experiment.judge_baseline([obs({"tests.T.test_bug": "fail"})], ["test_bug"], None)
    assert b["state"] == "not-reproduced" and "did you mean 'tests.T.test_bug'" in b["why"]


def test_a_stale_report_never_leads_with_a_supported_headline():
    md = render.markdown(_passport(), {"state": "stale", "reasons": ["the working tree changed"]})
    assert "STALE" in md.splitlines()[2] and "✅" not in md


@needs_sandbox
def test_no_change_against_the_base_is_said_before_anything_runs(py_repo: Path):
    _set(py_repo, GOOD.replace(" if xs else 0", ""))  # the original code: only the scenario differs
    proc = run_cli(py_repo, "prove", "plan", "empty")
    assert proc.returncode == 2 and "--base" in proc.stdout and "~1" in proc.stdout


@needs_sandbox
def test_status_lists_claims_and_a_claim_can_be_unpinned(py_repo: Path):
    (py_repo / "tests" / "test_extra.py").write_text(ACCEPT)
    try:
        assert run_cli(py_repo, "prove", "pin", "extra", "--claim", "x", "--scenario", "tests/test_extra.py"
                       ).returncode == 0
        listing = run_cli(py_repo, "prove", "status", "--json")
        assert listing.returncode == 0
        assert {r["claim"] for r in json.loads(listing.stdout)["claims"]} >= {"empty", "extra"}
        assert run_cli(py_repo, "prove", "pin", "extra", "--remove").returncode == 0
        assert "extra" not in run_cli(py_repo, "prove", "status", "--json").stdout
    finally:
        (py_repo / "tests" / "test_extra.py").unlink()


@needs_sandbox
def test_a_report_written_into_the_tree_says_it_makes_the_passport_stale(py_repo: Path):
    _set(py_repo, GOOD)
    assert _prove(py_repo)[0] == 0
    proc = run_cli(py_repo, "prove", "report", "empty", "--out", str(py_repo / "proof.md"))
    (py_repo / "proof.md").unlink()
    assert "stale" in proc.stderr
    inside = run_cli(py_repo, "prove", "report", "empty", "--out", str(py_repo / ".repo-ai" / "proof.md"))
    assert inside.returncode == 0 and "note:" not in inside.stderr


# --------------------------------------------------------------------------
# Session A's evidence contract (repo-ai.proof-evidence/1)
# --------------------------------------------------------------------------
from repo_ai.prove import contract  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "proof-evidence-1.schema.json"


def _check(value, schema: dict, root: dict, where: str = "$") -> list[str]:
    """The subset of JSON Schema the contract's schema uses."""
    import re as _re
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return _check(value, node, root, where)
    errs: list[str] = []
    types = schema.get("type")
    py = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float),
          "null": type(None)}
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        if not any(isinstance(value, py[t]) and not (t in {"integer", "number"} and isinstance(value, bool))
                   for t in allowed):
            return [f"{where}: {type(value).__name__} is not {types}"]
    if "const" in schema and value != schema["const"]:
        errs.append(f"{where}: {value!r} != {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {value!r} not in {schema['enum']}")
    if "pattern" in schema and isinstance(value, str) and not _re.search(schema["pattern"], value):
        errs.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
        errs.append(f"{where}: too short")
    if "not" in schema and not _check(value, schema["not"], root, where):
        errs.append(f"{where}: matches a forbidden pattern")
    if isinstance(value, dict):
        errs += [f"{where}: missing {k}" for k in schema.get("required", []) if k not in value]
        for k, sub in (schema.get("properties") or {}).items():
            if k in value:
                errs += _check(value[k], sub, root, f"{where}.{k}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{where}: fewer than {schema['minItems']} items")
        for i, item in enumerate(value):
            errs += _check(item, schema.get("items") or {}, root, f"{where}[{i}]")
    for cond in schema.get("allOf") or []:
        if not _check(value, cond["if"], root, where):
            errs += _check(value, cond["then"], root, where)
    return errs


def _record(base_states: list[str], cand_states: list[str], control: list[str], *, kind: str = "file",
            caps: list[str] | None = None) -> dict:
    def run(state: str) -> dict:
        if state == "timeout":
            return {**obs({}, trusted=False, reason="timed out"), "timed_out": True}
        return obs({"t.a": state})
    pp = _passport()
    pp["scenario"] = {**pp["scenario"], "provenance": {"kind": kind}, "in_base_tree": "absent",
                      "in_candidate_tree": "absent"}
    pp["subject"] = {"declared": True, "files": ["calc/__init__.py"], "left_out": []}
    pp["conditions"]["oracle"] = {"identical": True, "candidate_sha256": "f" * 64}
    pp["environment"] = {"backend": "seatbelt"}
    return contract.record(pp, sides_raw={"base": [run(s) for s in base_states],
                                          "candidate": [run(s) for s in cand_states],
                                          "control": [run(s) for s in control]},
                           runner_identity={"kind": "pytest"}, argv=["python -m pytest t.py"], env_key="k",
                           caps=caps or [], full_suite_passed=False, integrity_ok=True, tree="t" * 40, head="h" * 40)


@pytest.mark.parametrize("args,want", [
    ((["fail", "fail"], ["pass", "pass"], ["fail", "fail"]), "supported_by_controlled_comparison"),
    ((["fail", "fail"], ["pass", "pass"], ["fail"]), "behavior_observed"),                 # one control run (1.1)
    ((["fail", "fail"], ["pass", "pass"], ["fail"], "worktree"), "behavior_observed"),     # not independent
    ((["fail", "fail"], ["pass", "pass"], ["pass"]), "not_established"),                   # the control disagrees
    ((["fail"], ["pass"], ["fail"]), "behavior_observed"),                                 # one repeat a side
    ((["timeout", "timeout"], ["pass", "pass"], ["timeout"]), "behavior_observed"),        # a time-out is not a fail
    ((["fail", "fail"], ["pass", "fail"], ["fail"]), "not_established"),                   # flaky candidate
    ((["fail", "fail"], ["timeout", "pass"], ["fail"]), "not_established"),
])
def test_claim_levels_follow_the_contract(args, want):
    rec = _record(*args[:3], kind=args[3] if len(args) > 3 else "file")
    assert rec["claim"]["level"] == want, rec["claim"]
    assert set(contract.MINIMUM_NOT_ESTABLISHED) <= set(rec["claim"]["not_established"])


def test_fingerprint_gaps_cap_the_level_and_a_capped_supported_verdict_becomes_incomplete():
    rec = _record(["fail", "fail"], ["pass", "pass"], ["fail"], caps=["a rename is in the change (D9)"])
    assert rec["claim"]["level"] == "test_passed"
    v = {"state": "supported", "supported": True, "headline": "", "reasons": []}
    passport._align(v, rec)
    assert v["state"] == "incomplete" and not v["supported"] and "D9" in v["reasons"][0]


@pytest.mark.skipif(not SCHEMA_FILE.exists(), reason="the contract's schema is not in this tree")
@pytest.mark.parametrize("states", [(["fail", "fail"], ["pass", "pass"], ["fail"]),
                                    (["timeout"], ["fail"], [])])
def test_every_record_matches_the_contracts_schema(states):
    schema = json.loads(SCHEMA_FILE.read_text("utf-8"))
    rec = _record(*states)
    assert _check(rec, schema, schema) == []


@needs_sandbox
def test_an_external_scenario_reaches_a_controlled_comparison(py_repo: Path, tmp_path: Path):
    outside = tmp_path / "reviewer" / "test_review.py"
    outside.parent.mkdir()
    outside.write_text(ACCEPT)
    assert _terminal_cli(py_repo, "prove", "pin", "review", "--claim", "x", "--scenario", "tests/test_review.py",
                         "--file", str(outside), "--subject", "calc/*.py").returncode == 0
    try:
        _set(py_repo, GOOD)
        proc = run_cli(py_repo, "prove", "run", "review", "--json")
        pp = json.loads(proc.stdout)
    finally:
        run_cli(py_repo, "prove", "pin", "review", "--remove")
    assert proc.returncode == 0, pp["verdict"]
    rec = pp["evidence"][0]
    assert rec["claim"]["level"] == "supported_by_controlled_comparison", rec["claim"]
    assert rec["scenario"]["independent_of_change"] and rec["sides"]["control"]["observations"][0]["state"] == "fail"
    assert "controlled comparison" in pp["verdict"]["headline"]


def test_a_record_of_a_claim_that_is_not_established_says_so():
    rec = _record(["fail", "fail"], ["pass", "pass"], ["fail", "fail"])
    v = {"state": "regressions-detected", "supported": False, "headline": "", "reasons": ["verify: regression"]}
    passport._align(v, rec)
    # a claim that is not established supports nothing (Session A, superseding the earlier rule): the scenario's
    # own level is kept for display as `scenario_level`
    assert rec["claim"]["level"] == v["level"] == "not_established"
    assert rec["claim"]["scenario_level"] == "supported_by_controlled_comparison"
    assert any(x.startswith("the ProofLab claim: regressions-detected") for x in rec["claim"]["not_established"])


# --------------------------------------------------------------------------
# false proofs found by the independent adversarial review (2026-10-24)
# --------------------------------------------------------------------------
import sys as _sys  # noqa: E402

from conftest import cli_env  # noqa: E402


def _terminal_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    """repo-ai as a person runs it in a terminal: no agent-shell variable."""
    from repo_ai.capabilities import AGENT_ENV
    env = {k: v for k, v in cli_env().items() if k not in AGENT_ENV}
    return subprocess.run([_sys.executable, "-m", "repo_ai", *args, "-C", str(root)], capture_output=True, text=True,
                          env=env, timeout=300, check=False)


def _pytest_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "pt"
    _write(root, {"calc/__init__.py": GOOD.replace(" if xs else 0", ""), **files})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


PT = ["--test-command", "python -m pytest -q"]


def _pin_run(root: Path, scenario: str, *pin_extra: str) -> tuple[int, dict]:
    pin = run_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", scenario, *PT, *pin_extra)
    assert pin.returncode == 0, pin.stderr
    proc = run_cli(root, "prove", "run", "c", "--json")
    assert proc.stdout.strip(), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


@needs_sandbox
def test_f1_an_expected_failure_raised_by_the_candidate_is_not_a_pass(tmp_path: Path):
    root = _pytest_repo(tmp_path, {"tests/test_accept.py": "from calc import mean\n\n\ndef test_empty():\n"
                                                           "    assert mean([]) == 0\n"})
    (root / "calc" / "__init__.py").write_text(GOOD.replace(
        "return sum(xs) / len(xs) if xs else 0",
        "if not xs:\n        import sys\n        sys.modules['pytest'].xfail('later')\n    return sum(xs) / len(xs)"))
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert code == 1 and pp["verdict"]["state"] != "supported", pp["verdict"]


@needs_sandbox
def test_f2_a_failure_beyond_the_first_200_test_ids_is_still_seen(tmp_path: Path):
    many = "".join(f"\n\ndef test_a{i:03d}():\n    assert True\n" for i in range(250))
    scen = ("import pytest\nfrom calc import mean, clamp\n\n\ndef test_empty():\n    assert mean([]) == 0\n"
            + many + "\n\ndef test_zz_clamp():\n    assert clamp(5, 0, 3) == 3\n")
    root = _pytest_repo(tmp_path, {"tests/test_accept.py": scen})
    (root / "calc" / "__init__.py").write_text(GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"))
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert code == 1 and pp["verdict"]["state"] == "candidate-failed", pp["verdict"]


@needs_sandbox
def test_f3_f4_imported_test_helpers_and_golden_files_next_to_the_scenario_are_oracle_inputs(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "tests/test_common.py": "EXPECTED = 0\n",
        "tests/test_accept.py": "from calc import mean\nfrom tests.test_common import EXPECTED\n\n\n"
                                "def test_empty():\n    assert mean([]) == EXPECTED\n",
        "checks/expected.json": "0\n",
        "checks/test_golden.py": "import json, pathlib\nfrom calc import mean\n\n\ndef test_empty():\n"
                                 "    want = json.loads((pathlib.Path(__file__).parent / 'expected.json').read_text())\n"
                                 "    assert mean([]) == want\n", "tests/__init__.py": ""})
    (root / "calc" / "__init__.py").write_text(GOOD.replace("if xs else 0", "if xs else None"))
    (root / "tests" / "test_common.py").write_text("EXPECTED = None\n")
    (root / "checks" / "expected.json").write_text("null\n")
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert pp["verdict"]["state"] == "conditions-differ", pp["verdict"]
    assert "tests/test_common.py" in json.dumps(pp["conditions"]["oracle"]["differing"])
    run_cli(root, "prove", "pin", "c", "--remove")
    code, pp = _pin_run(root, "checks/test_golden.py")
    assert pp["verdict"]["state"] == "conditions-differ" and "checks/expected.json" in pp["conditions"]["oracle"][
        "differing"], pp["verdict"]


@needs_sandbox
def test_f5_a_regression_hidden_by_editing_a_helper_of_the_existing_tests_is_found(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "tests/__init__.py": "", "tests/helpers.py": "CLAMPED = 3\n",
        "tests/test_calc.py": "from calc import clamp\nfrom tests.helpers import CLAMPED\n\n\n"
                              "def test_clamp():\n    assert clamp(5, 0, 3) == CLAMPED\n",
        "acceptance/test_accept.py": "from calc import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n"})
    (root / "calc" / "__init__.py").write_text(GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"))
    (root / "tests" / "helpers.py").write_text("CLAMPED = 0\n")
    code, pp = _pin_run(root, "acceptance/test_accept.py")
    assert code == 1 and pp["verdict"]["state"] == "regressions-detected", pp["verdict"]
    assert any(r["path"] == "tests/test_calc.py" for r in pp["edited_tests"]["files"])


@needs_sandbox
def test_f6_a_file_that_stands_in_for_the_test_runner_stops_the_experiment(tmp_path: Path):
    root = _pytest_repo(tmp_path, {"tests/test_accept.py": "from calc import mean\n\n\ndef test_empty():\n"
                                                           "    assert mean([]) == 0\n"})
    (root / "pytest.py").write_text("# a fake pytest\n")
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert code == 1 and pp["verdict"]["state"] == "conditions-differ" and "pytest.py" in json.dumps(pp["verdict"])


def test_f9_pinned_targets_are_checked_at_the_candidate_whatever_the_base_showed():
    base = [obs({"<file>": "fail"}, {"<file>": "SyntaxError: x"})]
    c = experiment.judge_candidate([obs({"a > b": "pass"})], base, ["<file>"], ["a > typo"])
    assert c["state"] == "incomplete" and "typo" in c["why"]


def test_f14_an_outside_file_pinned_from_an_agent_shell_is_not_independent():
    scen = {"provenance": {"kind": "file"}, "in_base_tree": "absent", "in_candidate_tree": "absent"}
    assert contract.independent_of_change(scen, pinned_from_agent=False)
    assert not contract.independent_of_change({**scen, "in_candidate_tree": "identical"}, pinned_from_agent=False)
    assert not contract.independent_of_change(scen, pinned_from_agent=True)


def test_f13_a_missing_module_attribute_at_the_base_is_a_load_failure():
    runs = [obs({"t.a": "fail"}, {"t.a": "AttributeError: module 'calc' has no attribute 'median'"})] * 2
    assert experiment.judge_baseline(runs, [], None)["state"] == "load-failure"


def test_a_canary_has_a_fresh_name_every_time():
    assert experiment.canary_token() != experiment.canary_token()


# --------------------------------------------------------------------------
# security re-check (2026-10-24)
# --------------------------------------------------------------------------
def test_n5_more_credential_shapes_and_bidi_controls_are_removed():
    text = ("postgres://admin:hunter2@db/x Bearer abcdefghijklmnop eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "dozjgNryP4J3jVmNHl0w5N glpat-abcdefghijklmnopqrst AIzaSyA1234567890abcdefghij akiaabcdefghijklmnop "
            "‮evil")
    out = experiment.clean(text, 1000)
    for secret in ("hunter2", "abcdefghijklmnop", "dozjgNry", "glpat-", "AIzaSy", "akiaabcd", "‮"):
        assert secret not in out, (secret, out)
    home = str(Path.home())
    assert experiment.clean(home + "X/y") == home + "X/y" and experiment.clean(home + "/y") == "~/y"


def test_n6_math_and_issue_references_are_inert_in_markdown():
    body = render.prose("$\\color{green}{ok}$ fixes #123 and org/repo#5")
    assert "\\$" in body and "#123" not in body and "#5" not in body


def test_n7_a_report_is_never_written_through_a_link(tmp_path: Path):
    from repo_ai import cli
    root = tmp_path / "r"
    (root / ".repo-ai").mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (root / ".repo-ai" / "proof.md").symlink_to(victim)
    with pytest.raises(SystemExit):
        cli._write_report(root, root / ".repo-ai" / "proof.md", "report")
    (root / "linked").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SystemExit):
        cli._write_report(root, root / "linked" / "victim.txt", "report")
    assert victim.read_text() == "keep"
    cli._write_report(root, root / ".repo-ai" / "new.md", "report")
    assert (root / ".repo-ai" / "new.md").read_text() == "report"


def test_n8_a_node_scenario_without_a_package_type_gets_the_canary_its_syntax_needs():
    files = ["package.json", "test/a.test.js"]
    read = {"package.json": b"{}", "test/a.test.js": b"import test from 'node:test';\n"}.get
    assert "import {" in experiment.node_canary("test/a.test.js", files, read)
    read = {"package.json": b"{}", "test/a.test.js": b"const test = require('node:test');\n"}.get
    assert "require(" in experiment.node_canary("test/a.test.js", files, read)


def test_n4_a_huge_helper_is_compared_but_not_parsed():
    huge = b"import os\n" + b"x = 1\n" * (conditions.MAX_PARSE_BYTES // 6 + 10)
    assert conditions.imports("tests/h.py", huge, {"os.py"}, [""]) == set()


def test_n1_committed_state_in_another_case_is_refused(tmp_path: Path):
    probe = tmp_path / "CaseProbe"
    probe.write_text("")
    if not (tmp_path / "caseprobe").exists():
        pytest.skip("case-sensitive filesystem")
    root = _repo(tmp_path)
    _git(root, "config", "core.ignorecase", "true")
    f = root / ".REPO-AI" / "state" / "prove" / "claims" / "x.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    _git(root, "add", "-f", ".REPO-AI/state/prove/claims/x.json")
    assert cl.tracked_state(root, root / ".repo-ai" / "state")


@needs_sandbox
def test_f15_expected_values_in_a_constants_module_the_scenario_imports_are_oracle_inputs(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "expectations.py": "EMPTY_MEAN = 0\n",
        "tests/test_accept.py": "from calc import mean\nfrom expectations import EMPTY_MEAN\n\n\n"
                                "def test_empty():\n    try:\n        got = mean([])\n    except ZeroDivisionError:\n"
                                "        got = 'raised'\n    assert got == EMPTY_MEAN\n"})
    (root / "expectations.py").write_text("EMPTY_MEAN = 'raised'\n")  # the bug stays; the expectation moves
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert code == 1 and pp["verdict"]["state"] == "conditions-differ" and \
        "expectations.py" in pp["conditions"]["oracle"]["differing"], pp["verdict"]


@needs_sandbox
def test_f16_a_data_file_the_scenario_names_is_an_oracle_input_wherever_it_lives(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "data/golden.json": "0\n",
        "tests/test_accept.py": "import json, pathlib\nfrom calc import mean\n\n\ndef test_empty():\n"
                                "    want = json.loads((pathlib.Path(__file__).parents[1] / 'data' / 'golden.json')"
                                ".read_text())\n    try:\n        got = mean([])\n    except ZeroDivisionError:\n"
                                "        got = 'raised'\n    assert got == want\n"})
    (root / "data" / "golden.json").write_text('"raised"\n')
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert code == 1 and pp["verdict"]["state"] == "conditions-differ" and \
        "data/golden.json" in pp["conditions"]["oracle"]["differing"], pp["verdict"]


def test_a_module_of_constants_is_told_from_code_under_test():
    assert conditions.constants_only(b"A = 1\nB: int = 2\n")
    assert not conditions.constants_only(b"A = 1\ndef f():\n    return A\n")
    assert conditions.literal_names(["t.py"], {"t.py": b"open('data/golden.json'); x = 'v1.2'"}.get) >= {"golden.json"}


@needs_sandbox
def test_v2_v4_expected_values_reached_indirectly_are_named_and_changed_data_caps_the_level(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "support/__init__.py": "from .values import *\n", "support/values.py": "EMPTY = 0\n",
        "support/golden.dat": "0\n",
        "tests/test_accept.py": "from calc import mean\nfrom support import EMPTY\n\n\ndef test_empty():\n"
                                "    try:\n        got = mean([])\n    except ZeroDivisionError:\n        got = 'raised'\n"
                                "    assert got == EMPTY\n"})
    (root / "support" / "values.py").write_text("EMPTY = 'raised'\n")
    (root / "support" / "golden.dat").write_text("raised\n")
    code, pp = _pin_run(root, "tests/test_accept.py")
    # the change edits only an expected value and a data file: no code under test, so nothing can be supported
    assert code == 1 and pp["verdict"]["state"] != "supported" and pp["executed"] is False
    assert "--subject" in " ".join(pp["verdict"]["reasons"])


def test_the_fingerprint_gap_cap_is_lifted_once_the_engine_covers_d5_d9(tmp_path: Path):
    assert contract.ENGINE_COVERS_D5_D9
    root = _repo(tmp_path)
    (root / "a.txt").write_bytes(b"x\r\ny\r\n")
    from repo_ai.verify import changes as ch
    assert contract.cap_conditions(root, ch.detect(root, "HEAD"), "/usr/bin/python3", True) == []


# --------------------------------------------------------------------------
# Session A's independent assessment of #44 (2026-10-25): F1-F5 and contract 1.1
# --------------------------------------------------------------------------
def test_sa_f1_a_pin_from_an_agent_shell_is_never_independent_whatever_its_kind():
    blob = {"provenance": {"kind": "git"}, "in_base_tree": "identical"}
    assert contract.independent_of_change(blob, pinned_from_agent=False)
    assert not contract.independent_of_change(blob, pinned_from_agent=True)
    # a support file from the candidate's tree makes the scenario's conditions the candidate's
    assert not contract.independent_of_change(blob, False, [{"path": "tests/data.json", "in_base_tree": "absent"}])


@needs_sandbox
def test_sa_f1_a_committed_test_pinned_from_an_agent_shell_is_not_a_controlled_comparison(tmp_path: Path):
    root = _pytest_repo(tmp_path, {})
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_accept.py").write_text("from calc import mean\n\n\ndef test_empty():\n"
                                                   "    assert mean([]) == 0\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "the agent commits its own failing test")
    (root / "calc" / "__init__.py").write_text(GOOD)
    pin = run_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "tests/test_accept.py", "--from", "HEAD",
                  *PT, env={"CLAUDECODE": "1"})
    assert pin.returncode == 0, pin.stderr
    proc = run_cli(root, "prove", "run", "c", "--json", env={"CLAUDECODE": "1"})
    pp = json.loads(proc.stdout)
    rec = pp["evidence"][0]
    assert rec["scenario"]["pinned_from"] == "agent" and rec["scenario"]["independent_of_change"] is False
    assert rec["claim"]["level"] != "supported_by_controlled_comparison"
    assert any("agent session" in x for x in pp["limitations"])


@needs_sandbox
def test_sa_f2_a_target_the_candidate_turns_into_a_skip_never_reaches_a_level(tmp_path: Path):
    root = _pytest_repo(tmp_path, {"tests/test_accept.py": (
        "import unittest\nimport calc\n\n\nclass A(unittest.TestCase):\n"
        "    @unittest.skipIf(getattr(calc, 'HAS_NUMPY', False), 'numpy path')\n"
        "    def test_empty(self):\n        self.assertEqual(calc.mean([]), 0)\n")})
    (root / "calc" / "__init__.py").write_text(GOOD.replace(" if xs else 0", "") + "\nHAS_NUMPY = True\n")
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert code == 1 and pp["verdict"]["state"] != "supported"
    assert pp["evidence"][0]["claim"]["level"] == "not_established", pp["evidence"][0]["claim"]


@needs_sandbox
def test_sa_f3_a_scenario_that_cannot_import_at_the_base_is_not_a_controlled_comparison(tmp_path: Path):
    root = _pytest_repo(tmp_path, {})
    outside = tmp_path / "reviewer" / "test_new.py"
    outside.parent.mkdir()
    outside.write_text("from calc import safe_mean\n\n\ndef test_empty():\n    assert safe_mean([]) == 0\n")
    (root / "calc" / "__init__.py").write_text(GOOD + "\n\ndef safe_mean(xs):\n    return mean(xs)\n")
    assert _terminal_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "tests/test_new.py", "--file",
                         str(outside), *PT).returncode == 0
    proc = _terminal_cli(root, "prove", "run", "c", "--json")
    pp = json.loads(proc.stdout)
    assert pp["verdict"]["state"] == "baseline-not-reproduced"
    assert pp["evidence"][0]["claim"]["level"] != "supported_by_controlled_comparison"


@needs_sandbox
def test_sa_f4_a_fixture_in_a_declared_pytest_plugin_is_an_oracle_input(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "conftest.py": 'pytest_plugins = ["calc.testing"]\n',
        "calc/testing.py": "import pytest\n\n\n@pytest.fixture\ndef empty():\n    return []\n",
        "tests/test_accept.py": "from calc import mean\n\n\ndef test_empty(empty):\n"
                                "    assert mean(empty) == (0 if not empty else empty[0])\n"})
    (root / "calc" / "testing.py").write_text("import pytest\n\n\n@pytest.fixture\ndef empty():\n    return [0]\n")
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert code == 1 and pp["verdict"]["state"] == "conditions-differ", pp["verdict"]
    assert "calc/testing.py" in pp["conditions"]["oracle"]["differing"]


@pytest.mark.skipif(not NODE_SANDBOX, reason="the sandbox cannot start node here")
def test_sa_f5_typescript_tests_count_in_the_regression_check(tmp_path: Path):
    root = tmp_path / "n"
    _write(root, {"src/clamp.js": "exports.clamp = (x, lo, hi) => Math.max(lo, Math.min(x, hi));\n",
                  "test/clamp.test.ts": ("import test from 'node:test'; import assert from 'node:assert';\n"
                                         "import { createRequire } from 'node:module';\n"
                                         "const { clamp } = createRequire(import.meta.url)('../src/clamp.js');\n"
                                         "test('upper bound', () => assert.equal(clamp(9, 0, 3), 3));\n")})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "test" / "accept.test.js").write_text(
        "const test = require('node:test'); const assert = require('node:assert');\n"
        "const { clamp } = require('../src/clamp');\n"
        "test('NaN is clamped to lo', () => assert.equal(clamp(NaN, 0, 3), 0));\n")
    assert run_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "test/accept.test.js",
                   "--test-command", "node --test").returncode == 0
    (root / "src" / "clamp.js").write_text("exports.clamp = (x, lo, hi) => Number.isNaN(x) ? lo : Math.max(lo, x);\n")
    proc = run_cli(root, "prove", "run", "c", "--json")
    pp = json.loads(proc.stdout)
    assert proc.returncode == 1 and pp["verdict"]["state"] == "regressions-detected", pp["verdict"]


def test_sa_nothing_selected_in_the_regression_check_is_no_evidence():
    rec = {"verdict": "nothing-selected", "results": [], "selected": [], "plan": {}}
    assert experiment.judge_regressions(rec, "", True)["state"] == "incomplete"


def test_sa_contract_1_1_the_control_needs_two_conclusive_agreeing_runs():
    one = _record(["fail", "fail"], ["pass", "pass"], ["fail"])
    two = _record(["fail", "fail"], ["pass", "pass"], ["fail", "fail"])
    assert one["claim"]["level"] == "behavior_observed" and one["contract_version"] == "1.1"
    assert two["claim"]["level"] == "supported_by_controlled_comparison"
    assert two["reproduction"]["engine"].get("commit") or "installed_record_sha256" in two["reproduction"]["engine"]


def test_sa_a_module_that_failed_to_load_is_not_counted_as_a_test():
    o = contract.observation({**obs({"tests.T": "fail"}), "load_failures": ["tests.T"]})
    assert o["tests"]["ran"] == 0 and o["state"] == "skipped" and not o["conclusive"]


def _fake_gh(tmp_path: Path, visibility: str) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh.log"
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nif [ \"$1\" = repo ]; then echo {visibility}; fi\n"
                  f"if [ \"$1\" = pr ]; then cat \"$5\" > {tmp_path}/posted.md; echo ok; fi\n")
    gh.chmod(0o755)
    return {"PATH": f"{bin_dir}:{_os_path()}"}


def _os_path() -> str:
    import os
    return os.environ.get("PATH", "")


@needs_sandbox
def test_publishing_a_passport_needs_a_fresh_passport_and_a_private_repository(py_repo: Path, tmp_path: Path):
    _set(py_repo, GOOD)
    assert _prove(py_repo)[0] == 0
    env = _fake_gh(tmp_path, "PUBLIC")
    public = run_cli(py_repo, "prove", "report", "empty", "--publish-pr", "7", env=env)
    assert public.returncode != 0 and "public" in public.stderr and not (tmp_path / "posted.md").exists()
    (tmp_path / "bin" / "gh").unlink()
    (tmp_path / "bin").rmdir()
    env = _fake_gh(tmp_path, "PRIVATE")
    ok = run_cli(py_repo, "prove", "report", "empty", "--publish-pr", "7", env=env)
    assert ok.returncode == 0, ok.stderr
    assert "CLAIM SUPPORTED" in (tmp_path / "posted.md").read_text()
    (py_repo / "calc" / "__init__.py").write_text(GOOD + "# later\n")
    stale = run_cli(py_repo, "prove", "report", "empty", "--publish-pr", "7", env=env)
    assert stale.returncode != 0 and "stale" in stale.stderr


# --------------------------------------------------------------------------
# final adversarial challenge of 164c678 (X1-X14): the scenario runs on the base plus the code under test only
# --------------------------------------------------------------------------
FIXTURE_SCENARIO = "from calc import mean\n\n\ndef test_empty(empty_input):\n    assert mean(empty_input) == 0\n"


def _fixture_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    return _pytest_repo(tmp_path, {"support/__init__.py": "",
                                   "tests/test_calc.py": "from calc import clamp\n\n\ndef test_clamp():\n"
                                                         "    assert clamp(5, 0, 3) == 3\n",
                                   "support/fixtures.py": "import pytest\n\n\n@pytest.fixture\ndef empty_input():\n"
                                                          "    return []\n", **files})


def _external_pin_run(root: Path, tmp_path: Path, scenario: str, *extra: str) -> dict:
    outside = tmp_path / "reviewer" / PurePosixPath(scenario).name
    outside.parent.mkdir(exist_ok=True)
    outside.write_text(FIXTURE_SCENARIO if "accept" in scenario else outside.read_text())
    pin = _terminal_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", scenario, "--file", str(outside),
                        *PT, *extra)
    assert pin.returncode == 0, pin.stderr
    return json.loads(_terminal_cli(root, "prove", "run", "c", "--json").stdout)


@needs_sandbox
@pytest.mark.parametrize("files", [
    {"conftest.py": "from support.fixtures import *  # noqa\n"},                       # X1: a non-test module
    {"conftest.py": 'pytest_plugins = "support.extra,support.fixtures"\n', "support/extra.py": ""},     # X2
    {"pyproject.toml": "[tool.pytest.ini_options]\naddopts = '-p support.fixtures'\n"},                  # X3
    {"conftest.py": 'pytest_plugins = []\npytest_plugins += ["support.fixtures"]\n'},                    # X5
])
def test_x1_x5_a_fixture_edit_outside_the_code_under_test_never_reaches_the_scenario(tmp_path: Path, files):
    root = _fixture_repo(tmp_path, files)
    (root / "support" / "fixtures.py").write_text(  # the only change: the fixture, not the bug
        "import pytest\n\n\n@pytest.fixture\ndef empty_input():\n    return [0]\n")
    pp = _external_pin_run(root, tmp_path, "tests/test_accept.py")
    assert pp["verdict"]["state"] != "supported", pp["verdict"]
    assert (pp.get("evidence") or [{"claim": {"level": "not_established"}}])[0]["claim"]["level"] != \
        "supported_by_controlled_comparison"


@needs_sandbox
def test_x1_a_real_fix_with_its_fixture_still_works_when_the_subject_is_declared(tmp_path: Path):
    root = _fixture_repo(tmp_path, {"conftest.py": "from support.fixtures import *  # noqa\n"})
    (root / "calc" / "__init__.py").write_text(GOOD)
    pp = _external_pin_run(root, tmp_path, "tests/test_accept.py", "--subject", "calc/__init__.py")
    assert pp["verdict"]["state"] == "supported", pp["verdict"]
    assert pp["evidence"][0]["claim"]["level"] == "supported_by_controlled_comparison"
    assert pp["subject"]["declared"] and pp["subject"]["files"] == ["calc/__init__.py"]


@needs_sandbox
def test_x7_a_repository_with_submodules_is_refused_before_anything_runs(tmp_path: Path):
    root = _pytest_repo(tmp_path, {"tests/test_accept.py": "def test_x():\n    assert 1\n"})
    (root / ".gitmodules").write_text('[submodule "vendor"]\n\tpath = vendor\n\turl = ../vendor\n')
    _git(root, "add", ".gitmodules")
    _git(root, "commit", "-qm", "a submodule")
    (root / "calc" / "__init__.py").write_text(GOOD)
    code, pp = _pin_run(root, "tests/test_accept.py")
    assert code == 1 and pp["executed"] is False and "submodule" in json.dumps(pp["verdict"]["reasons"])


@needs_sandbox
@pytest.mark.parametrize("hide", ["added-conftest", "testsupport", "pinned-support"])
def test_x8_x10_a_regression_hidden_through_test_support_is_found(tmp_path: Path, hide: str):
    files = {"tests/__init__.py": "", "tests/unit/__init__.py": "",
             "tests/unit/test_clamp.py": "from calc import clamp\n\n\ndef test_clamp(want):\n"
                                         "    assert clamp(5, 0, 3) == want\n",
             "tests/unit/conftest.py": "import pytest\n\n\n@pytest.fixture\ndef want():\n    return 3\n"}
    if hide == "testsupport":
        files.update({"testsupport/__init__.py": "", "testsupport/values.py": "CLAMPED = 3\n",
                      "tests/unit/conftest.py": "import pytest\nfrom testsupport.values import CLAMPED\n\n\n"
                                                "@pytest.fixture\ndef want():\n    return CLAMPED\n"})
    if hide == "pinned-support":
        files.update({"tests/expected.py": "CLAMPED = 3\n",
                      "tests/unit/conftest.py": "import pytest\nfrom tests.expected import CLAMPED\n\n\n"
                                                "@pytest.fixture\ndef want():\n    return CLAMPED\n"})
    if hide == "added-conftest":
        files.pop("tests/unit/conftest.py")
        files["tests/conftest.py"] = "import pytest\n\n\n@pytest.fixture\ndef want():\n    return 3\n"
    root = _pytest_repo(tmp_path, files)
    (root / "calc" / "__init__.py").write_text(GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"))
    if hide == "added-conftest":
        (root / "tests" / "unit" / "conftest.py").write_text("import pytest\n\n\n@pytest.fixture\ndef want():\n"
                                                             "    return 0\n")
    elif hide == "testsupport":
        (root / "testsupport" / "values.py").write_text("CLAMPED = 0\n")
    else:
        (root / "tests" / "expected.py").write_text("CLAMPED = 0\n")
    extra = ["--support", "tests/expected.py"] if hide == "pinned-support" else []
    outside = tmp_path / "reviewer" / "test_accept.py"
    outside.parent.mkdir()
    outside.write_text("from calc import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n")
    assert _terminal_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "acceptance/test_accept.py",
                         "--file", str(outside), "--subject", "calc/__init__.py", *PT, *extra).returncode == 0
    pp = json.loads(_terminal_cli(root, "prove", "run", "c", "--json").stdout)
    assert pp["verdict"]["state"] == "regressions-detected", (hide, pp["verdict"])


def test_x11_an_outside_file_that_the_candidate_also_holds_is_not_independent():
    scen = {"provenance": {"kind": "file"}, "in_base_tree": "absent", "in_candidate_tree": "identical"}
    assert not contract.independent_of_change(scen, pinned_from_agent=False)


def test_x14_a_base_that_disagrees_between_repeats_is_not_established():
    rec = _record(["fail", "pass"], ["pass", "pass"], ["fail", "fail"])
    assert rec["claim"]["level"] == "not_established" and "flaky" in " ".join(rec["claim"]["not_established"])


# --------------------------------------------------------------------------
# second round of the final challenge (7fa342d): A2-A9
# --------------------------------------------------------------------------
@needs_sandbox
@pytest.mark.parametrize("wiring", ["conftest-import", "entry-point"])
def test_a2_a3_a_declared_subject_glob_never_pulls_in_pytest_machinery(tmp_path: Path, wiring: str):
    plugin = "calc/fixtures.py" if wiring == "conftest-import" else "calc/pytest_plugin.py"
    files = {plugin: "import pytest\n\n\n@pytest.fixture\ndef empty_input():\n    return []\n"}
    if wiring == "conftest-import":
        files["conftest.py"] = "from calc.fixtures import *  # noqa\n"
    else:
        files["pyproject.toml"] = "[project]\nname='calc'\n\n[project.entry-points.pytest11]\ncalc = 'calc.pytest_plugin'\n" \
                                  "\n[tool.pytest.ini_options]\naddopts = '-p calc.pytest_plugin'\n"
    root = _pytest_repo(tmp_path, {**files, "tests/test_calc.py": "from calc import clamp\n\n\ndef test_clamp():\n"
                                                                  "    assert clamp(5, 0, 3) == 3\n"})
    (root / plugin).write_text("import pytest\n\n\n@pytest.fixture\ndef empty_input():\n    return [0]\n")
    pp = _external_pin_run(root, tmp_path, "tests/test_accept.py", "--subject", "calc/*")
    assert pp["verdict"]["state"] != "supported", pp["verdict"]
    assert plugin not in (pp.get("subject") or {}).get("files", [])


def test_a2_subject_globs_are_path_aware():
    assert experiment._glob("calc/core.py", "calc/*") and not experiment._glob("calc/sub/core.py", "calc/*")
    assert experiment._glob("calc/sub/core.py", "calc/**") and experiment._glob("calc/sub/core.py", "calc")


@needs_sandbox
def test_a6_a_regression_hidden_through_a_plugin_loaded_with_p_is_found(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "support/__init__.py": "",
        "support/fixtures.py": "import pytest\n\n\n@pytest.fixture\ndef clamp_expected():\n    return 3\n",
        "pyproject.toml": "[tool.pytest.ini_options]\naddopts = '-p support.fixtures'\n",
        "tests/test_calc.py": "from calc import clamp\n\n\ndef test_clamp(clamp_expected):\n"
                              "    assert clamp(5, 0, 3) == clamp_expected\n"})
    (root / "calc" / "__init__.py").write_text(GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"))
    (root / "support" / "fixtures.py").write_text("import pytest\n\n\n@pytest.fixture\ndef clamp_expected():\n"
                                                 "    return 0\n")
    outside = tmp_path / "reviewer" / "test_accept.py"
    outside.parent.mkdir()
    outside.write_text("from calc import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n")
    assert _terminal_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "acceptance/test_accept.py",
                         "--file", str(outside), "--subject", "calc/*", *PT).returncode == 0
    pp = json.loads(_terminal_cli(root, "prove", "run", "c", "--json").stdout)
    # a plugin pytest loads for every test is also an oracle input of the scenario: refused before anything runs
    assert pp["verdict"]["state"] in {"conditions-differ", "regressions-detected"}, pp["verdict"]


@needs_sandbox
def test_a7_changed_data_outside_the_subject_that_no_test_maps_to_is_not_a_clean_regression_check(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "golden/clamp.json": "3\n",
        "tests/test_calc.py": "import json, pathlib\nfrom calc import clamp\n\n\ndef test_clamp():\n"
                              "    want = json.loads((pathlib.Path(__file__).parents[1] / 'golden' / 'clamp.json')"
                              ".read_text())\n    assert clamp(5, 0, 3) == want\n"})
    (root / "calc" / "__init__.py").write_text(GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"))
    (root / "golden" / "clamp.json").write_text("0\n")
    outside = tmp_path / "reviewer" / "test_accept.py"
    outside.parent.mkdir()
    outside.write_text("from calc import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n")
    assert _terminal_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "acceptance/test_accept.py",
                         "--file", str(outside), "--subject", "calc/*", *PT).returncode == 0
    pp = json.loads(_terminal_cli(root, "prove", "run", "c", "--json").stdout)
    assert pp["verdict"]["state"] in {"regressions-detected", "incomplete"}, pp["verdict"]


@needs_sandbox
def test_a4_a9_test_support_modules_are_never_inferred_as_the_code_under_test(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "calc/testing.py": "def clamp_expected():\n    return 3\n",
        "test-support/expect.py": "def expected_empty():\n    return 0\n",
        "tests/test_calc.py": "from calc import clamp\nfrom calc.testing import clamp_expected\n\n\n"
                              "def test_clamp():\n    assert clamp(5, 0, 3) == clamp_expected()\n"})
    (root / "calc" / "__init__.py").write_text(GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"))
    (root / "calc" / "testing.py").write_text("def clamp_expected():\n    return 0\n")
    outside = tmp_path / "reviewer" / "test_accept.py"
    outside.parent.mkdir()
    outside.write_text("from calc import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n")
    assert _terminal_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "acceptance/test_accept.py",
                         "--file", str(outside), *PT).returncode == 0
    pp = json.loads(_terminal_cli(root, "prove", "run", "c", "--json").stdout)
    assert "calc/testing.py" not in pp["subject"]["files"]
    assert pp["verdict"]["state"] != "supported", pp["verdict"]


# --------------------------------------------------------------------------
# third round (f1281ec): B1-B7. The subject-only check runs the whole suite on the base plus only the code under
# test, so no edit outside it can hide a regression, however the tests reach it
# --------------------------------------------------------------------------
def _clamp_broken(root: Path) -> None:
    (root / "calc" / "__init__.py").write_text(GOOD.replace("max(lo, min(x, hi))", "min(lo, max(x, hi))"))


def _reviewer_pin_run(root: Path, tmp_path: Path, *extra: str, command: list[str] = PT) -> dict:
    outside = tmp_path / "reviewer" / "test_accept.py"
    outside.parent.mkdir(exist_ok=True)
    outside.write_text("from calc import mean\n\n\ndef test_empty():\n    assert mean([]) == 0\n")
    pin = _terminal_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "acceptance/test_accept.py",
                        "--file", str(outside), "--subject", "calc", *command, *extra)
    assert pin.returncode == 0, pin.stderr
    return json.loads(_terminal_cli(root, "prove", "run", "c", "--json").stdout)


@needs_sandbox
def test_b1_a_plugin_named_in_the_test_command_cannot_hide_a_regression(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "support/__init__.py": "",
        "support/shared.py": "import pytest\n\n\n@pytest.fixture\ndef clamp_expected():\n    return 3\n",
        "tests/test_calc.py": "from calc import clamp\n\n\ndef test_clamp(clamp_expected):\n"
                              "    assert clamp(5, 0, 3) == clamp_expected\n"})
    _clamp_broken(root)
    (root / "support" / "shared.py").write_text("import pytest\n\n\n@pytest.fixture\ndef clamp_expected():\n"
                                               "    return 0\n")
    pp = _reviewer_pin_run(root, tmp_path, command=["--test-command", "python -m pytest -q -p support.shared"])
    assert pp["verdict"]["state"] in {"regressions-detected", "conditions-differ"}, pp["verdict"]


@needs_sandbox
def test_b3_b4_a_module_that_serves_fixtures_is_machinery_whatever_its_name(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "calc/helpers.py": "import pytest\n\n\n@pytest.fixture\ndef empty_input():\n    return []\n\n\n"
                           "def clamp_expected():\n    return 3\n",
        "tests/test_calc.py": "from calc import clamp\nfrom calc.helpers import clamp_expected\n\n\n"
                              "def test_clamp():\n    assert clamp(5, 0, 3) == clamp_expected()\n"})
    _clamp_broken(root)  # and mean stays unfixed
    (root / "calc" / "helpers.py").write_text("import pytest\n\n\n@pytest.fixture\ndef empty_input():\n"
                                             "    return [0]\n\n\ndef clamp_expected():\n    return 0\n")
    outside = tmp_path / "reviewer" / "test_accept.py"
    outside.parent.mkdir()
    outside.write_text("from calc import mean\nfrom calc.helpers import empty_input  # noqa: F401\n\n\n"
                       "def test_empty(empty_input):\n    assert mean(empty_input) == 0\n")
    assert _terminal_cli(root, "prove", "pin", "c", "--claim", "x", "--scenario", "acceptance/test_accept.py",
                         "--file", str(outside), "--subject", "calc", *PT).returncode == 0
    pp = json.loads(_terminal_cli(root, "prove", "run", "c", "--json").stdout)
    assert pp["verdict"]["state"] != "supported", pp["verdict"]
    assert "calc/helpers.py" not in pp["subject"]["files"]


@needs_sandbox
@pytest.mark.parametrize("hide", ["markdown-snapshot", "dynamic-import"])
def test_b6_b7_a_regression_hidden_where_no_rule_maps_is_found_by_the_subject_only_check(tmp_path: Path, hide):
    if hide == "markdown-snapshot":
        files = {"snapshots/clamp.md": "3\n",
                 "tests/test_calc.py": "import pathlib\nfrom calc import clamp\n\n\ndef test_clamp():\n"
                                       "    name = 'cl' + 'amp' + '.m' + 'd'\n"
                                       "    want = int((pathlib.Path(__file__).parents[1] / 'snapshots' / name)"
                                       ".read_text())\n    assert clamp(5, 0, 3) == want\n"}
    else:
        files = {"support/__init__.py": "", "support/values.py": "CLAMP = 3\n",
                 "tests/test_calc.py": "import importlib\nfrom calc import clamp\n\n\ndef test_clamp():\n"
                                       "    want = importlib.import_module('support.' + 'values').CLAMP\n"
                                       "    assert clamp(5, 0, 3) == want\n"}
    root = _pytest_repo(tmp_path, files)
    _clamp_broken(root)
    (root / "calc" / "__init__.py").write_text((root / "calc" / "__init__.py").read_text())  # mean is fixed
    if hide == "markdown-snapshot":
        (root / "snapshots" / "clamp.md").write_text("0\n")
    else:
        (root / "support" / "values.py").write_text("CLAMP = 0\n")
    pp = _reviewer_pin_run(root, tmp_path)
    assert pp["verdict"]["state"] == "regressions-detected", (hide, pp["verdict"])
    assert any("test_clamp" in t for r in pp["edited_tests"]["files"] for t in r["new_failures"])


# --------------------------------------------------------------------------
# fourth round (b4ebb93): C1, C3; C2 documented
# --------------------------------------------------------------------------
def test_c1_a_test_that_ran_at_the_base_and_is_skipped_now_is_a_regression():
    base = {"trusted": True, "outcomes": {"t.py :: test_clamp": "pass"}, "failures": {}}
    now = {"trusted": True, "outcomes": {"t.py :: test_clamp": "skip"}, "failures": {}}
    assert experiment.judge_suite(base, now, [])["state"] == "detected"


@needs_sandbox
def test_c3_code_the_scenario_does_not_reach_still_runs_against_the_bases_tests(tmp_path: Path):
    root = _pytest_repo(tmp_path, {
        "calc/other.py": "def clamp2(x, lo, hi):\n    return max(lo, min(x, hi))\n",
        "testsupport/__init__.py": "", "testsupport/values.py": "CLAMP = 3\n",
        "tests/test_other.py": "from calc.other import clamp2\nfrom testsupport.values import CLAMP\n\n\n"
                               "def test_clamp2():\n    assert clamp2(5, 0, 3) == CLAMP\n"})
    (root / "calc" / "__init__.py").write_text(GOOD)  # the fix the scenario reaches
    (root / "calc" / "other.py").write_text("def clamp2(x, lo, hi):\n    return min(lo, max(x, hi))\n")  # broken
    (root / "testsupport" / "values.py").write_text("CLAMP = 0\n")  # and its expectation moved to match
    (root / "tests" / "test_accept.py").write_text("from calc import mean\n\n\ndef test_empty():\n"
                                                   "    assert mean([]) == 0\n")
    code, pp = _pin_run(root, "tests/test_accept.py")
    # calc/other.py is code the scenario does not reach: never a clean regression check without declaring it
    assert code == 1 and pp["verdict"]["state"] in {"incomplete", "regressions-detected"}, pp["verdict"]
    assert "calc/other.py" in json.dumps(pp["verdict"]["reasons"]) or pp["verdict"]["state"] == "regressions-detected"


def test_c2_a_declared_subject_says_the_declaration_is_trusted():
    pp = _passport()
    pp["subject"] = {"declared": True, "files": ["calc/__init__.py"], "left_out": []}
    lim, _ = passport.limitations(pp, 2)
    assert any("declared (--subject)" in x for x in lim)
