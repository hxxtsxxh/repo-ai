"""First-run polish: the developer-experience audit's findings, one test each.

Bare `init` names its IBM Bob default; hints name `--agent claude`; TypeScript
ESM `./x.js` imports resolve to `x.ts`; framework markers match on any line;
`impact` is not "low" at a poor import-resolution rate; the privacy audit
lists every store; `/repo-verify` asks before `--run`; `budget`, `skills
audit` and `doctor` agree on skill tokens; `doctor` reports subagents off
under `feature_set = core`; one leading BOM is not hidden text; `--help` is
clean.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import _git, make_repo, run_cli

from repo_ai import firewall, inventory
from repo_ai.analyze import resolve_imports
from repo_ai.cli import build_parser
from repo_ai.models import FileRecord, ImportEdge
from repo_ai.testing import discover_test_suites

INIT_HINT = "run `repo-ai init --agent claude` (or `--agent none` for verify only)"
BOB_NOTICE = ("no --agent given: wiring IBM Bob (the v0.4 default); "
              "for Claude Code use --agent claude")


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REPO_AI_HOME", str(tmp_path / "rh"))


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    return {"REPO_AI_HOME": str(tmp_path / "rh"), **extra}


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _git_repo(root: Path, files: dict[str, str]) -> Path:
    _write(root, files)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")
    return root


# 1. bare `init` names the Bob default; hints name `--agent claude` ---------------
def test_bare_init_says_it_wires_bob(tmp_path: Path):
    bare = make_repo(tmp_path, "pyweb", "bare")
    proc = run_cli(bare, "init", "-q", env=_env(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.count(BOB_NOTICE) == 1
    assert (bare / ".bob").is_dir()  # the v0.4 default is kept

    claude = make_repo(tmp_path, "pyweb", "claude")
    proc = run_cli(claude, "init", "--agent", "claude", "-q", env=_env(tmp_path))
    assert proc.returncode == 0 and BOB_NOTICE not in proc.stderr
    # a re-init keeps the recorded agents and wires no Bob: no notice
    proc = run_cli(claude, "init", "-q", env=_env(tmp_path))
    assert proc.returncode == 0 and BOB_NOTICE not in proc.stderr
    assert not (claude / ".bob").exists()


def test_missing_index_hints_name_claude(tmp_path: Path):
    repo = make_repo(tmp_path, "pyweb")
    status = run_cli(repo, "status", env=_env(tmp_path))
    assert status.returncode == 1 and INIT_HINT in status.stdout
    for args in (("verify",), ("search", "x"), ("architecture",)):
        proc = run_cli(repo, *args, env=_env(tmp_path))
        assert proc.returncode != 0 and INIT_HINT in proc.stderr, (args, proc.stderr)
        assert "run `repo-ai init` " not in proc.stderr
    doctor = json.loads(run_cli(repo, "doctor", "--json", env=_env(tmp_path, PATH="/usr/bin:/bin")).stdout)
    index = next(c for c in doctor if c["label"] == "index")
    assert index["fix"] == "repo-ai init --agent claude (or --agent none for verify only)"


# 2. TypeScript ESM: `./math.js` is written in `math.ts` --------------------------
def test_js_extension_import_resolves_to_typescript_source():
    paths = ["src/index.ts", "src/math.ts", "src/a.mts", "src/b.mts", "src/c.tsx", "src/d.tsx",
             "src/e.cts", "src/f.cts", "src/real.js", "src/real.ts", "src/g.ts", "src/h.tsx"]
    edges = [ImportEdge("src/index.ts", "./math.js"), ImportEdge("src/a.mts", "./b.mjs"),
             ImportEdge("src/c.tsx", "./d.jsx"), ImportEdge("src/e.cts", "./f.cjs"),
             ImportEdge("src/index.ts", "./real.js"),     # the .js file exists: it wins
             ImportEdge("src/index.ts", "./h.js"),        # .js -> .tsx as well
             ImportEdge("src/index.ts", "./gone.js")]     # nothing to resolve to
    got = {(e.src_path, e.raw_target): e.resolved_path for e in resolve_imports(edges, paths, {})}
    assert got == {("src/index.ts", "./math.js"): "src/math.ts", ("src/a.mts", "./b.mjs"): "src/b.mts",
                   ("src/c.tsx", "./d.jsx"): "src/d.tsx", ("src/e.cts", "./f.cjs"): "src/f.cts",
                   ("src/index.ts", "./real.js"): "src/real.js", ("src/index.ts", "./h.js"): "src/h.tsx",
                   ("src/index.ts", "./gone.js"): ""}


NODENEXT = {
    "package.json": '{"name": "esm", "type": "module", "scripts": {"test": "node --test test/math.test.ts"}}\n',
    "tsconfig.json": '{"compilerOptions": {"module": "NodeNext", "moduleResolution": "NodeNext"}}\n',
    "src/math.ts": "export function add(a: number, b: number): number {\n  return a + b;\n}\n",
    "src/index.ts": 'import { add } from "./math.js";\n\n'
                    "export function total(xs: number[]): number {\n  return xs.reduce(add, 0);\n}\n",
    "test/math.test.ts": 'import { test } from "node:test";\nimport assert from "node:assert";\n'
                         'import { add } from "../src/math.js";\n\n'
                         'test("add", () => {\n  assert.equal(add(1, 2), 3);\n});\n',
}


def test_nodenext_project_links_importers_and_tests(tmp_path: Path):
    repo = _git_repo(tmp_path / "esm", NODENEXT)
    assert run_cli(repo, "init", "--agent", "none", "-q", env=_env(tmp_path)).returncode == 0

    related = json.loads(run_cli(repo, "related", "src/math.ts", "--format", "json", env=_env(tmp_path)).stdout)
    assert set(related["imported_by"]) == {"src/index.ts", "test/math.test.ts"}
    assert "test/math.test.ts" in related["likely_tests"]

    impact = json.loads(run_cli(repo, "impact", "src/math.ts", "--format", "json", env=_env(tmp_path)).stdout)
    assert {i["path"] for i in impact["importers"]} == {"src/index.ts", "test/math.test.ts"}
    assert {t["path"]: t["evidence"] for t in impact["tests"]} == {"test/math.test.ts": "import"}
    assert impact["import_resolution_rate"] == 1.0

    # the read-only verify plan now selects the test that exercises the change
    (repo / "src" / "math.ts").write_text(
        "export function add(a: number, b: number): number {\n  return b + a;\n}\n", encoding="utf-8")
    plan = json.loads(run_cli(repo, "verify", "--json", env=_env(tmp_path)).stdout)
    assert [s["test"] for s in plan["selected"]] == ["test/math.test.ts"]


# 3. framework markers match on any line -------------------------------------------
def _suite(path: str, text: str) -> str:
    record = FileRecord(path=path, size=len(text), lines=text.count("\n"), language="Python",
                        sha1="0", mtime=0.0, role="test")
    suites = discover_test_suites([record], {path: text}, [], {})
    return suites[0].framework


def test_framework_import_markers_match_any_line():
    assert _suite("tests/test_a.py", '"""Tests."""\n\nimport os\nimport pytest\n\n\ndef test_a():\n    pass\n') \
        == "pytest"
    assert _suite("tests/test_b.py", '"""Tests."""\nimport os\nimport unittest\n\n\n'
                  "class T(unittest.TestCase):\n    pass\n") == "unittest"
    assert _suite("tests/test_c.py", "import os\nfrom pytest import raises\n") == "pytest"
    # `import unittest.mock` is a mocking helper, not the unittest framework
    assert _suite("tests/test_d.py", "import os\nimport unittest.mock\n\n\ndef test_d():\n    pass\n") \
        != "unittest"


# 4. a poor resolution rate is not "low" risk ---------------------------------------
LOWRES = {
    "package.json": '{"name": "lowres", "scripts": {"test": "node --test"}}\n',
    "src/util.js": "export function util(x) {\n  return x + 1;\n}\n",
    "test/util.test.js": 'import { util } from "../src/util.js";\nimport { test } from "node:test";\n'
                         'test("u", () => util(1));\n',
    "src/app.js": 'import a from "./gone1.js";\nimport b from "./gone2.js";\nimport c from "./gone3.js";\n'
                  'import d from "./gone4.js";\nexport const all = [a, b, c, d];\n',
}


def test_impact_is_medium_when_most_imports_are_unresolved(tmp_path: Path):
    repo = _git_repo(tmp_path / "lowres", LOWRES)
    assert run_cli(repo, "init", "--agent", "none", "-q", env=_env(tmp_path)).returncode == 0
    data = json.loads(run_cli(repo, "impact", "src/util.js", "--format", "json", env=_env(tmp_path)).stdout)
    assert data["import_resolution_rate"] < 0.5 and data["tests"] and len(data["importers"]) < 4
    assert data["risk"] == "medium"
    assert any("under half of the imports resolved" in u for u in data["uncertainty"])
    text = run_cli(repo, "impact", "src/util.js", env=_env(tmp_path)).stdout
    assert "risk: medium" in text and "under half of the imports resolved" in text

    # the same file with every import resolved stays low
    (repo / "src" / "app.js").unlink()
    assert run_cli(repo, "update", "-q", env=_env(tmp_path)).returncode == 0
    data = json.loads(run_cli(repo, "impact", "src/util.js", "--format", "json", env=_env(tmp_path)).stdout)
    assert data["import_resolution_rate"] == 1.0 and data["risk"] == "low"
    assert not any("under half" in u for u in data["uncertainty"])


# 5. the privacy audit lists every store and says what evidence keeps ---------------
def test_privacy_audit_lists_verify_and_capability_stores(pyweb: Path, tmp_path: Path):
    assert run_cli(pyweb, "init", "--agent", "none", "-q", env=_env(tmp_path)).returncode == 0
    proc = run_cli(pyweb, "privacy", "audit", "--json", env=_env(tmp_path))
    assert proc.returncode == 0, proc.stdout
    stores = {s["name"]: s for s in json.loads(proc.stdout)}
    for name, rel in (("verification evidence", ".repo-ai/state/evidence"),
                      ("test map", ".repo-ai/state/testmap.json"),
                      ("verify baseline", ".repo-ai/state/verify-baseline.json"),
                      ("verify timings", ".repo-ai/state/verify-timings.json"),
                      ("verify scan cache", ".repo-ai/state/verify-scan-cache.json")):
        assert stores[name]["path"] == rel, name
    assert "failing test output" in stores["verification evidence"]["contains"]
    # the release-freeze packaging review: ProofLab's store and the gate's state were not listed
    assert stores["ProofLab (experimental)"]["path"] == ".repo-ai/state/prove"
    assert "claim text" in stores["ProofLab (experimental)"]["contains"]
    assert stores["completion gate"]["path"] == ".repo-ai/state/gate.json"
    # the freeze review: unpinning keeps the pinned bytes, and the audit does not scan ProofLab's store
    assert "pinned bytes until uninstall" in stores["ProofLab (experimental)"]["retention"]
    assert "not scrubbed" in stores["ProofLab (experimental)"]["contains"]
    machine = tmp_path / "rh" / "repos"
    for name, leaf in (("capability approvals", "capabilities.json"), ("capability runs", "capability-runs")):
        assert stores[name]["committed"] == "outside repository"
        assert Path(stores[name]["path"]).name == leaf and Path(stores[name]["path"]).is_relative_to(machine)
    text = run_cli(pyweb, "privacy", "audit", env=_env(tmp_path)).stdout
    # Missions explicitly retain redacted task text: do not restore the old,
    # now-false blanket promise in order to satisfy a wording snapshot.
    mission = stores["missions (experimental)"]
    assert mission["path"] == ".repo-ai/state/missions"
    assert "task text is redacted" in mission["contains"]
    assert "candidate diffs" in mission["contains"]
    assert "no provider upload" not in mission["contains"]
    assert "network" in stores["provider transmission"]["contains"]
    assert "64 missions maximum" in mission["retention"]
    assert ("mission contracts keep redacted task text; verification evidence keeps the last lines "
            "of failing test output") in text
    assert "no store contains prompts or secret values" not in text
    assert "the audit does not scan them" in text
    assert "command output" not in text.splitlines()[1]


# 6. /repo-verify asks before running repository code -------------------------------
def test_repo_verify_skill_asks_before_run(pyweb: Path, tmp_path: Path):
    plugin = Path(__file__).resolve().parent.parent / "integrations" / "claude-plugin" / "skills" / "verify"
    assert run_cli(pyweb, "init", "--agent", "claude", "-q", env=_env(tmp_path)).returncode == 0
    for path in (pyweb / ".claude" / "skills" / "repo-verify" / "SKILL.md", plugin / "SKILL.md"):
        text = path.read_text("utf-8")
        step2 = text[text.index("\n2. "):text.index("\n3. ")]
        assert step2.startswith("\n2. With the user's go-ahead (it runs repository code, sandboxed):"), path
        assert step2.index("go-ahead") < step2.index("`repo-ai verify --run`")
        assert "with the same go-ahead, `repo-ai verify --run --full`" in text


# 7./8. budget, skills audit and doctor agree; subagents are off under core ---------
def _doctor(repo: Path, tmp_path: Path) -> dict[str, dict]:
    proc = run_cli(repo, "doctor", "--agent", "claude", "--json", env=_env(tmp_path, PATH="/usr/bin:/bin"))
    return {c["label"]: c for c in json.loads(proc.stdout)}


def test_skill_token_counts_agree_and_exclude_manual_only(pyweb: Path, tmp_path: Path):
    assert run_cli(pyweb, "init", "--agent", "claude", "-q", env=_env(tmp_path)).returncode == 0
    _write(pyweb, {".claude/skills/my-manual/SKILL.md":
                   "---\nname: my-manual\ndescription: \"" + "A long manual-only description. " * 8 + "\"\n"
                   "disable-model-invocation: true\n---\n# Steps\n\n1. Read.\n",
                   ".claude/skills/my-auto/SKILL.md":
                   "---\nname: my-auto\ndescription: \"Formats the changelog. Use when releasing.\"\n"
                   "---\n# Steps\n\n1. Read.\n"})

    budget = json.loads(run_cli(pyweb, "budget", "--json", env=_env(tmp_path)).stdout)
    skills = [i for i in budget["items"] if i["kind"] == "skill"]
    assert any(not i["always_loaded"] for i in skills if i["owner"].startswith("repo-ai"))  # manual-only ones
    budget_all = sum(i["tokens_est"] for i in skills if i["always_loaded"])
    budget_ours = sum(i["tokens_est"] for i in skills if i["always_loaded"] and i["owner"].startswith("repo-ai"))

    audit = json.loads(run_cli(pyweb, "skills", "audit", "--json", env=_env(tmp_path)).stdout)
    assert audit["description_tokens"] == budget_all
    text = run_cli(pyweb, "skills", "audit", env=_env(tmp_path)).stdout
    assert f"~{budget_all} tokens (manual-only skills excluded)" in text

    detail = _doctor(pyweb, tmp_path)["claude: skills"]["detail"]
    assert int(re.search(r"descriptions ~(\d+) tokens", detail).group(1)) == budget_ours
    assert "manual-only, not counted" in detail


def test_doctor_reports_subagents_off_under_core(tmp_path: Path):
    core = make_repo(tmp_path, "pyweb", "core")
    assert run_cli(core, "init", "--agent", "claude", "-q", env=_env(tmp_path)).returncode == 0
    check = _doctor(core, tmp_path)["claude: subagents"]
    assert (check["status"], check["detail"], check["fix"]) == ("info", "off (feature_set = core)", "")

    full = make_repo(tmp_path, "pyweb", "full")
    assert run_cli(full, "init", "--agent", "claude", "--feature-set", "full", "-q",
                   env=_env(tmp_path)).returncode == 0
    assert _doctor(full, tmp_path)["claude: subagents"]["status"] == "ok"


# 9. one leading byte-order mark is not hidden text ----------------------------------
def _hidden(tmp_path: Path, name: str, data: str) -> bool:
    skill = _write(tmp_path / name, {
        "SKILL.md": f"---\nname: {name}\ndescription: \"Edits documents. Use when asked.\"\nlicense: MIT\n"
                    "---\n# Steps\n\n1. Read the schema.\n"})
    (skill / "reference.md").write_bytes(data.encode("utf-8"))
    dest, files, prior = firewall.quarantine_local(skill, name)
    report = firewall.inspect(dest, files, {"id": f"local/{name}", "name": name, "path": name}, {}, prior)
    return any(f.rule == "hidden-unicode" for f in report.findings)


def test_leading_bom_is_not_hidden_unicode(tmp_path: Path):
    assert not _hidden(tmp_path, "bom-first", "﻿# Schema\n\nPlain text.\n")
    assert _hidden(tmp_path, "bom-inside", "# Schema\n\nPlain﻿text.\n")
    assert _hidden(tmp_path, "bom-twice", "﻿﻿# Schema\n")
    assert _hidden(tmp_path, "bom-then-zw", "﻿# Schema​\n")


# 10. the inventory hint names the flag that works ----------------------------------
def test_inventory_hint_names_all_flag(tmp_path: Path):
    repo = _write(tmp_path / "inv", {".claude/skills/notes/SKILL.md":
                                     "---\nname: notes\ndescription: \"Takes notes. Use when asked.\"\n---\n"
                                     "# Steps\n\n1. Write notes.\n"})
    text = inventory.render(inventory.build(repo, home=tmp_path / "home"))
    assert "--all lists them" in text and "--verbose" not in text
    assert build_parser().parse_args(["skills", "inventory", "--all"]).all is True


# 11. --help hygiene ------------------------------------------------------------------
def test_top_level_help_is_clean(tmp_path: Path):
    out = run_cli(None, "--help", env=_env(tmp_path)).stdout
    assert "SUPPRESS" not in out and "_extract-prompt" not in out
    usage = out.split("\n\n")[0]
    assert "{" not in usage and "<command>" in usage
    assert "repo-ai verify " in out and "repo-ai verify --run" in out
    # hidden, not removed
    assert build_parser().parse_args(["_extract-prompt"]).command == "_extract-prompt"


def test_subcommand_help_text(tmp_path: Path):
    skills = run_cli(None, "skills", "--help", env=_env(tmp_path)).stdout
    for flag in ("--workers", "--max-file-bytes", "--no-symbols", "--no-bob", "--summarize"):
        assert flag not in skills, flag
    verify = " ".join(run_cli(None, "verify", "--help", env=_env(tmp_path)).stdout.split())
    assert "--gate (experimental)" in verify
    caps = " ".join(run_cli(None, "capabilities", "--help", env=_env(tmp_path)).stdout.split())
    assert "recommend | candidates | select are experimental" in caps
    assert "select (experimental): the digest" in caps
    hook = " ".join(run_cli(None, "hook", "--help", env=_env(tmp_path)).stdout.split())
    assert "post-skill" in hook
    top = " ".join(run_cli(None, "--help", env=_env(tmp_path)).stdout.split())
    assert "recommend | candidates | select are experimental" in top


def test_quickstart_mentions_verify(pyweb: Path, tmp_path: Path):
    out = run_cli(pyweb, "quickstart", env=_env(tmp_path)).stdout
    assert re.search(r"^\s+repo-ai verify\s+#", out, re.M)
    assert re.search(r"^\s+repo-ai verify --run\s+#.*sandboxed", out, re.M)


def test_skills_without_indexing_flags_still_falls_back_to_init(pyweb: Path, tmp_path: Path):
    """`skills promote` with no index runs a full init; that path must not need
    the indexing flags `skills` no longer takes."""
    args = build_parser().parse_args(["skills", "promote", "--safe"])
    assert not hasattr(args, "no_bob") and not hasattr(args, "workers")
    proc = run_cli(pyweb, "skills", "promote", "--safe", env=_env(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert BOB_NOTICE in proc.stderr  # the fallback is a bare init (v0.4 layout)
    assert run_cli(pyweb, "status", "--json", env=_env(tmp_path)).returncode in (0, 2)


def test_plugin_inspection_ignores_one_leading_bom(tmp_path):
    import json

    from repo_ai import pluginvet

    def rules(script_text):
        root = tmp_path / str(abs(hash(script_text)))
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text("{}", "utf-8")
        (root / "hooks").mkdir()
        (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "node ${CLAUDE_PLUGIN_ROOT}/hooks/x.js"}]}]}}), "utf-8")
        (root / "hooks" / "x.js").write_text(script_text, "utf-8")
        rep = pluginvet.vet(pluginvet.LocalSource(root))
        return {f.rule for c in rep.components for f in c.findings}

    assert "hidden-unicode" not in rules("\ufeffconsole.log('ok')\n")
    assert "hidden-unicode" in rules("console.log('o\u200bk')\n")


def test_from_unittest_import_is_a_unittest_suite_but_unittest_mock_is_not():
    """journey-offline-v2: more-itertools' tests use `from unittest import TestCase`, which left the suite "unknown",
    so verify found no runner it trusted and refused."""
    assert _suite("tests/test_more.py", "from unittest import TestCase\n\nclass T(TestCase):\n    def test_a(self):\n"
                                        "        pass\n") == "unittest"
    assert _suite("tests/test_c.py", "from unittest import IsolatedAsyncioTestCase\n") == "unittest"
    # a pytest file that only takes mock (or skip) from unittest stays pytest: unittest discovery cannot collect it
    assert _suite("tests/test_b.py", "from unittest import mock\n\ndef test_b():\n    assert True\n") == "pytest"
    assert _suite("tests/test_d.py", "from unittest import skip, mock\n\ndef test_d():\n    pass\n") == "pytest"
