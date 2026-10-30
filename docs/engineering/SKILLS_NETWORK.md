# Skill Intelligence Network: diagnosis and the safe-autopilot milestone

Engineering notes for maintainers. User-facing documentation stays in
[../SKILL_NETWORK.md](../SKILL_NETWORK.md), [../CAPABILITIES.md](../CAPABILITIES.md) and
[../STATUS.md](../STATUS.md).

## 1. Why the fresh validations failed

**Source of the numbers.** The raw protocols and results live under `docs/research/`. That directory is
excluded from the public export (`scripts/public_export.py`) and from the sdist. The numbers below are
therefore copied from the public record: `docs/STATUS.md`, `CHANGELOG.md` (0.8 section),
`docs/CAPABILITIES.md` and `docs/SKILL_NETWORK.md`. The causes come from those documents and from
reading the shipped code (`capdiscovery.py`, `capselect.py`, `pluginvet.py`, `firewall.py`). They were
not re-derived from the per-case result files, which this checkout does not contain.

### 1.1 Capability discovery (`capabilities recommend`, `candidates` / `select`): FAIL

Corpus C was a fresh 120-task corpus with a protocol frozen beforehand, run once.

| Metric | Result | Gate or reference |
|---|---|---|
| top-3 recall | **0.385** | gate **0.80** |
| shortlist recall@6 | 0.736 | none |
| top-3 precision | 0.712 | none |
| constraint-forbidden items in the top 3 | **5** | 0 |
| stated constraints detected from the task text | 9 of 18 | none |
| baselines (top-3 recall) | lexical 0.088, repository-only 0.286 | — |
| earlier matcher, two 60-task corpora | precision 0.91–0.93, recall 0.43–0.58 | — |

**Causes.**

1. **The matcher is built for precision.** An intent fires only when two or three lexicon facets meet
   within one clause (a 12-token window) or across two adjacent clauses. A single ambiguous word never
   fires, negated mentions are dropped, and repository signals can only amplify a need the text already
   supports (`capdiscovery.py` docstring, steps 2–6). When a task names its need in words outside the
   frozen lexicon of about 40 facets, nothing fires, and the result is "nothing recognised".
2. **Ranking and cut-off, not only detection.** Recall@6 (0.736) is almost twice top-3 recall (0.385),
   so for about a third of the tasks the right capability was found and then ranked below the top 3.
   Partial-credit candidates can only reach the `consider` tier (`capselect.TIERS`), never the top 3.
