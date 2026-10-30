# verify-eval artifacts: what is kept, where, and why

**Audit (2026-10-22).**
- **Before:** `results/raw/` as committed at `f34818d` held 147 JSON files, 37.6 MB. It was 98% of
  PR #23's added lines.
- **Byte-identical files:** none. Some `selections-posthoc*.json` pairs have the same size, but
  their latencies differ.
- **What the bulk was:** `changes.json` (28.9 MB, 77%). For every change it held the **full
  content** of each changed file, which made it a third-party source snapshot.

## Layout

| Path | What | Needed for |
|---|---|---|
| `PROTOCOL.md`, `FREEZE.md`, `corpus.json` | protocol, freezes, pinned corpus commits | reproducing and auditing every set |
| `harness.py`, `tables.py`, `archive.py` | harness, table generator, archive tool | reproducing |
| `results/*-score*.json`, `results/*-tables*.md` | per-set scores and tables, frozen and post-hoc (labelled) | the reported numbers (`RESULTS.md`) |
| `results/zero-config-commands.json` | command-inference measurement | the zero-config claim |
| `results/archives/<name>.tar.xz` | **raw per-project outputs**, compressed | re-scoring without re-running the containers |
| `results/archives/<name>.manifest.json` | SHA-256 of the archive and of every original file, and the source commit | integrity and provenance |

**What the raw files are, per project:**
- `setup.json`: pinned commit and test universe.
- `baseline.json`: per-file baseline status and durations.
- `changes.json`: generated changes.
- `truth.json`: the affected test files per change.
- `selections*.json`: what each method selected, with confidence and latency.

`changes.json` can be regenerated from `corpus.json` and the seeded generator. It is archived
anyway, so the evaluated changes stay immutable.

## Integrity and provenance

- **Uncompressed originals:** `results/archives/raw-2026-10-21.tar.xz` holds `results/raw/`
  exactly as committed at `f34818db407b`. Those originals stay in git history at that commit.
  Nothing was rewritten or force-pushed.
- **Manifest:** `raw-2026-10-21.manifest.json` lists all 147 files with their SHA-256. `pack`
  verified the round trip, and a byte-for-byte `diff -r` against the originals passed before
  `results/raw/` was removed from the tree.
- **Engine commits of each frozen result:**

  | Set | Engine commit |
  |---|---|
  | dev and held-out | `d9695d3` |
  | held-out-2 | `280c03a` |
  | post-hoc | `edef2ae`, `2dff74c` |

- **Corpus commits:** pinned in `corpus.json`.

```sh
python benchmarks/verify-eval/archive.py verify benchmarks/verify-eval/results/archives/*.tar.xz
python benchmarks/verify-eval/archive.py unpack \
    benchmarks/verify-eval/results/archives/raw-2026-10-21.tar.xz /tmp/vev/out
mkdir -p /tmp/vev/repos   # scoring reads only out/; no clones needed
VEV_WORK=/tmp/vev python benchmarks/verify-eval/harness.py score --set heldout
# -> verify-runtime no_miss_rate 0.993, suite_time_share 0.435: the frozen held-out result
```

**New raw output:**
- The harness writes it to `$VEV_WORK/out/`, outside the repository.
- `results/raw/` is git-ignored.
- A finished evidence set is added only as a new archive. `archive.py pack` refuses to overwrite
  an existing one.

## Held-out-3 and post-hoc selections (2026-10-22)

`results/archives/raw-2026-10-22.tar.xz` (82 files, 76.9 MB → 1.1 MB, verified) holds:
- **The held-out-3 raw outputs:** `setup`, `baseline`, `changes`, `truth`,
  `selections.json` (**frozen**, engine `75679e9`), `testmap.json` (runtime
  evidence) and `image.json`.
- **`selections-posthoc3.json` for every set** (engine `a8653bc` and later,
  **post-hoc**).

**Uncompressed, in the tree:**
- the held-out-3 selection records: `results/heldout3/`;
- image digests: `results/heldout3/images/`;
- the Vitest control: `results/heldout3/control-found-plan.json`;
- scores, tables, and the zero-config, actual-time and e2e results:
  `results/*.json`, `results/*.md`.

## Never shipped

- `pyproject.toml` excludes everything under `benchmarks/` from the sdist except
  `benchmarks/tasks/`. That is the offline eval suite `repo-ai eval --offline` runs, and the
  wheel force-includes it as `repo_ai/_evalsuite`.
- CI fails if a built sdist or wheel contains `verify-eval`, `sealed-v2`, `authoring` or any
  other benchmark data.

## Held-out-4 and the execution measurements (2026-10-22)

`results/archives/raw-2026-10-22-heldout4.tar.xz` (59 files, 7.7 MB → 415 kB, verified) holds the
held-out-4 raw outputs:
- **Per project** (frozen engine `ccb0622`): `setup`, `baseline`, `image`, `testmap`, `changes`,
  `truth` and `selections`.
- **chardet:** `setup` and `baseline` only, from before its replacement.

They were never committed uncompressed. Its manifest names the commit of the first result
(`826143d`).

**Uncompressed, in the tree:**
- **Selection records:**
  - `results/heldout4/selection*.json` (the frozen search, Amendment 3b's searches, the test scripts
    read);
  - `results/heldout4/images.json`.
- **Scores and tables:** `results/heldout4-score-frozen-ccb0622.json`,
  `results/heldout4-tables-frozen-ccb0622.md`.
- **Zero-config:** `results/zeroconfig-heldout4-ccb0622.json` (frozen) and
  `results/zeroconfig-posthoc-*.json` (post-hoc).
- **Waiting time:** `results/wallclock-summary.json`, the per-project summaries behind
  `WALLCLOCK.md`, for both engines.
  - The full per-run records (every `verify --run`, with its verdict, processes, timing and
    integrity digest) are in `results/archives/wallclock-2026-10-22.tar.xz`: 5 files,
    802 kB → 18 kB, verified.
  - They were committed uncompressed at `2af29ab` and are still in that commit.

| Set | Engine commit |
|---|---|
| held-out-4 (selection, zero-config, execution) | `ccb0622` (frozen) |
| development execution | `43f7b22` (new), `cf56523` (previous) |
| post-hoc after held-out-4 | `8498671`, `3b57a88` |
