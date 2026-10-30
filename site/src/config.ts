/**
 * Single source of truth for release facts the site renders.
 *
 * Flip `pypiPublished` once `repo-ai` is on PyPI, and `repoPublic` once the
 * GitHub repository is public. Nothing else in the site needs to change.
 */
export const site = {
  /** The release the install commands point at. */
  version: '0.9.0',
  /** false: install the wheel from the GitHub release. true: pipx / pip from PyPI. */
  pypiPublished: true,
  /** Canonical repository URL. Only rendered as a link when `repoPublic` is true. */
  githubRepo: 'https://github.com/hxxtsxxh/repo-ai',
  /** false: no "view source" / star-style calls to action; neutral wording instead. */
  repoPublic: true,
  /** Date the provider/platform matrix and evaluation facts were last checked. */
  factsAsOf: '2026-10-29',
} as const;

export const wheelName = `repo_ai_cli-${site.version}-py3-none-any.whl`;
export const wheelUrl = `${site.githubRepo}/releases/download/v${site.version}/${wheelName}`;

/** The primary install command for the current distribution state. */
export const installCommand = site.pypiPublished
  ? 'pipx install repo-ai-cli'
  : `python -m pip install ${wheelUrl}`;

/** Alternative commands shown under the primary one. */
export const installAlternatives: { label: string; command: string }[] = site.pypiPublished
  ? [{ label: 'pip', command: 'python -m pip install repo-ai-cli' }]
  : [{ label: 'pipx, from the same wheel', command: `pipx install ${wheelUrl}` }];

export const installNote = site.pypiPublished
  ? `repo-ai ${site.version} is published on PyPI as repo-ai-cli; the command is repo-ai.`
  : `repo-ai ${site.version} is not on PyPI yet. The command installs the wheel attached to the GitHub release; pip still fetches the one runtime dependency (pathspec, plus tomli on Python 3.10) from PyPI.`;

export const sourceLabel = site.repoPublic ? 'Source on GitHub' : 'Source: coming soon';