3. **Constraints were inferred, not enforced.** Constraints written in prose ("offline", "don't run
   anything") were detected for 9 of 18 tasks. Undetected ones did not gate anything, which is how 5
   forbidden recommendations reached the top 3. `--deny` (always enforced, and it only tightens) was
   added after Corpus C. Tests cover it; no fresh corpus has evaluated it.
4. **No further tuning.** Tuning stopped after three unsuccessful passes, and Corpus C is spent. A
   claim of improvement needs a new, independently labelled corpus.

### 1.2 Plugin inspection (`pluginvet`, through `skills vet` and `inventory`): FAIL

The protocol was preregistered: 44 cases, with the analyser frozen.

| Metric | Result |
|---|---|
| benign cases blocked (false alarms) | **12 of 42** |
| executable-resolution coverage | **0.25** (0.43 after a post-hoc corrective pass, still a fail) |
| critical or unresolvable case reported eligible | 0 |
| attack detection | **not freshly validated**: the synthetic attacks could not be produced |

**Causes.**

1. **Pattern rules matched text that only talks about danger.** Most false alarms came from quoted
   prohibitions ("never run `curl … | sh`") and from detection regexes that themselves contain the
   dangerous strings. The negation check did not cover every phrasing. One narrow fix followed:
   Markdown emphasis (`**DO NOT**`) no longer defeats negation. No rule was loosened in any other way.
2. **Static resolution cannot follow most real commands.** Hooks and servers usually start through
   package runners (`npx`, `uvx`, `docker`), project runners (`npm run`, `make`), computed paths,
   binaries or minified bundles. `pluginvet` marks each of these `dynamic-unknown` by design, so the
   coverage of executable resolution stayed low.
3. **Containment, not repair.** A plugin is never reported `eligible`: `review` is the best it gets.
   repo-ai never installs or enables a plugin.

### 1.3 Third-party skill effectiveness: not demonstrated

No third-party skill has been shown to help in a controlled trial. Recorded agent runs show 0 skill
invocations in 212 runs (STATUS.md, "Agent benefit"). Trials (`skills benchmark` and `tournament`) are
paid model runs. None was run for this milestone.

## 2. What this milestone adds

The milestone extends the existing pipeline (profile → radar → quarantine → firewall → recommend →
approve and install → trial → canary and promote). It adds no parallel system.

### 2.1 Autonomy policy (`src/repo_ai/autonomy.py`)

`repo-ai skills policy [show | set LEVEL | revoke]`. The level is stored per checkout in
`registry.machine_dir(root)/skills-policy.json`, outside the repository, next to the radar state and
the capability approvals. A file committed under `.repo-ai/` is never read, so a clone cannot grant
itself `SAFE_AUTO`. If `REPO_AI_HOME` points inside the repository, the stored policy is ignored and
writes are refused.

| Level | Network discovery | Install with a per-hash approval | Autopilot | Live trials |
|---|---|---|---|---|
| `OFFLINE` | refused | local sources only | nothing | refused |
| `DISCOVER_ONLY` | allowed | refused | nothing | refused |
| `PROPOSE` (default) | allowed | allowed | proposes | allowed (`--max-cost-usd`) |
| `SAFE_AUTO` | allowed | allowed | installs **inert** skills only | allowed |
| `TRIAL` | allowed | allowed | proposes a trial for inert skills | allowed |
| `MANUAL_ONLY` | allowed | full 64-hex hash only | nothing | allowed |

- **Raising** to `SAFE_AUTO` or `TRIAL` is refused (exit 5) when any agent, hook or CI marker
  (`capabilities.AGENT_ENV`) is set, or when stdin is not a TTY.
- **Lowering** and `revoke` are always allowed.
- **`revoke`** returns to `PROPOSE` and removes, byte-exactly, every skill that the policy installed
  (`approved_by: policy:*`) rather than a human.
- **History:** every change is kept in the file (the last 20).

### 2.2 Five object kinds and inertness (`src/repo_ai/capbundle.py`)

`classify()` separates `skill`, `plugin` (`.claude-plugin/`, `hooks/`, `bin/`, `monitors/`,
`settings.json`, `.lsp.json`) and `mcp_server` (`.mcp.json`, `mcp.json`, `smithery.yaml`, MCP SDK
dependencies). `registry_objects()` lists `provider_adapter` (the five provider CLIs) and `static_tool`
(capability adapters such as ruff).

- **Skills only.** Only `skill` is installable through `skills install`.
- **Never installed:** `plugin` and `mcp_server`.
- **Per-capability approval:** `provider_adapter` and `static_tool` keep their own flows.

`assess()` computes `inert` structurally, on top of the firewall:

- **File set:** only `SKILL.md`, plus plain-text licence files. Any other file is a surface: scripts,
  references, binaries.
- **Modes:** no executable bit and no shebang.
- **Size:** SKILL.md is at most 32 KiB, with no line over 2,000 characters.
- **Front matter:** only `name`, `description`, `license`, `metadata`, `argument-hint` and
  `disable-model-invocation`, in the strict YAML subset.
- **Characters:** no bidi, zero-width, tag, BOM or control characters, and no HTML comments.
- **Content:** no URLs, no network-executing commands, no MCP references, no account or credential
  cues, no permission or settings changes, no decode-and-run constructs, and no risky commands
  (`skillcheck.RISKY_RE`).
- **Firewall:** verdict `eligible` and complete, with no finding of medium severity or above, and none
  of the low or info findings that imply execution, network use or permission changes.

`eligible` alone never makes a skill inert. A test pins this: a skill that asks for an access token is
`eligible` and not inert.

### 2.3 Bundles, translators and manifests

- **`CapabilityBundle`:** the reviewed bytes, pinned to the full content hash.
  - `from_quarantine` refuses a listing whose hash differs from the pin.
  - It also refuses a quarantined file whose bytes changed after inspection.
- **Translators:**

  | Host | Directory | Support |
  |---|---|---|
  | `claude-code` | `.claude/skills/<name>/` | `INSTALL_TARGET` (the existing portfolio target) |
  | `codex` | `.agents/skills/<name>/` | `CAPABILITY_EXPORT_ONLY` |
  | `gemini-cli` | `.gemini/skills/<name>/` | `CAPABILITY_EXPORT_ONLY` |
  | `antigravity` | `.agents/skills/<name>/` | `CAPABILITY_EXPORT_ONLY` |
  | `ibm-bob` | `.bob/skills/<name>/` | `CAPABILITY_EXPORT_ONLY` |

  - Codex: codex-cli 0.165.0 binary strings name `.agents/skills` as a repository skills root.
  - Gemini CLI: the bundled docs of gemini-cli 0.65.0.
  - Antigravity: agy binary strings (`{workspace}/.agents/skills/{skill_name}/SKILL.md`).
  - IBM Bob: repo-ai's own Bob notes (`bobsetup.py`).
  - These paths come from local inspection only: no login, no model call. **No host was observed
    loading a skill**, so every entry reports `runtime_observed: false`.
- **Owned and permission-neutral:**
  - Each SKILL.md gets `<!-- repo-ai:managed kind=capability-bundle bundle=… sha=… -->` after its front
    matter, so a hand edit makes the file the user's (`fsutil.managed_state`).
  - Front matter is reduced to `firewall.SAFE_FRONT_KEYS`.
  - Files are written non-executable, and nothing is written outside `<skills_dir>/<name>/`.
  - The adapter's generic managed-file writer and `skills.collision()` treat a `capability-bundle`
    marker as foreign. A generated or curated skill with the same name can therefore never replace a
    third-party skill.
- **Conflicts:** an existing file repo-ai does not own, a file edited since repo-ai wrote it, a
  symlinked path or a foreign directory each refuse the **whole** install, and nothing is written.
  Hosts that share `.agents/skills` (Codex and Antigravity) receive identical bytes. The shared path
  stays in place until the last of those hosts is uninstalled.
- **Manifest** (`machine_dir/bundles/<name>.json`, outside the repository, so a clone cannot forge it):
  - For each path: the bytes there before the first install (always absent today, because conflicts
    refuse), and the sha256 of what repo-ai wrote.
  - The directories repo-ai created.
  - On load, paths are re-validated against the host's `<skills_dir>/<name>/` and its ancestors.
- **Uninstall** restores the baseline only for files still byte-identical to what repo-ai wrote, and
  removes only directories repo-ai created, when empty. Translation is deterministic, so a rollback
  writes exactly the bytes the earlier install wrote.
- **Portfolio integration** (`portfolio.py`):
  - `install`, `enable`, `rollback`, `disable` and `repo-ai uninstall` all go through the bundle and
    the manifest.
  - Skills installed before manifests existed fall back to the lockfile's per-file hashes, the old
    behaviour.
  - Lock entries gain `hosts`, `kind`, `inert` and `approved_by`.

### 2.4 CLI (skills parser only)

- **`skills policy [show|set LEVEL|revoke] [--json]`:**
  - Exit 0 on success.
  - Exit 2 on a usage error or an unknown level.
  - Exit 5 when raising the level is refused (no human terminal).
- **`skills autopilot [names…] [--dry-run] [--online] [--json]`:** applies the policy to the
  candidates vetted by the last discovery.
  - Without names it acts only on candidates recommended for an evidence-backed gap.
  - Under `SAFE_AUTO`, before installing it re-fetches the candidate, re-hashes it against the vetted
    pin, re-inspects it and re-assesses it.
  - Exit 4 when a candidate's content changed after vetting. Nothing is installed in that case.
- **`skills install … --host claude-code,codex,…`:** the default is the installed version's hosts, or
  `claude-code` for a new skill. A host dropped on an upgrade is uninstalled.
- **`skills install --dry-run`:** prints the unified diff and the conflicts. Exit 1 when there is a
  conflict.
- **Policy gates in existing actions:** `OFFLINE` refuses `discover --online`, `updates`, `vet <URL>`,
  remote installs and live trials. `DISCOVER_ONLY` refuses installs and live trials. `MANUAL_ONLY`
  requires the full hash.

## 3. Not done, or not verified

- **Host loading.** Nothing shows that any host loads a skill from these directories at runtime. This
  includes Claude Code for this change: it was not re-observed. Codex, Gemini CLI, Antigravity and Bob
  remain `CAPABILITY_EXPORT_ONLY`. The `.agents/skills` and `.gemini/skills` precedence in Gemini CLI
  was not exercised.
- **User-level directories.** Personal skill directories (`~/.codex/skills`, `~/.gemini/skills`) are
  deliberately not targets: repo-ai writes only inside the project.
- **Discovery tuning.** The failed discovery and plugin validations are unchanged. No matcher or rule
  was tuned, and no new corpus exists.
- **Measured precision of `inert`.** `inert` is a conservative structural rule: it refuses anything
  with a URL, a risky word or an extra file. Its precision on real skills was not measured, and it will
  refuse many harmless skills.
- **Trials.** No paid trial was run, so third-party benefit is still not demonstrated.
- **Upgrades from 0.9.0.** A third-party skill installed before this change has no manifest. Its
  removal still uses the lockfile hashes, and it leaves parent directories in place.
- **`repo-ai uninstall`.** It removes bundle files through the manifest but does not delete the
  manifest files themselves in the machine directory. A stale manifest only claims files whose bytes
  still match what repo-ai wrote.
