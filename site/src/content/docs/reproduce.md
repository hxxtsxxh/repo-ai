---
title: Repeat our journeys
description: Exact commands to repeat repo-ai's real-project journeys yourself, offline on a disposable runner and live with your own Claude Code login, and how to compare your results with ours.
---

The claims on this site about real projects come from two preregistered studies whose harnesses are in the source
tree. You can run both yourself and compare. Neither needs anything from us: no account, no key, no telemetry.

| | offline journey | live journey |
|---|---|---|
| Harness | `benchmarks/journey-offline-v2/run.py` | `benchmarks/journey-live-v1/run.py` |
| What it shows | `verify` on 7 real upstream fixes in 4 projects: does it ever call a broken change safe? | `repo-ai do --agent claude` on 4 real upstream defects: candidate, frozen tests, hidden upstream oracle, apply and undo |
| Where project code runs | a disposable GitHub Actions runner (never your machine) | podman containers only (dependencies-only images, no network) |
| Cost | $0, no model | Claude Code's reported cost, capped at $1.00 per session by `--max-budget-usd`; ours came to $0.04–$0.08 per session |
| Our results | [RESULTS.md](https://github.com/hxxtsxxh/repo-ai/blob/main/benchmarks/journey-offline-v2/RESULTS.md) | [RESULTS.md](https://github.com/hxxtsxxh/repo-ai/blob/main/benchmarks/journey-live-v1/RESULTS.md) |

## Offline: on a disposable runner

The harness clones and tests third-party projects, so it refuses to run unless `REPO_AI_JOURNEY=1` is set, and the
workflow that sets it runs only on branches named `journey/...`, never on pull requests.

1. Fork [hxxtsxxh/repo-ai](https://github.com/hxxtsxxh/repo-ai) and enable Actions on the fork.
2. Push a branch whose name starts with `journey/`:

   ```sh
   git clone https://github.com/<you>/repo-ai && cd repo-ai
   git switch -c journey/repeat && git push -u origin journey/repeat
   ```

3. The `journey` workflow installs repo-ai from that checkout, installs bubblewrap, and runs `journey-offline-v1`
   and `journey-offline-v2`. Download the `journey-offline-v2` artifact (`journey-offline-v2.json`) from the run.
4. Compare it with our [run-1.json](https://github.com/hxxtsxxh/repo-ai/blob/main/benchmarks/journey-offline-v2/results/run-1.json).
   The question that matters is the first gate: a change whose tests fail without the fix must never come out as
   `selected passed` or `full passed` (ours: 0 of 7; 5 detected as a regression, 2 refused because more-itertools
   declares no test command). Upstream commits are pinned by tag, so your defects should be the same seven.

## Live: with your own Claude Code login

**Requirements:** macOS or Linux; `git`; [podman](https://podman.io/) (on macOS a running `podman machine`);
Python 3.10+; Claude Code; about 1 GB of disk for the clones and four images. Project code never runs on your machine: the harness
checks the frozen tests, the positive control, every mission and the oracle in podman containers with no network,
a read-only root and no capabilities. The model only sees a disposable copy of each project and can only edit the
file the task names.

1. Install repo-ai from PyPI into its own virtualenv, and give repo-ai its own Claude Code login (separate from your
   `~/.claude`; nothing of yours is copied):

   ```sh
   python3 -m venv ~/repo-ai-venv && ~/repo-ai-venv/bin/pip install repo-ai-cli
   CLAUDE_CONFIG_DIR=~/.local/share/repo-ai/claude-provider claude auth login
   ```

2. Get the harness (a checkout of this repository) and pick a work directory under your home directory (the
   provider sandbox cannot read it, so the upstream history and records stay out of the model's reach):

   ```sh
   git clone https://github.com/hxxtsxxh/repo-ai && cd repo-ai/benchmarks/journey-live-v1
   W=~/journey-live-v1-work
   ```

3. Run the stages. The first two make no model call; `run` is the only one that spends:

   ```sh
   python3 run.py prep    --work "$W"                                  # clones, frozen tests, images, native checks
   python3 run.py control --work "$W" --repo-ai ~/repo-ai-venv/bin/repo-ai   # upstream fix as a replay: must PASS
   python3 run.py run     --work "$W" --repo-ai ~/repo-ai-venv/bin/repo-ai --max-sessions 4
   python3 run.py recovery --work "$W" --repo-ai ~/repo-ai-venv/bin/repo-ai  # no model: a broken image must not pass
   ```

   Add `--only humanize` (repeatable) to run fewer defects, and lower `--max-sessions` to cap the spend. Sessions are
   counted from `"$W"/records.jsonl`, so running `run` again never repeats one. A stage refuses before any model call
   if repo-ai workspaces from an earlier run are still in the shared workspace directory; don't run other repo-ai
   missions at the same time.

4. Read `"$W"/records.jsonl`. For each defect, compare with our table: the mission verdict, `native-frozen`
   (`l1_violation` must be false on a PASS), `oracle` (`behavioural_differences`), and `apply-undo`
   (`undo_identical` must be true). Our runs: pyjwt, more-itertools and humanize PASS end to end; marshmallow is
   INCONCLUSIVE by design, because one of its tests takes a parameter from the clock and its test IDs differ between
   any two runs.

**What to expect, honestly.** The upstream fixes predate the model's training data, so a candidate that matches
upstream may be recall; this is an adopter journey, not a capability benchmark. The model is told which file to edit.
Your model version, and so your candidates and cost, can differ from ours; a different outcome is a result worth
reporting. Claude Code checks its budget between turns, so one turn can overshoot the cap.

If your results differ, please open an issue with your `records.jsonl` (it contains paths from your machine:
redact them) and `repo-ai --version`.
