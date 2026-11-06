/**
 * Terminal walkthrough for the landing page.
 *
 * Every line below was captured on 2026-11-05 by running repo-ai 0.12.7 (PyPI) on
 * macOS, in a throwaway git repository copied from tests/fixtures/pyweb, with
 * `scripts/record_transcripts.py` (temporary HOME and REPO_AI_HOME; the demo's
 * tests ran under Python 3.12 with pytest and PyJWT). The raw record, with exit
 * codes and durations, is benchmarks/site-transcripts/transcripts-0.12.7.jsonl.
 * The only edits: lines removed (marked with a `trim` line), absolute paths
 * shortened to `…/`, and a home directory shown as `~`.
 * `do --dry-run` and `agents list` ran on the clean checkout, before the change;
 * `agents list` reflects the agent CLIs on the recording machine's PATH.
 * The change verified in the verify steps adds `email = (email or "").strip()`
 * at the top of validate_credentials in app/auth/login.py.
 * To refresh, re-run the script against the release and copy its lines; never
 * type or alter output by hand.
 */
export type LineKind = 'cmd' | 'out' | 'dim' | 'head' | 'pass' | 'warn' | 'fail' | 'trim';
export interface Line {
  k: LineKind;
  t: string;
}
export interface Transcript {
  id: string;
  label: string;
  summary: string;
  lines: Line[];
}

const o = (t: string): Line => ({ k: 'out', t });
const d = (t: string): Line => ({ k: 'dim', t });
const h = (t: string): Line => ({ k: 'head', t });
const trim = (t = 'lines trimmed'): Line => ({ k: 'trim', t: `… ${t}` });

