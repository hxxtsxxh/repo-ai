"""benchmarks/skill-vet-fresh-v2/validate_corpus.py on synthetic deliveries with neutral placeholder text only: the
strata are labels the validator checks, and no case here describes or performs anything harmful."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "skill-vet-fresh-v2"
SPEC = importlib.util.spec_from_file_location("validate_corpus", HERE / "validate_corpus.py")
vc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vc)
COUNTS = {"H-text": 1, "H-code": 1, "B-skill": 1, "H-plugin": 1, "B-plugin": 1}
PLACEHOLDER = "a placeholder sentence for a format test"


def skill(body: str = "Placeholder prose for a format test.\n", extra: dict[str, str] | None = None) -> dict[str, str]:
    return {"SKILL.md": f"---\nname: placeholder\ndescription: \"Placeholder.\"\n---\n{body}", **(extra or {})}


PLUGIN = {".claude-plugin/plugin.json": '{"name": "placeholder"}', "commands/p.md": "Placeholder command.\n"}
CASES = {"case-004": ("H-text", skill()),
         "case-001": ("H-code", skill("See the script.\n", {"scripts/p.sh": "#!/bin/sh\necho placeholder\n"})),
         "case-005": ("B-skill", skill("Docs: https://docs.python.org/3/ and https://github.com/x/y\n")),
         "case-002": ("H-plugin", PLUGIN), "case-003": ("B-plugin", PLUGIN)}


def freeze(root: Path) -> None:
    files = sorted([*(p for p in (root / "corpus").rglob("*") if p.is_file()), root / "labels.json", root / "AUTHOR.md"])
    (root / "MANIFEST.sha256").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}\n" for p in files))


def delivery(root: Path, cases: dict = CASES, *, do_freeze: bool = True) -> Path:
    labels = []
    for cid, (stratum, files) in cases.items():
        for rel, text in files.items():
            (root / "corpus" / cid / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / "corpus" / cid / rel).write_text(text, encoding="utf-8")
        harm = "none" if stratum.startswith("B-") else PLACEHOLDER
        labels.append({"id": cid, "stratum": stratum, "intended_harm": harm, "observable_harm": harm})
    (root / "labels.json").write_text(json.dumps({"cases": labels}))
    (root / "AUTHOR.md").write_text("Written by a test, 2026-11-02, without an AI model.\n")
    if do_freeze:
        freeze(root)
    return root


def problems(root: Path) -> list[str]:
    return vc.validate(root, COUNTS)["problems"]


def test_a_valid_delivery_loads_the_way_the_harness_loads_it(tmp_path):
    root = delivery(tmp_path)
    assert problems(root) == []
    # run.py: labels = {c["id"]: c for c in json.loads(labels.json)["cases"]}; case = corpus / case_id
    labels = {c["id"]: c for c in json.loads((root / "labels.json").read_text())["cases"]}
    assert all((root / "corpus" / cid).is_dir() and labels[cid]["stratum"] for cid in labels)


def test_the_default_counts_are_the_preregistered_eighty():
    assert sum(vc.COUNTS.values()) == 80 and vc.COUNTS == {"H-text": 20, "H-code": 10, "B-skill": 30,
                                                           "H-plugin": 10, "B-plugin": 10}


@pytest.mark.skipif(not shutil.which("shasum") or sys.platform == "win32", reason="the brief's command needs a POSIX shell and shasum")
def test_the_briefs_manifest_command_validates(tmp_path):
    root = delivery(tmp_path, do_freeze=False)
    brief = "find corpus labels.json AUTHOR.md -type f -print0 | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256"
    subprocess.run(brief, shell=True, cwd=root, check=True)  # noqa: S602 - the brief's literal command
    assert problems(root) == []


@pytest.mark.parametrize("mutate,problem", [
    (lambda r: (r / "corpus" / "case-004" / "SKILL.md").write_text("changed\n"), "changed since the manifest"),
    (lambda r: (r / "AUTHOR.md").write_text("someone else\n"), "changed since the manifest was frozen: AUTHOR.md"),
    (lambda r: (r / "labels.json").write_text("[]"), "labels.json must be"),
    (lambda r: (r / "corpus" / "stray.txt").write_text("x"), "only case directories"),
    (lambda r: (r / "corpus" / "case-009").symlink_to(r / "corpus" / "case-004"), "symlink not allowed"),
])
def test_tampering_and_stray_files_are_refused(tmp_path, mutate, problem):
    root = delivery(tmp_path)
    mutate(root)
    assert any(problem in p for p in problems(root)), problems(root)


@pytest.mark.parametrize("label_change,problem", [
    ({"stratum": ["H-text"]}, "missing or empty stratum"),
    ({"stratum": "X-text"}, "unknown stratum"),
    ({"observable_harm": "none"}, "observable_harm must be 'none' for a benign case"),
])
def test_label_rules(tmp_path, label_change, problem):
    root = delivery(tmp_path)
    data = json.loads((root / "labels.json").read_text())
    data["cases"][0].update(label_change)  # case-004, H-text
    (root / "labels.json").write_text(json.dumps(data))
    freeze(root)
    assert any(problem in p for p in problems(root)), problems(root)


@pytest.mark.parametrize("body,why", [
    ("Placeholder.\n\n```\nplaceholder\n```\n", "fenced"),
    ("Placeholder.\n\n    placeholder line\n", "indented"),
    ("> ```\n> placeholder\n", "fenced"),
    ("Placeholder <pre>x</pre>\n", "<pre>"),
])
def test_h_text_is_prose_only(tmp_path, body, why):
    root = delivery(tmp_path, {**CASES, "case-004": ("H-text", skill(body))})
    assert any("prose only" in p and why in p for p in problems(root)), problems(root)


def test_list_items_are_prose(tmp_path):
    root = delivery(tmp_path, {**CASES, "case-004": ("H-text", skill("Steps:\n\n    - first\n    - second\n"))})
    assert problems(root) == []


def test_a_plugin_needs_its_manifest(tmp_path):
    root = delivery(tmp_path, {**CASES, "case-002": ("H-plugin", {"commands/p.md": "Placeholder.\n"})})
    assert any("plugin.json" in p for p in problems(root))


def test_hosts_are_checked_in_harmful_cases_only(tmp_path):
    body = "Placeholder: https://api.github.com/x and https://docs.example.com/y.\n"
    root = delivery(tmp_path, {**CASES, "case-004": ("H-text", skill(body)), "case-005": ("B-skill", skill(body))})
    found = problems(root)
    assert any("case-004" in p and "'api.github.com'" in p for p in found)
    assert not any("case-005" in p for p in found) and not any("docs.example.com" in p for p in found)


@pytest.mark.parametrize("text,host", [
    ("https://github.com?@example.com/", "github.com"),
    ("https://github.com#@example.com/", "github.com"),
    ("docs.github.com/en/x", "docs.github.com"),
    ("mail ops@corp.example.net", "corp.example.net"),
    ("git@github.com:org/repo.git", "github.com"),
    ("10.0.0.5:8080", "10.0.0.5"),
    ("http://2130706433/", "2130706433"),
    ("http://intranet/", "intranet"),
    ("http://[fe80::1%25en0]/", "[fe80::1%25en0]"),
    ("https://github%2ecom/", "github%2ecom"),
    ("https://github。com/", "github.com"),
])
def test_undefanged_hosts_are_found(text, host):
    found = vc.hosts(text)
    assert host in found and vc.unsafe_host(host), found


@pytest.mark.parametrize("text", [
    "see `https://x.example.com`, then https://a.invalid; and https://b.example.com!",
    "https://{region}.example.com/ and https://$HOST/x and https://<host>/y",
    "https://my_host.invalid/ and edit src/app.py:12 or config.json:3",
])
def test_defanged_text_is_clean(text):
    assert [h for h in vc.hosts(text) if vc.unsafe_host(h)] == []


def test_the_command_line_refuses_without_the_fixture_flag(tmp_path):
    proc = subprocess.run([sys.executable, str(HERE / "validate_corpus.py"), str(tmp_path)], capture_output=True,
                          text=True, env={k: v for k, v in os.environ.items() if k != "REPO_AI_SECURITY_FIXTURES"})
    assert proc.returncode == 2 and "REPO_AI_SECURITY_FIXTURES=1" in proc.stderr


@pytest.mark.parametrize("body,flagged", [
    ("Steps:\n\n1. First step.\n\n    A continuation paragraph of the first step.\n", None),
    ("- ```\nplaceholder\n", "fenced"),
    ("Placeholder <script>x</script>\n", "<script>"),
])
def test_prose_rules_for_lists_and_markup(tmp_path, body, flagged):
    root = delivery(tmp_path, {**CASES, "case-004": ("H-text", skill(body))})
    found = [p for p in problems(root) if "prose only" in p]
    assert (found == []) if flagged is None else any(flagged in p for p in found), found


@pytest.mark.parametrize("mutate,problem", [
    (lambda r: (r / "labels.json").unlink() or (r / "labels.json").mkdir(), "labels.json must be a file"),
    (lambda r: (r / "AUTHOR.md").unlink() or (r / "AUTHOR.md").mkdir(), "AUTHOR.md must be a file"),
])
def test_wrong_kinds_are_reported_not_a_crash(tmp_path, mutate, problem):
    root = delivery(tmp_path)
    mutate(root)
    assert any(problem in p for p in problems(root)), problems(root)


def test_manifest_formats_duplicates_and_size(tmp_path):
    root = delivery(tmp_path)
    lines = (root / "MANIFEST.sha256").read_text().splitlines()
    (root / "MANIFEST.sha256").write_text("\n".join(ln.split("  ", 1)[0].upper() + " *" + ln.split("  ", 1)[1]
                                                     for ln in lines) + "\n")
    assert problems(root) == []  # shasum -b's '*' separator and uppercase hex are accepted
    data = json.loads((root / "labels.json").read_text())
    data["cases"].append(dict(data["cases"][0]))
    (root / "labels.json").write_text(json.dumps(data))
    freeze(root)
    assert any("labelled twice" in p for p in problems(root))


def test_a_bom_before_front_matter_is_accepted(tmp_path):
    root = delivery(tmp_path, {**CASES, "case-005": ("B-skill", {"SKILL.md": "\ufeff" + skill()["SKILL.md"]})})
    assert problems(root) == []


def test_sut_freezes_the_package_and_refuses_anything_but_a_delivery():
    spec = importlib.util.spec_from_file_location("sut", HERE / "sut.py")
    sut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sut)
    assert "src/repo_ai" in sut.FROZEN and "pyproject.toml" in sut.FROZEN
    assert sut.DELIVERY_DIR.startswith("benchmarks/skill-vet-fresh-v2/")


def test_sut_check_in_a_real_repository(tmp_path):
    root = tmp_path / "r"
    bench = root / "benchmarks" / "skill-vet-fresh-v2"
    bench.mkdir(parents=True)
    (root / "src" / "repo_ai").mkdir(parents=True)
    (root / "src" / "repo_ai" / "m.py").write_text("x = 1\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    for name in ("run.py", "validate_corpus.py", "constraints.txt"):
        (bench / name).write_text("# placeholder\n")
    shutil.copy(HERE / "sut.py", bench / "sut.py")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.hooksPath=/dev/null"]

    def commit(msg):
        subprocess.run([*git, "add", "-A"], cwd=root, check=True)
        subprocess.run([*git, "commit", "-qm", msg], cwd=root, check=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()

    def check(rev):
        return subprocess.run([sys.executable, str(bench / "sut.py"), "--check", rev], capture_output=True,
                              text=True).returncode

    subprocess.run([*git, "init", "-q"], cwd=root, check=True)
    before = commit("base")
    subprocess.run([sys.executable, str(bench / "sut.py"), "--record"], check=True)
    freeze = commit("freeze")
    (bench / "corpus" / "case-001").mkdir(parents=True)
    (bench / "corpus" / "case-001" / "SKILL.md").write_text("placeholder\n")
    (bench / "labels.json").write_text("{}")
    commit("delivery")
    assert check(freeze) == 0
    assert check(before) == 1  # not the commit that added SUT.json
    (bench / "labels.json.bak").write_text("{}")
    commit("not a delivery path")
    assert check(freeze) == 1
    (bench / "labels.json.bak").unlink()
    (root / "src" / "repo_ai" / "m.py").write_text("x = 2\n")
    commit("vetter changed")
    assert check(freeze) == 1


@pytest.mark.parametrize("text", ["Run setup.sh first", "see `deploy.sh`", "MANIFEST.in and Makefile.in",
                                  "helper.pl", "Calculator.app", "[1]: https://docs.example.com/x", "[ab]/x"])
def test_file_names_and_link_references_are_not_hosts(text):
    assert [h for h in vc.hosts(text) if vc.unsafe_host(h)] == []


def test_code_nested_in_a_list_item_is_not_prose(tmp_path):
    root = delivery(tmp_path, {**CASES, "case-004": ("H-text", skill("1. Run:\n\n        placeholder command\n"))})
    assert any("indented code block" in p for p in problems(root)), problems(root)
