"""capability-fresh-v1 scorer (see PREREGISTRATION.md). Offline; runs only the deterministic matcher."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from repo_ai import capabilities as caps  # noqa: E402


def main() -> int:
    stacks = json.loads((ROOT / "tests" / "fixtures" / "capabilities" / "stacks.json").read_text("utf-8"))
    tasks = json.loads((HERE / "corpus.json").read_text("utf-8"))["tasks"]
    manifest = caps.load_manifest()
    rows, recalls, prec_hits, prec_n, forbidden_hits, abstain_ok, empty = [], [], 0, 0, [], 0, 0
    for t in tasks:
        rec = caps.recommend(t["task"], stacks[t["repo_stack"]], t.get("changed_files") or [], manifest, {})
        got = [r["id"] for r in rec["recommended"]][:3]
        gold, forbidden = set(t.get("gold") or []), set(t.get("forbidden") or [])
        if gold:
            recalls.append(len(set(got) & gold) / len(gold))
        else:
            empty += 1
            abstain_ok += not got
        prec_hits += len(set(got) & gold)
        prec_n += len(got)
        forbidden_hits += [f"{t['id']}:{g}" for g in got if g in forbidden]
        rows.append({"id": t["id"], "got": got, "gold": sorted(gold), "forbidden": sorted(forbidden)})
    r1 = sum(recalls) / len(recalls) if recalls else None
    out = {"tasks": len(tasks), "R1_top3_recall": r1, "R1_pass": r1 is not None and r1 >= 0.80,
           "R2_forbidden": forbidden_hits, "R2_pass": not forbidden_hits,
           "R3_correct_abstention": f"{abstain_ok}/{empty}", "R4_top3_precision": prec_hits / prec_n if prec_n else None,
           "rows": rows}
    (HERE / "results.json").write_text(json.dumps(out, indent=1) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
