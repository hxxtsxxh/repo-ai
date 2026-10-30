# repo-ai website

The landing page and documentation for repo-ai, published as a GitHub Pages
project site at <https://hxxtsxxh.github.io/repo-ai/> (base path `/repo-ai`).

- **Stack:** [Astro](https://astro.build) 7 with [Starlight](https://starlight.astro.build) 0.42.
  Exact versions are pinned in `package.json` and locked in `package-lock.json`.
- **Landing page:** `src/pages/index.astro`, a custom Astro page with its own layout
  (`src/layouts/Landing.astro`) and styles (`src/styles/landing.css`).
- **Docs:** Markdown and MDX in `src/content/docs/`, served under `/repo-ai/docs/`.
  `src/content.config.ts` prefixes every entry with `docs/`, so
  `src/content/docs/verify.md` becomes `/repo-ai/docs/verify/`. The sidebar is in
  `astro.config.mjs`.
- **Search:** Pagefind, built into Starlight and generated at build time.
- **No runtime network.** System font stacks, no CDNs, no analytics, no trackers.
  `npm run check:links` fails the build if a page loads anything from another origin.

## Release facts in one place

`src/config.ts` holds the facts that change with a release:

```ts
export const site = {
  version: '0.9.0',
  pypiPublished: false, // true: show `pipx install repo-ai` / `python -m pip install repo-ai`
  githubRepo: 'https://github.com/hxxtsxxh/repo-ai',
  repoPublic: false,    // true: render links to the source; false: "Source: coming soon"
  factsAsOf: '2026-10-29',
};
```

The install command on the landing page and the Install docs page (`<InstallCommand />`)
both read it. When the release reaches PyPI, or the repository goes public, flip the flag
and rebuild. Nothing else needs editing.

The provider and platform matrix, the evaluation numbers and the terminal walkthrough
(`src/data/transcripts.ts`) are written by hand from the repository's own records
(`README.md`, `docs/STATUS.md`, `benchmarks/*/RESULTS.md`) and from real CLI output.
Update them, and `factsAsOf`, when those change. Never add output the CLI did not print.

## Build and preview

Requires Node.js 22.23.4 or newer (CI uses 24.19.0).

```sh
cd site
npm ci
npm run build      # writes dist/
npm run preview    # serves dist/ at http://localhost:4321/repo-ai/
npm run dev        # live-reloading dev server
```

Astro 7 may start `preview` as a background process when there is no interactive
terminal; stop it with `npx astro preview stop`.

## Quality checks

```sh
npx playwright install chromium   # once, for the browser-based checks
npm run qa           # build + link check + axe accessibility check
npm run qa:screens   # screenshots into qa/screenshots/ (gitignored)
```

- `npm run check:links` (`scripts/check-links.mjs`): every internal `href`/`src`
  in `dist/` must resolve under the `/repo-ai/` base, every `#fragment` must
  match an `id`, and no page may load a third-party subresource.
- `npm run qa:a11y` (`scripts/a11y.mjs`): axe-core (WCAG 2.x A/AA plus best
  practices) on every built page, in light and dark themes, at 390 px and
  1440 px. It also fails on horizontal overflow at 390 px and on any request that
  leaves the local server. The report is written to `qa/a11y-report.json`.
- `npm run qa:screens` (`scripts/screenshots.mjs`): full-page screenshots of the
  landing page and three docs pages at 390×844, 768×1024 and 1440×900, light and dark.

The browser checks serve `dist/` with `scripts/serve.mjs`, a small static server
that mimics GitHub Pages under the base path. They do not need `npm run preview`.

## Brand assets

- `src/assets/logo.svg` is the mark, used in both headers. `public/favicon.svg` is a copy.
- `npm run og` (`scripts/render-og.mjs`) renders `public/og.png` (the 1200×630 social
  card), `public/favicon-32.png` and `public/apple-touch-icon.png` with resvg and the
  system's fonts. The PNGs are committed, so the site build does not run this step.

## Deploy

`.github/workflows/pages.yml` builds `site/` and deploys `site/dist` with the
official Pages actions. It runs on `workflow_dispatch` and on pushes to `main` that touch
`site/**` or the workflow itself.

One-time setup: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
GitHub Pages for a private repository needs a plan that supports it.

Notes:
- `public/robots.txt` is served at `/repo-ai/robots.txt`. Crawlers only read
  `robots.txt` at the domain root, so it is informational for a project site. The
  sitemap (`/repo-ai/sitemap-index.xml`) is linked from every page.
- `src/pages/404.astro` becomes `dist/404.html`, which GitHub Pages serves for
  missing paths under the site.
- The CLI reference page (`src/content/docs/reference/cli.md`) is a placeholder whose
  body is generated from `repo-ai --help` by a separate script.
