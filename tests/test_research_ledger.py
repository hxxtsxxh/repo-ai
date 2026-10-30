"""The development-only research ledger (scripts/research/ledger.py).

It must refuse a ledger that could mislead: a post marked INSPECTED without
observations, a technology no source mentions, an "implemented" claim with
no evidence.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "research" / "ledger.py"
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="development scripts are not shipped")


@pytest.fixture(scope="module")
def ledger():
    spec = importlib.util.spec_from_file_location("research_ledger", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GOOD = {
    "schema": "repo-ai.research-ledger/1",
    "sources": [
        {"id": "S01", "url": "https://example.invalid/p/1", "status": "INSPECTED", "format": "video",
         "observations": [{"at": "0:05", "seen": "repo name on screen"}],
         "claims": [{"claim": "it is fast", "confidence": "unverified"}], "technologies": ["T1"]},
        {"id": "S02", "url": "https://example.invalid/p/2", "status": "INACCESSIBLE", "format": "unknown",
         "unavailable": "login wall; no caption or media", "technologies": []},
    ],
    "technologies": [
        {"id": "T1", "name": "Widget", "repo": "acme/widget", "commit": "a" * 40, "license": "MIT",
         "disposition": "E", "reason": "plain Claude Code already does this", "integration": "rejected"},
    ],
}


def test_a_consistent_ledger_passes_and_renders(ledger):
    assert ledger.check(GOOD) == []
    text = ledger.render(GOOD)
    assert "**INSPECTED**" in text and "**INACCESSIBLE**" in text and "acme/widget" in text


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d["sources"][0].update(observations=[]), "INSPECTED needs"),
    (lambda d: d["sources"][1].update(unavailable=""), "INACCESSIBLE must say"),
    (lambda d: d["sources"][1].update(observations=[{"at": "0:01", "seen": "x"}]), "cannot carry"),
    (lambda d: d["sources"][0].update(technologies=[]), "no source mentions it"),
    (lambda d: d["sources"][0].update(technologies=["T1", "T9"]), "no technology entry"),
    (lambda d: d["technologies"][0].update(reason=""), "needs a reason"),
    (lambda d: d["technologies"][0].update(commit="main"), "40-hex"),
    (lambda d: d["technologies"][0].update(integration="implemented"), "needs `evidence`"),
    (lambda d: d["sources"][0]["claims"][0].update(confidence="sure"), "needs confidence"),
    (lambda d: d["sources"][0].update(status="WATCHED"), "status"),
])
def test_misleading_ledgers_are_refused(ledger, mutate, expected):
    data = copy.deepcopy(GOOD)
    mutate(data)
    assert any(expected in e for e in ledger.check(data)), ledger.check(data)


def test_render_into_keeps_the_hand_written_text(ledger, tmp_path: Path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(GOOD), encoding="utf-8")
    report = tmp_path / "REPORT.md"
    report.write_text(f"# Intro\n\n{ledger.BEGIN}\nold\n{ledger.END}\n\n## Analysis\nkept\n", "utf-8")
    assert ledger.main(["render", str(path), "--into", str(report)]) == 0
    out = report.read_text("utf-8")
    assert out.startswith("# Intro") and out.endswith("## Analysis\nkept\n")
    assert "old" not in out and "acme/widget" in out
    assert ledger.main(["render", str(path), "--into", str(report)]) == 0
    assert report.read_text("utf-8") == out  # idempotent


def test_new_refuses_to_overwrite(ledger, tmp_path: Path):
    path = tmp_path / "l.json"
    data = ledger.new(path, ["https://example.invalid/a", "https://example.invalid/b"])
    assert [s["status"] for s in data["sources"]] == ["UNREVIEWED", "UNREVIEWED"]
    with pytest.raises(SystemExit):
        ledger.new(path, ["https://example.invalid/c"])
