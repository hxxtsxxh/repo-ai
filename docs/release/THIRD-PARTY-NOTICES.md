# Bundled evaluation sources and notices

The wheel includes `benchmarks/tasks` under `repo_ai/_evalsuite` so offline evaluation works after
installation. The original synthetic `py-shop`, `ts-workspace` and `java-ledger` fixtures use repo-ai's
MIT license. Upstream snapshots retain separate notices:

| Snapshot | Source recorded in bases.json | License file retained in both artifacts |
|---|---|---|
| oss-markdown | Python-Markdown/markdown @ b41e0aaf | `bases/oss-markdown/LICENSE.md` — BSD-3-Clause |
| oss-pyflakes | PyCQA/pyflakes @ f0a8b981 | `bases/oss-pyflakes/LICENSE` — MIT |
| oss-cachetools | tkem/cachetools @ 6f23e2a7 | `bases/oss-cachetools/LICENSE` — MIT |
| oss-simplejson | simplejson/simplejson @ 9950b7e5 | `bases/oss-simplejson/LICENSE.txt` — MIT or AFL-2.1, both texts retained |
| oss-bottle | bottlepy/bottle @ 8ec5fe29 | `bases/oss-bottle/LICENSE` — MIT |
| oss-tomli | hukkin/tomli @ 43a86ade | `bases/oss-tomli/LICENSE` — MIT |
| toml-test data inside tomli | TOML authors, as vendored by tomli | `bases/oss-tomli/tests/data/{valid,invalid}/_external/toml-test/LICENSE` — MIT |

Paths above are relative to the evaluation suite in each artifact. `bases.json` records the upstream
URLs; individual files retain their embedded notices. The inventory checks that these notice files
ship unchanged. It is not a claim that every third-party source header received a legal review.

The original README's statement that all code was synthetic was incorrect after the upstream snapshots
were added; it has been corrected. These sources are evaluation fixtures, not imported runtime
dependencies. The sealed ProofLab certification data, research directories and authoring material are
excluded from release artifacts.
