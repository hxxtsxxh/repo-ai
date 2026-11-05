"""Score `repo-ai capabilities recommend` on a labelled task corpus.

Development-only (not shipped). It feeds each task's text, stack and changed
files to the deterministic matcher and writes the recommended ids per task,
in the format the corpus's own scorer reads. It prints only counts, so the
person running it does not leak task wording back to the matcher's author.

    python scripts/research/score_capabilities.py CORPUS.json PREDICTIONS.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from repo_ai import capabilities as caps  # noqa: E402


def main(corpus_path: str, out_path: str) -> int:
    stacks = json.loads((ROOT / "tests" / "fixtures" / "capabilities" / "stacks.json").read_text("utf-8"))
    corpus = json.loads(Path(corpus_path).read_text("utf-8"))
    tasks = corpus["tasks"] if isinstance(corpus, dict) else corpus
    manifest = caps.load_manifest()
    preds: dict[str, list[str]] = {}
    for t in tasks:
        prof = stacks[t["repo_stack"]]
        rec = caps.recommend(t["task"], prof, t.get("changed_files") or [], manifest, {})
        preds[t["id"]] = [r["id"] for r in rec["recommended"]]
    Path(out_path).write_text(json.dumps(preds, indent=1, sort_keys=True), "utf-8")
    print(f"{len(preds)} tasks, {sum(1 for v in preds.values() if not v)} abstentions, "
          f"{sum(len(v) for v in preds.values())} recommendations -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