export const transcripts: Transcript[] = [
  {
    id: 'init',
    label: 'init',
    summary: 'Index the repository offline. No agent wiring with --agent none.',
    lines: [
      { k: 'cmd', t: 'repo-ai init --agent none' },
      d('[  0.00s] repo-ai 0.12.7 — initialising …/demo'),
      d('[  0.01s] scanning …/demo'),
      d('[  0.02s] scan complete: 25 indexable files (30 seen, 6 skipped, 0 unchanged)'),
      d('[  0.02s] parsing 25 files (stdlib ast + regex fallback)'),
      d('[  0.02s] found 5 manifests, 10 declared dependencies'),
      d('[  0.31s] git: main@3685d52, 1 commits, 1 contributors'),
      d('[  0.32s] analysis complete in 0.3s'),
      o(''),
      h('  repo-ai 0.12.7 — demo: 25 files, 212 LOC, 2 component(s) [Python, TypeScript]'),
      o('  agents: none (docs only)   learning: suggest   skills: curated   layout: .repo-ai/context/'),
      o('  changed 13 file(s)'),
      o('    create  .gitignore'),
      o('    create  .repo-ai/config.toml'),
      o('    (+ 11 generated docs under .repo-ai/context/)'),
      o('  rules: 0 active, 3 proposed (`repo-ai learn` to review)'),
      { k: 'warn', t: "  ! tree-sitter not installed: non-Python symbol extraction uses the regex fallback. Install with `pip install 'repo-ai-cli[ast]'` (with pipx: `pipx inject repo-ai-cli 'tree-sitter>=0.23' 'tree-sitter-language-pack>=0.7,<1.0'`) for higher fidelity." },
    ],
  },
  {
    id: 'context',
    label: 'context',
    summary: 'A ranked shortlist for a task, with the reason for each file.',
    lines: [
      { k: 'cmd', t: 'repo-ai context "fix the login validation bug"' },
      d('<repo-ai-context>'),
      o('Retrieved by repo-ai for this request. Confidence: high. Task class: auth, bug. Start with these files; ignore the rest of the repository unless they prove insufficient.'),
      o(''),
      o('Verify with: `make test`'),
      o(''),
      o('| # | File | Why | Look at |'),
      o('|---|------|-----|---------|'),
      o('| 1 | `app/auth/login.py` — Login flow: credential validation and token issuance. | keyword match, named like the task, auth path, imported by users.py | L1-24 (class LoginError, function validate_credentials) |'),
      o('| 2 | `tests/test_login.py` | keyword match, named like the task, auth path, imports login.py | whole file (8 lines) |'),
      o('| 3 | `web/src/components/LoginForm.tsx` | keyword match, named like the task, auth path, imported by LoginForm.test.tsx | L1-10 (function LoginForm) |'),
      trim('rows 4–9 and the @-mentions line trimmed'),
      d('</repo-ai-context>'),
    ],
  },
  {
    id: 'verify',
    label: 'verify',
    summary: 'Read-only plan: what the change touched and which tests can show a break.',
    lines: [
      { k: 'cmd', t: 'repo-ai verify' },
      h('repo-ai verify: 2 changed files against HEAD'),
      o(''),
      o('changed'),
      o('  .gitignore  [data, added]'),
      o("      only repo-ai's own managed block in .gitignore changed"),
      o('  app/auth/login.py  [source, modified, units: validate_credentials]'),
      o('      evidence: 1 linked test file(s); runtime evidence none'),
      o(''),
      o('selected 1 of 3 test files'),
      o('  tests/test_login.py  [static] imports app/auth/login.py'),
      o(''),
      { k: 'warn', t: 'confidence: MEDIUM: some of the change rests on static evidence only (imports or file names), not on runtime evidence' },
      trim('uncertainty notes and test command trimmed'),
      o('run'),
      o('  targeted:   python -m pytest -q -p no:cacheprovider tests/test_login.py'),
      o('  full suite: python -m pytest -q tests   (before merging)'),
      o('  sandboxed:  repo-ai verify --run   (--full runs the full suite instead)'),
      o('              tests run in a disposable copy of the working tree, never in it; failures are re-checked against the base'),
      o('  sharper:    repo-ai verify --record   (once: records which code each test runs)'),
      o(''),
      o('evidence: none yet for this repository'),
    ],
  },
  {
    id: 'run',
    label: 'verify --run',
    summary: 'Run the selection sandboxed, in a disposable copy; the tree is checked before and after.',
    lines: [
      { k: 'cmd', t: 'repo-ai verify --run' },
      d('verifying 1 selected test file(s) in the seatbelt sandbox, in a disposable copy of the working tree…'),
      d("  command: make test  [declared in the project's manifests, CI or docs]"),
      d('  isolated copy: 31 files (clone, 0.0s)'),
      trim('strategy line trimmed'),
      { k: 'pass', t: '  pass    tests/test_login.py (0.4s)' },
      trim('3 summary lines trimmed'),
      o(''),
      { k: 'pass', t: 'PASSED: every selected test passed (the full suite was not run)' },
      o('  1 selected test file(s) passed'),
      o('  source tree unchanged'),
      { k: 'warn', t: '  ! no runtime evidence: selection rests on static imports only (`repo-ai verify --record` records which code each test executes)' },
      trim('one more caveat trimmed'),
      o('evidence saved; `repo-ai evidence` shows whether it still covers the working tree.'),
      h('This covers only the tests that ran; it is not proof the change is correct.'),
    ],
  },
  {
    id: 'do',
    label: 'do --dry-run',
    summary: 'Plan a mission offline. No provider, no tests, no writes.',
    lines: [
      { k: 'cmd', t: 'repo-ai do "Reject emails with surrounding whitespace in login validation" --dry-run' },
      { k: 'warn', t: 'ASK_APPROVAL: External execution requires verified provider policy, explicit disclosure and budget authorization; planning only; trivial change classification refused unnecessary specialist fan-out' },
      h('Planning only; no provider or tests invoked.'),
      o('  app/auth/login.py: keyword match; named like the task; auth path'),
      o('  app/api/users.py: keyword match; auth path; imports login.py'),
      o('  web/src/components/LoginForm.tsx: keyword match; named like the task; auth path'),
      trim('3 more files trimmed'),
      o('Unknowns: static import graph only: dynamic imports, reflection, dependency injection, plugin registries and string-based routing are not visible'),
      o('Orchestration (trivial): merge_owner=controller'),
    ],
  },
  {
    id: 'agents',
    label: 'agents list',
    summary: 'Which agent CLIs are on PATH. Static check only; nothing is started.',
    lines: [
      { k: 'cmd', t: 'repo-ai agents list' },
      o('codex: PLANNING_ONLY | version not probed | auth UNKNOWN'),
      o('claude: PLANNING_ONLY | version not probed | auth UNKNOWN'),
      o('bob: PLANNING_ONLY | version not probed | auth UNKNOWN'),
      o('agy: PLANNING_ONLY | version not probed | auth UNKNOWN'),
      o('opencode: PLANNING_ONLY | version not probed | auth UNKNOWN'),
      o('opencode-acp: PLANNING_ONLY | version not probed | auth UNKNOWN'),
      h('No model was invoked. Installed executable does not establish authenticated runnable availability.'),
    ],
  },
];
