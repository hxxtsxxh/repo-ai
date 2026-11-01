# journey-offline-v1: results (inconclusive)

Protocol: [PREREGISTRATION.md](PREREGISTRATION.md), committed with the harness and workflow at 0576dc3 before the run.
One run (2026-11-01T01:15Z): GitHub Actions [41260337468](https://github.com/hxxtsxxh/repo-ai/actions/runs/41260337468), ubuntu runner,
bwrap. Raw: [results/run-1.json](results/run-1.json). Spend: $0.

| project | fix commit chosen | quickstart / init / record | fix: native, verify | test without fix: native, verify | uninstall |
|---|---|---|---|---|---|
| python-humanize/humanize | 1bf3f4c7 (2013) | 0 / 0 / 1 | 5 (no tests collected), 1 | 5, 1 | see below |
| pallets/itsdangerous | none within the rules | — | — | — | — |
| marshmallow-code/marshmallow | 01fab376 (typing fix) | 0 / 0 / 0 | 0, 0 (selected passed) | 0, 0 (selected passed) | see below |

**Gates.**
- **J1 (no false assurance): 0 cases, but with no power.** In no test-without-fix state did the native suite fail
  (humanize collected no tests on its 2013 tree; marshmallow's test change is a typing case that passes without the
  fix), so verify had nothing it could falsely pass.
- **J2:** the one fix state with a passing native suite (marshmallow) passed under verify.
- **J3: unknown (harness defect).** The harness committed `init`'s files before the journey and compared the tree
  after `uninstall` with that commit, so the `D .repo-ai/...` and ` M .gitignore` lines are consistent with uninstall
  removing its files, but the recorded status was cut at 400 characters (hiding any untracked leftovers) and was
  never compared with the original revision. Amendment 1 below.

**Why it is weak (found by an independent review).** Selection walked `git log --no-merges --first-parent`, which
skips every change merged through a pull-request merge commit. humanize 4.12.3's tip is itself a fix merged that way
(2968d442, "Fix regression in `naturalsize`…", two parents), so the walk fell back to a 2013 feature commit that
matched only through "(fixes #2)"; itsdangerous also merges pull requests, which likely explains finding nothing;
marshmallow's pick was a typing-only change. The protocol was followed; its selection rule was the problem. C21 stays
EXPERIMENTAL.

## Amendment 1 (after run 1; for any future run)

- J3 compares the tree after `uninstall` with the project's original revision: tracked differences
  (`git diff --stat P`) and untracked leftovers (`git ls-files --others --exclude-standard`), recorded in full.
- A new protocol (journey-offline-v2), not a change to this one, should select from merged pull requests too (second
  parents of merges, or squash commits) and require that the fix's tests fail natively without the fix, so that J1
  has power.
