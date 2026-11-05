# Releasing and rolling back

How a repo-ai version reaches PyPI and GitHub, how it is checked after publication, and what to do when a published
version is bad. The workflow is `.github/workflows/release.yml`; the record of each release is in
`docs/engineering/FINAL_REPORT.md` and `docs/engineering/ACCEPTANCE.json` (gate C20).

## Releasing

1. **Release PR.** Bump the version in `src/repo_ai/__init__.py`, `.claude-plugin/marketplace.json`,
   `integrations/claude-plugin/.claude-plugin/plugin.json` and `integrations/claude-plugin/README.md`; rename the
   `CHANGELOG.md` "Unreleased" heading to the version; add a condensed entry to `site/src/content/docs/changelog.md`;
   run `python scripts/site_facts.py`; add a row to `docs/engineering/QUEUE.md`. Merge only after the full CI matrix
   (`gh workflow run ci.yml --ref <branch>`, macOS included) and the PR's required checks pass.
2. **Tag.** Push an annotated `vX.Y.Z` tag at the merge commit. The owner approves every tag push.
3. **Workflow.** The tag starts `release.yml`: build the wheel and sdist (refusing a tag that differs from the source
   version), a CycloneDX SBOM and `SHA256SUMS`; install and smoke-test the wheel on Ubuntu, macOS and Windows; publish
   to PyPI by Trusted Publishing (environment `pypi`) with build-provenance attestations; then create the GitHub
   release with the same files.
4. **Verify after publication** (and record it in a record PR):
   - download the files from PyPI and from the GitHub release, check they are byte-identical and that
     `SHA256SUMS` matches;
   - build from the tag (`git archive vX.Y.Z`) and rebuild the wheel from the PyPI sdist; both must equal the
     published wheel;
   - `gh attestation verify <file> -R hxxtsxxh/repo-ai` for the wheel and the sdist;
   - a fresh virtualenv: `pip install repo-ai-cli==X.Y.Z`, `repo-ai --version`, and a short smoke run;
   - the site: every sitemap URL returns 200, a missing page returns 404, the changelog shows the version;
   - `python scripts/site_facts.py --record-pypi` (network) so the site's release facts move to the version.

## Rolling back

Published files and tags are immutable: a bad release is never deleted, re-tagged or overwritten.

1. **Assess.** Reproduce the problem on the published wheel. If it is a security issue, follow `SECURITY.md`
   (private advisory) before saying anything in public.
2. **Yank on PyPI** (project owner, pypi.org → repo-ai-cli → the version → Options → Yank) when installing it would
   harm users. A yanked version is skipped by `pip install repo-ai-cli` but stays installable when pinned exactly,
   so existing pins keep working.
3. **Mark the GitHub release.** Edit its notes to say the version is withdrawn and which version replaces it; do not
   delete the release or its tag.
4. **Ship a fix forward** as the next patch version through the normal process above. If the fix is not ready, a
   patch release that reverts the faulty change is the rollback.
5. **Record it.** A `CHANGELOG.md` entry in the fixing version names the withdrawn version and why; the release row in
   `docs/engineering/QUEUE.md` and gate C20 in `ACCEPTANCE.json` get the observation.

Users who already installed a bad version upgrade with `pip install -U repo-ai-cli` (or `pipx upgrade repo-ai-cli`).
