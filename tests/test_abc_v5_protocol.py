"""abc-v5 calibration set: manifest seal and grader controls (free; no live provider)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "abc-v5"
pytestmark = [pytest.mark.skipif(not ROOT.is_dir(), reason="benchmarks/abc-v5 not present"),
              pytest.mark.skipif(shutil.which("node") is None, reason="the Node calibration tasks need node")]


def _run(*args):
    env = {**os.environ, "PYTHONPATH": str(ROOT.parents[1] / "src")}
    env.pop("AI_AGENT", None)
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, env=env, timeout=600)


def test_manifest_is_sealed():
    out = _run("make_manifest.py", "verify")
    assert out.returncode == 0 and out.stdout.strip().endswith("OK"), out.stdout + out.stderr


def test_grader_controls_pass():
    out = _run("selfcheck.py")
    assert out.returncode == 0 and "OK: 0 failing check(s)" in out.stdout, out.stdout[-2000:] + out.stderr[-2000:]
