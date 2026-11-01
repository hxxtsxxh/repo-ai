# journey-offline-v1: results (inconclusive)

Protocol: [PREREGISTRATION.md](PREREGISTRATION.md), committed with the harness and workflow at 0576dc3 before the run.
One run: GitHub Actions [41260337468](https://github.com/hxxtsxxh/repo-ai/actions/runs/41260337468), ubuntu runner,
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
- **J3: not measured correctly (harness defect).** The harness committed `init`'s files before the journey, so after
  `uninstall` removed them and restored `.gitignore`, `git status` against that commit showed the removals. The
  comparison should be against the project's original revision. Amendment 1 below.

**Why it is weak.** The mechanical selection (the latest "fix" commit that touches source and tests) picked a 2013
commit that modern pytest cannot collect, a typing-only change and, for itsdangerous, nothing. The protocol was
followed; it chose poor defects. C21 stays EXPERIMENTAL.

## Amendment 1 (after run 1; for any future run)

- J3 compares the working tree after `uninstall` with the project's original revision (`git diff --stat P`),
  not with the commit that recorded `init`.
- Selection should also require that the fix commit's tests fail natively without the fix, so that J1 has power;
  that is a new protocol (journey-offline-v2), not a change to this one.
