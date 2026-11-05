"""The Stop-hook completion gate: its per-session bound, and coexistence with
other Stop hooks (a formatter that rewrites files after verification).

Contract tests proposed in docs/research/VERIFY-INTERFACE-PROPOSALS-2026-10.md
(P1, P2). Evidence records are written directly, so nothing runs here except
one sandboxed end-to-end check that real runs store what the gate reads.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import evidence_environment, run_cli

from repo_ai.verify import changes, evidence

PASSED = "selected-passed (full suite not run)"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "g"
    for rel, text in {"calc/core.py": "def add(a, b):\n    return a + b\n",
                      "lib/fmt.js": "function greet(name) {\n  return 'hi ' + name;\n}\nmodule.exports = { greet };\n",
                      }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _layout(root: Path):
    from repo_ai.config import load_config
    from repo_ai.paths import detect_kind, resolve_layout
    return resolve_layout(root, load_config(root), prefer=detect_kind(root) or "standard")


def _decide(root: Path, data: dict | None = None, **kw) -> dict | None:
    from repo_ai.verify.gate import decision
    out = decision(root, _layout(root), data if data is not None else {"session_id": "s1"}, **kw)
    return json.loads(out) if out else None


def _verified(root: Path, verdict: str = PASSED) -> None:
    """What a clean `verify --run` of the current tree leaves behind."""
    evidence.save(_layout(root).state_dir, {
        **evidence_environment(root),
        "schema": evidence.SCHEMA, "fingerprint": changes.fingerprint(root),
        "semantic_fingerprint": changes.semantic_fingerprint(root), "verdict": verdict})


# -- P1: a hard bound per session --------------------------------------------
def test_gate_never_blocks_more_than_n_times_per_session(repo: Path):
    core = repo / "calc" / "core.py"
    blocks = 0
    for i in range(6):  # six different unverified changes: fingerprint churn
        core.write_text(f"def add(a, b):\n    return a + b + {i + 1}\n")
        out = _decide(repo, max_blocks=3)
        blocks += bool(out and out.get("decision") == "block")
    assert blocks == 3
    core.write_text("def add(a, b):\n    return a * b\n")
    assert _decide(repo, max_blocks=0) is None  # 0: never blocks


def test_gate_counter_is_per_session_not_global(repo: Path):
    core = repo / "calc" / "core.py"
    for i in range(2):
        core.write_text(f"def add(a, b):\n    return a + b + {i + 1}\n")
        assert _decide(repo, {"session_id": "s1"}, max_blocks=2)["decision"] == "block"
    core.write_text("def add(a, b):\n    return a - b\n")
    assert _decide(repo, {"session_id": "s1"}, max_blocks=2) is None    # s1 has used its two
    assert _decide(repo, {"session_id": "s2"}, max_blocks=2)["decision"] == "block"  # a new session has not


def test_the_report_mode_is_not_bounded_by_the_block_cap(repo: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return a - b\n")
    assert "systemMessage" in _decide(repo, mode="report", max_blocks=0)


def test_a_gate_state_file_from_before_the_cap_is_still_read(repo: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return a - b\n")
    state = _layout(repo).state_dir / "gate.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps([changes.fingerprint(repo)]))  # the list-only form: this change was shown
    assert _decide(repo) is None


def test_gate_is_silent_when_another_stop_hook_continues_the_agent(repo: Path):
    (repo / "calc" / "core.py").write_text("def add(a, b):\n    return a - b\n")
    assert _decide(repo, {"session_id": "s1", "stop_hook_active": True}) is None
    assert _decide(repo)["decision"] == "block"  # the same change, outside a stop-hook continuation


# -- P2: a formatter after verification ---------------------------------------
def test_formatting_only_rewrite_after_verification_does_not_reblock_python(repo: Path):
    core = repo / "calc" / "core.py"
    core.write_text("def add(a, b):\n    return a+b if a else b\n")
    _verified(repo)
    assert _decide(repo) is None
    core.write_text("def add(a, b):\n    # formatted\n    return (\n        a + b if a else b\n    )\n")  # black-style
    assert changes.fingerprint(repo) != json.loads(
        (_layout(repo).state_dir / "evidence" / "latest.json").read_text())["fingerprint"]
    assert _decide(repo) is None
    core.write_text("def add(a, b):\n    return (\n        a - b if a else b\n    )\n")  # behaviour changed
    assert _decide(repo)["decision"] == "block"


def test_formatting_only_rewrite_after_verification_does_not_reblock_javascript(repo: Path):
    js = repo / "lib" / "fmt.js"
    js.write_text("function greet(name) {\n  return 'hello ' + name;\n}\nmodule.exports = { greet };\n")
    _verified(repo)
    js.write_text('function greet( name ){\n    return "hello "+name;  // prettier, quotes\n}\n'
                  'module.exports = {greet};\n')
    assert _decide(repo) is None
    js.write_text('function greet( name ){\n    return "hello  "+name;\n}\nmodule.exports = {greet};\n')
    assert _decide(repo)["decision"] == "block"  # a string's content is behaviour


def test_failing_evidence_still_blocks_after_a_formatting_rewrite(repo: Path):
    core = repo / "calc" / "core.py"
    core.write_text("def add(a, b):\n    return a-b\n")
    _verified(repo, verdict="regression")
    core.write_text("def add(a, b):\n    return a - b\n")
    out = _decide(repo)
    assert out["decision"] == "block" and " fails." in out["reason"]


@pytest.mark.parametrize(("a", "b"), [
    ("return\nx", "return x"),                                # automatic semicolon insertion
    ("a + +b", "a ++b"),                                      # different operators
    ("a - -b", "a --b"),
    ("let ab = 1", "let a b = 1"),
    ("x = 'a'", "x = 'b'"),
    ("1 .toString()", "1.toString()"),
    ("x = y\n(z)", "x = y(z)"),
])
def test_js_tokens_keep_every_difference_that_can_change_behaviour(a: str, b: str):
    ta, tb = changes._js_tokens(a), changes._js_tokens(b)
    assert ta is None or tb is None or ta != tb


@pytest.mark.parametrize("text", [
    "x = `a ${b}`",                       # template literals
    "if (x) /a b/.test(y)",               # a regular expression after `)`
    "f(/a b/)",                            # ... and after `(`
    "x = a / /b c/.source",                # ... and after a division
    "x = 'it\\'s'",                        # escapes
    "return <p>a  b</p>",                  # JSX text
    "x = 'unterminated\ny'",
    "/* open",
])
def test_js_tokens_give_up_on_what_they_cannot_tokenise_exactly(text: str):
    assert changes._js_tokens(text) is None


def test_semantic_fingerprint_keeps_docstrings_and_unparsable_files_exact(repo: Path):
    core = repo / "calc" / "core.py"
    core.write_text('def add(a, b):\n    "Add."\n    return a + b\n')
    one = changes.semantic_fingerprint(repo)
    core.write_text('def add(a, b):\n    "Add!"\n    return a + b\n')  # a docstring is a value at runtime
    assert changes.semantic_fingerprint(repo) != one
    core.write_text("def add(a, b:\n")
    two = changes.semantic_fingerprint(repo)
    core.write_text("def add(a,  b:\n")  # unparsable: bytes count
    assert changes.semantic_fingerprint(repo) != two


def test_a_real_run_records_the_semantic_fingerprint(tmp_path: Path):
    from test_verify_adaptive import CMD, _sandbox
    if not _sandbox():
        pytest.skip("no sandbox backend to run tests in")
    root = tmp_path / "p"
    for rel, text in {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n",
                      "tests/__init__.py": "",
                      "tests/test_a.py": ("import unittest\nfrom calc.core import add\n\n\n"
                                          "class T(unittest.TestCase):\n    def test_a(self):\n"
                                          "        self.assertEqual(add(1, 1), 2)\n")}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    proc = run_cli(root, "verify", "--run", "--json", "--test-command", CMD)
    ev = json.loads(proc.stdout)["evidence"]
    assert ev["semantic_fingerprint"] == changes.semantic_fingerprint(root)
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b+a  # formatted\n")
    assert run_cli(root, "verify", "--gate", stdin='{"session_id": "x"}').stdout.strip() == ""
