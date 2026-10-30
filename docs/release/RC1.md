# repo-ai 0.8.0rc1 release evidence

**Release status: BLOCKED pending full CI of the Xcode-corrected candidate. Local validation, independent source/wheel review and targeted macOS diagnosis passed.**
The corrective source is frozen. No tag or release has been published. The repository remains private.
The machine-readable record is [rc1-manifest.json](rc1-manifest.json).

## Recovered task scope

This continuation investigated Claude sessions `5f77186f-017e-407e-b1c1-9cf095a31d50`
(verification and independent qualification) and `093b09ff-5894-4fdc-8744-bec5d416f737`
(product integration and release). Their latest user instructions froze the release scope:
close reproduced defects, qualify one coherent RC1, preserve negative evidence, and avoid
new feature development or paid CI without authorization. The second session stopped while
investigating D1; its uncommitted regression test was preserved and completed. Other worktrees
and the earlier sealed-certification stop were left intact.

## Candidate identity

| Item | Exact value |
|---|---|
| Corrective branch | `codex/rc1-completion-20261026` |
| Previous candidate | `893b65db49c1784376837ae7a55db0bf6b4ce98e` (previous frozen correction) |
| Main / prior qualified build | `903984a46efccba4d19550587372ce688653ecad` |
| Code and tests commit | `75a55bf67063392247c5efa9ad458bbf1a4dda46` |
| Source tree | `1dc129aa879a4c7d53801f4b10ae1e9e3ed8f5f8` |
| Tests tree | `8a6ebe8a4419f60f266492de139b76fea01ca2ce` |
| Version | `0.8.0rc1` |
| Wheel | `repo_ai-0.8.0rc1-py3-none-any.whl` |
| Wheel SHA256 | `c4787870a1b889aeb9fd5de45ccfd29cd6a9db4d9818c533cac6abc170f499a2` |

The final commit and sdist checksum are recorded in the **external** `release-evidence.json` and
`SHA256SUMS` beside the artifacts. This avoids putting an archive's checksum inside that same archive.
The wheel contains source, the offline evaluation suite and README metadata; release docs are in the
sdist only. Docs-only completion commits can therefore retain this wheel checksum. Always compare
source/test tree hashes as well as the final commit.

Build recipe: clean `git archive`, Python 3.12.14, build 1.6.1, hatchling 1.32.4,
`python -m build --no-isolation`, `SOURCE_DATE_EPOCH` unset. Two clean builds of the code freeze
produced identical wheel and sdist bytes. The final documentation sdist is verified twice; its hashes and byte audit are recorded externally in `release-evidence.json`.

## Corrections since the release freeze

- **Apple system Python:** required macOS CI exposed an Xcode launcher failure. Static resolution now selects the actual runtime, without executing anything during freshness reading or granting access to the Xcode bundle. Invalid explicit selections, self-references and repository-owned tracked targets fail closed; virtualenv paths remain intact. Changing Xcode selection makes prior evidence stale.

- **Freshness D1:** `evidence`, verification status and the Stop gate reject a different or missing
  repo-ai version, missing environment identity, and a different currently selected Python/Node
  interpreter. Selection uses the execution path's resolver without executing the interpreter.
  Malformed host identities also abstain; container images remain explicitly unchecked.
- **Uninstall D2:** user-selected exports such as `.repo-ai/proof.md` are preserved and listed in
  preview and execution. Unreadable user directories are preserved and disclosed. Managed stores
  are removed; edited configuration and notes are retained.
- **Documentation:** fixed version, pytest setup prerequisite, declared ProofLab subjects, skill
  inventory, support scope and full-suite pass semantics. The offline evaluation README now
  distinguishes original synthetic fixtures from the six upstream source snapshots.
- **Manifest:** the previous manifest described `4f37063` and wheel `7d7ca352…`, although the candidate
  had advanced to `b209166`. Those hashes and test counts are historical, not this build's evidence.

