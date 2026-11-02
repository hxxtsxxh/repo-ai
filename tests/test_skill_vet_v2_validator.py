"""benchmarks/skill-vet-fresh-v2/validate_corpus.py on benign synthetic deliveries only (no harmful content is
written here: the strata's labels are what the validator checks, not the cases' intent)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "validate_corpus", Path(__file__).resolve().parents[1] / "benchmarks" / "skill-vet-fresh-v2" / "validate_corpus.py")
vc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vc)
COUNTS = {"B-skill": 2, "B-plugin": 1}


def _skill(text: str = "Summarise a failing test run.") -> dict[str, str]:
    return {"SKILL.md": f"---\nname: summarise\ndescription: \"{text}\"\n---\n# Steps\n\n1. Read the output.\n"}


def _delivery(root: Path, cases: dict[str, tuple[str, dict[str, str]]], *, freeze: bool = True) -> Path:
    for cid, (stratum, files) in cases.items():
        for rel, text in files.items():
            (root / "corpus" / cid / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / "corpus" / cid / rel).write_text(text)
        (root / "labels").mkdir(exist_ok=True)
        (root / "labels" / f"{cid}.json").write_text(json.dumps(
            {"case": cid, "stratum": stratum, "intended_harm": "none", "observable_harm": "none"}))
    (root / "AUTHOR.md").write_text("Written by a test, 2026-11-02.\n")
    if freeze:
        lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}"
                 for p in sorted([*(root / "corpus").rglob("*"), *(root / "labels").rglob("*")]) if p.is_file()]
        (root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    return root


PLUGIN = {".claude-plugin/plugin.json": '{"name": "fmt"}', "commands/fmt.md": "Format the changed files.\n"}


def test_a_valid_delivery(tmp_path):
    root = _delivery(tmp_path, {"case-001": ("B-skill", _skill()), "case-002": ("B-skill", _skill()),
                                "case-003": ("B-plugin", PLUGIN)})
    report = vc.validate(root, COUNTS)
    assert report["ok"], report["problems"]


@pytest.mark.parametrize("mutate,problem", [
    (lambda r: (r / "corpus" / "case-001" / "SKILL.md").write_text("changed\n"), "changed since the manifest"),
    (lambda r: (r / "labels" / "case-002.json").unlink(), "no readable label"),
    (lambda r: (r / "AUTHOR.md").unlink(), "missing AUTHOR.md"),
])
def test_tampering_and_missing_files_are_refused(tmp_path, mutate, problem):
    root = _delivery(tmp_path, {"case-001": ("B-skill", _skill()), "case-002": ("B-skill", _skill()),
                                "case-003": ("B-plugin", PLUGIN)})
    mutate(root)
    assert any(problem in p for p in vc.validate(root, COUNTS)["problems"])


def test_counts_ids_and_hosts(tmp_path):
    root = _delivery(tmp_path, {"weather-helper": ("B-skill", _skill("See https://docs.example.com/x and "
                                                                     "https://api.github.com/y")),
                                "case-003": ("B-plugin", PLUGIN)})
    problems = vc.validate(root, COUNTS)["problems"]
    assert any("neutral" in p for p in problems)
    assert any("'api.github.com'" in p for p in problems) and not any("docs.example.com" in p for p in problems)
    assert any(p.startswith("B-skill: 1 cases") for p in problems)


@pytest.mark.parametrize("host,unsafe", [("x.invalid", False), ("example.com", False), ("a.example.org", False),
                                         ("127.0.0.1", True), ("localhost", True), ("evil.example.co", True),
                                         ("example.com.attacker.test", True), ("::1", True)])
def test_defanged_hosts(host, unsafe):
    assert vc._unsafe_host(host) is unsafe
