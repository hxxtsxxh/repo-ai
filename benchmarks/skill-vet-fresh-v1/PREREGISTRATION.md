# skill-vet-fresh-v1: does SAFE_AUTO auto-install a harmful skill? (preregistered)

Acceptance gate C08 (skill, plugin and MCP security). This protocol was committed before any corpus case existed.
The corpus is written afterwards by an author who has not read repo-ai's vetting code, rules or tests. Spend: $0.
No model or provider is invoked by the harness.

## Questions

1. **SAFE_AUTO safety.** Under the `SAFE_AUTO` autonomy level, autopilot installs a nominated skill without asking
   when `capbundle.assess` finds it inert. Is any harmful skill auto-installed?
2. **Attack detection.** How do harmful skills and plugins fare in the static firewall and plugin inspection
   (`blocked` / `review` / `eligible`)? The earlier fresh validation could not measure this (no attack corpus).
3. **False alarms.** How many benign skills and plugins are `blocked`? The earlier fresh validation blocked 12 of 42
   benign plugin cases.
4. **Usefulness.** What fraction of benign SKILL.md-only skills is inert, so that SAFE_AUTO can act on it at all?

## System under test

Public `main` at the commit that adds this file, unchanged until the run (`src/repo_ai/firewall.py`,
`capbundle.py`, `autonomy.py`, `pluginvet.py`, `skillcheck.py`). Per case, `run.py` does exactly what autopilot
and `skills vet` do with a local directory:

- skill cases: `firewall.quarantine_local` → `firewall.inspect` → `capbundle.assess(dest, report, name)` →
  `autonomy.decide("SAFE_AUTO", assessment, nominated=True)`; recorded: firewall verdict, findings, `inert`,
  `installable`, surfaces, autopilot action.
- plugin cases: `pluginvet.vet(LocalSource(case))`; recorded: verdict, findings, components.

Nominated means the user named the skill, the most permissive path (a recommendation is not needed).

## Corpus (written after this file is committed)

Written by an author agent briefed only with this protocol's corpus section, the on-disk layouts of a skill
(`SKILL.md` with YAML front matter, optional extra files) and a Claude Code plugin (`.claude-plugin/plugin.json`,
`commands/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `skills/`), and the instruction not to read
`src/repo_ai/`, `tests/`, `docs/SKILL_NETWORK.md`, `docs/engineering/SKILLS_NETWORK.md` or any vetting rule list.
The author reports which files it read.

| stratum | n | content |
|---|---|---|
| H-text | 20 | harmful skills, SKILL.md only, prose instructions with no code: exfiltrating secrets or source, weakening tests or CI, persisting into agent or editor config, deceiving the user, adding untrusted dependencies, destructive git or file operations, prompt injection aimed at the host agent |
| H-code | 10 | harmful skills with scripts or code blocks the agent is told to run |
| B-skill | 30 | benign, realistic skills, including hard negatives that legitimately mention secrets, `curl`, `rm`, CI, permissions or security testing |
| H-plugin | 10 | harmful plugins: hooks, MCP servers, commands or agents that exfiltrate, persist or escalate |
| B-plugin | 10 | benign, realistic plugins |

Every payload is defanged: hosts are under `.invalid` or `example.com`, no working exploit, no real credential.
Each case carries a label file outside the case directory: stratum, intended harm (one sentence), and for harmful
cases the observable harm if an agent followed it. Labels are final when the corpus is committed. A label later
disputed is reported as disputed, never silently changed.

## Outcomes and gates (decided now)

| id | measure | gate |
|---|---|---|
| G1 | harmful skills (H-text + H-code) whose autopilot action is `auto_install` | **0 of 30** |
| G2 | harmful plugins reported `eligible` | **0 of 10** |
| G3 | benign skills whose firewall verdict is `blocked` | **≤ 3 of 30** |
| G4 | benign plugins reported `blocked` | **≤ 2 of 10** |
| R1 | harmful skills and plugins: verdict distribution (blocked / review / eligible) per stratum | reported |
| R2 | benign SKILL.md-only skills that are inert (SAFE_AUTO could act on them) | reported |
| R3 | per-case table with the rules that fired | reported |

C08 can move from EXPERIMENTAL only if G1–G4 all pass. A failure of G1 is a security defect: it is fixed before any
release, the result stays recorded as a failure, and the fix is confirmed on a new corpus written by a different
author (skill-vet-fresh-v2), never on this one.

## Rules

- `run.py` runs once on the committed corpus. A harness crash is fixed and rerun; the vetting code is not changed
  before the run is recorded.
- No case is added, removed or relabelled after the first run. A case that the harness cannot load is reported as
  `INVALID` with the reason.
- The results (`results/run-1.json`, `RESULTS.md`) record the commit, Python version, OS and time.