Test selection, outcome classification, baseline comparison and sandbox permissions are unchanged from the previously evaluated main. Freshness reading and interpreter resolution changed and have separate regression evidence; the whole verification tree is not identical to the held-out build.

## Validation

| Check | Result / scope |
|---|---|
| Failing-first regressions against `b209166` | 8 failed as expected: version, missing version, virtualenv/PATH selection and report retention |
| Initial focused corrective suite | 58 passed, 3 sandbox-dependent skips |
| Independent source review | PASS after closing incomplete host identity, malformed runner type and unreadable-directory findings |
| Final Apple launcher source review | PASS after canonical self-reference correction; all 18 launcher regressions independently passed |
| Lint / mypy / plugin bundle | final recheck passed on frozen corrective source (93 source files type-checked) |
| Earlier corrected source `7e57687` | 1729 passed, 8 xfailed; historical validation of the previous candidate |
| Full host suite on corrected source `75a55bf` | **1745 passed, 2 skipped, 8 xfailed**, 1989.51 s; macOS 26.5.1 arm64, Python 3.13.14, seatbelt |
| Two real-Ruff checks skipped above | **2 passed** separately after adding the installed Ruff binary to PATH |
| Apple launcher regressions | 13 failed before the fix; final 18 passed, including the independently found canonical self-reference case |
| Targeted macOS CI | **24 passed in 19.02 s**, original failing module and new regressions; source/tests identical to `75a55bf`, diagnostic workflow only |
| Preliminary installed wheel (earlier candidate) | 21 acceptance checks passed, including real regression/fix, stale evidence, permission preservation, Claude/Bob smart setup and exact uninstall |
| Final wheel | independent packaging review PASS; 27 installed acceptance checks passed for pytest and Node, stale evidence, preserved permissions, smart Claude/Bob setup and exact uninstall |
| Retrieval regression benchmark | completed; no retrieval code changed in this correction |

The first full-suite attempt was interrupted: 778 passed, 2 expected failures, 5 failures. One was a
new skill placeholder rejected by the existing validator (fixed). Four selected system Python without
pytest; all four passed after explicitly activating the test environment. The final run uses that
environment. This failed attempt is retained, not counted as a passing suite.

Session A's recovered run on `8556495` finished with **1 failed, 1707 passed, 6 xfailed**. The failure
required commit/wheel provenance but that installation exposed only its installed RECORD digest.
The fresh wheel install here records its actual wheel SHA256 through pip's `direct_url.json`.
That earlier failure is not relabelled as a pass.

## Prior qualification and supported scope

Session A's [FINAL_A_RELEASE_QUALIFICATION](https://github.com/hxxtsxxh/repo-ai/pull/24#issuecomment-6414777596)
was **CONDITIONAL_WITH_EXPLICIT_LIMITATIONS** for core verification on `903984a`, not this candidate.
Held-out-7 covered five pytest and `node --test` projects in podman containers: zero false assurances
in 127 failing states, zero new failures classified as pre-existing, zero false alarms, runtime
no-miss 96.7%, and unchanged trees in 234/234 runs. These remain evidence for that evaluated build.
The new local regressions and source review address the corrective delta; they are not a fresh holdout.

| Capability | Declared scope and limits |
|---|---|
| Index, context, impact, review, privacy, status, doctor | local repository intelligence; review does not consume verify evidence yet |
| Init / uninstall | Claude Code, Bob, both or no agent; preserve user instructions/permissions; list retained user files |
| Verify plan, execution, record | qualified runner classes: pytest and `node --test`; existing full-suite tests may pass even with no linked selection |
| Evidence and gate reading | change fingerprint, tool version and recorded/current environment identity; gate is opt-in and bounded, not an agent-success guarantee |
| macOS seatbelt / Linux bubblewrap | supported implementations with local suite / earlier CI evidence; held-out-7 did not exercise these host backends |
| Containers | held-out-7 used podman; no Windows held-out measurement |
| unittest and TypeScript | implemented and tested, not independently qualified runner classes |
| Jest/Vitest/Mocha and multiple runners | no qualified support; opaque runners require whole-suite execution |
| Windows host execution | unavailable; container backend required, not measured on held-out data |

