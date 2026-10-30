# C10 skill-value pilot, 2026-10-30: INCONCLUSIVE (predeclared rule)

Protocol predeclared in `EXPERIMENTS.md` and pushed (commit `263b24d`) before the first live call. Everything needed to
re-run is in `c10-pilot/`: the fixture (`base/`), the skill (`skill/`), the hidden oracle (`oracle/`), the harness
(`pilot.py`, `grade.sh`), the random arm assignment (`mapping.json`), per-run results (`results.json`) and each run's
candidate diff (`candidates/`).

Setup: repo-ai 0.11.1 development build at `029e6fa`; the skill installed in the skill arm through `repo-ai skills
discover --from-path` and `skills install --approve ab942622969d0a1e --host claude-code`; both arms ran `repo-ai init
--agent none`. Claude Code 2.1.314 host mode, dedicated login, `haiku`, file tools only (`--setting-sources project
--tools Read,Write,Edit,Glob,Grep,Skill --strict-mcp-config`), $0.30 cap per run. Calls #27–#32, 19:00–19:03Z.

## Result

| Task | Hidden rule exercised | Skill arm | Control | Higher |
|---|---|---|---|---|
| t1 `apply_discount` | rounding (rule 2, visible in code), percent range (rule 4) | 6/8 | 8/8 | control |
| t2 `invoice_total` | tax rounded per line (rule 5), percent range (rule 4) | 7/7 | 4/7 | skill |
| t3 `split_amount` | leftover cents to the earliest shares (rule 6) | 7/7 | 7/7 | tie |

Predeclared rule: the skill arm higher on 1 task, the control higher on 1 → **INCONCLUSIVE**. C10 stays
NOT_YET_DEMONSTRATED.

## What the runs show

- **Unprompted invocation:** the model called `Skill(invoicekit-conventions)` first in 3 of 3 skill-arm runs; no
  prompt named the skill. This repeats the earlier model-chosen invocation (`SKILL-HOSTS-2026-10-30.md`) on a new skill.
- **t2 is the case the skill was built for.** The control taxed the subtotal (`11 != 10`, `231 != 230`) and accepted a
  150 % rate; the skill arm taxed per line and rejected it. Without the skill, nothing in the repository states that rule.
- **t3:** the control chose "leftover cents to the earliest shares" unaided. It is the common default, so the pilot
  had no gap to measure there.
- **t1: the oracle encoded an ambiguous choice (post-hoc observation, not used to rescore).** Rule 2 says "round to
  the cent with ROUND_HALF_EVEN" but not *what* is rounded. The skill arm rounded the discount and subtracted it
  (125 → 113); the oracle and the control round the amount left (125 → 112). Both read the rule literally. Rescoring
  t1 as a tie would still give INCONCLUSIVE (one task higher, none lower).
- **Isolation held:** three runs (two skill, one control) tried `Bash` to run pytest; each got "No such tool
  available: Bash". No run read or wrote a path outside its project. Visible tests passed in all six projects.
- **Cost:** $0.0255 notional for six runs (skill arm $0.0145, control $0.0110: the skill read adds a turn).

## Product findings

- `repo-ai skills explain` recommended **against** installing the skill ("matches no evidence-backed capability gap"):
  the radar does not recognise project-convention skills as filling a gap. Queued.
- Claude Code's `--restricted` removes project skills from the session (verified with a $0 init probe), so host-mode
  skill trials cannot use it; `--setting-sources project` plus `--tools` and `--strict-mcp-config` can.

## Limits

One author wrote the fixture, skill, tasks and oracle; one model; n = 3 pairs; the knowledge gap was designed in.
Grading was by script, so the blinding covers only the order of grading. A confirmatory trial needs independently
written tasks and oracles with unambiguous rules, and more pairs.