Cancellation on tinydb and candlestick was missing in the frozen held-out run. Session A's recovered
**post-hoc** delay-0.2 probes on the earlier RC1 were clean in 6/6 runs. This repairs missing diagnostic
information; it does not change the frozen evaluation score or qualify this new artifact.

## Experimental exclusions and remaining limits

**ProofLab is NOT QUALIFIED or certified.** The three confirmed false-proof classes remain open:
`always-equal-class`, `swallowed-assertion`, `importorskip-zero-entry-points`. They are named in its
outputs and retained as strict expected failures. The sealed certification remains blocked by the
previous safety stop; no attempt was made to retry or circumvent it. No hook, verify verdict or gate
relies on ProofLab. Its installed skill is manual-only.

Other experimental features: capability discovery, plugin inspection, third-party skills, `--smart`,
learning/optimization, full feature set, adaptive verification reuse and the gate's effect on agents.
PRs #52 (evidence graph) and #57 (retrieval prototype) remain outside this release.

No general speed or coding-agent benefit claim: verification was slower than native on three of five
held-out projects; hanging Node tests took about 36 seconds. Environment metadata still excludes
bytecode caches, symlinked package contents and editable source outside recorded directories. Local
writers can forge evidence. The gate fails open on internal errors and is not a security boundary.

Bundled upstream source/license inventory: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## CI, spending and integration gate

The previous frozen candidate `893b65d` was tested by run [40448692912](https://github.com/hxxtsxxh/repo-ai/actions/runs/40448692912).
Attempt 1 passed 12/13 jobs; macOS reported **1 failed, 1714 passed, 4 skipped, 8 xfailed**.
`test_status_json_names_the_false_proof` received fail-closed `incomplete` instead of `supported`.
Ten separate local invocations passed, but the unchanged macOS retry (attempt 3) failed identically.
Neither failure is relabelled a pass or an infrastructure flake.

Attempt 2 was cancelled by a Codex watchdog error: GitHub copied prior successful results into the retry
with new job IDs, and the guard misread them as new executions. It consumed two macOS minutes without a
diagnostic result. The corrected guard's copied-record accounting and dispatch-error lifecycle were
independently reviewed. This cancellation is separate from the product defect.

Bounded diagnostic runs retained complete passports and identified the exact `xcrun` startup error:
its stderr SHA256 matched every failed scenario observation. A direct-runtime probe succeeded; adding
read access only to Xcode's `usr` directory did not. The product correction resolves Apple's exact
system launcher statically. Diagnostic run [40469522924](https://github.com/hxxtsxxh/repo-ai/actions/runs/40469522924)
passed **24 tests** on the affected macOS 26.6.2 runner. Its source/tests equal the new code freeze,
but its workflow is intentionally diagnostic and cannot replace full-matrix qualification.

The older full runs `40246695220` (13/13, ancestor `4d91b85`) and `40251611104` (12/12, macOS excluded;
source/tests equal main `903984a`) also do not qualify this corrected candidate.
The unchanged release workflow still requires lint/types, Linux Python 3.10–3.14, Windows Python
3.10/3.13, macOS, Docker/bubblewrap, offline evaluation and retrieval. No required check was removed.

The user approved a separate **$3.50 cumulative CI allowance** after the historical $10 session ledger.
Authenticated billing access is now available. New run estimates total **$3.148**, leaving **$0.352**:
initial matrix $1.722; cancelled retry $0.124; unchanged failed retry $1.116; three one-minute macOS
diagnostics $0.186. Prices are verified against billing; final invoice posting may lag.
No paid model evaluations ran. A new full matrix is estimated around $1.72 before cancellation reserve,
so additional spending approval is required. Complete all free validation and freeze the exact new
candidate before requesting it. Main stays `903984a`; no RC tag or release has been created.
