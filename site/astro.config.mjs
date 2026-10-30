// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// GitHub Pages project site: https://hxxtsxxh.github.io/repo-ai/
const SITE = 'https://hxxtsxxh.github.io';
const BASE = '/repo-ai';

export default defineConfig({
  site: SITE,
  base: BASE,
  trailingSlash: 'always',
  // No runtime network: no external fonts, scripts, analytics or prefetch to other origins.
  prefetch: false,
  integrations: [
    // Starlight adds @astrojs/sitemap itself when `site` is set; the sitemap covers
    // the landing page as well as the docs.
    starlight({
      title: 'repo-ai',
      description:
        'A local-first CLI: offline repository context, skeptical sandboxed change verification, and optional coding agents under frozen tests.',
      logo: {
        src: './src/assets/logo.svg',
        replacesTitle: false,
        alt: '',
      },
      favicon: '/favicon.svg',
      head: [
        { tag: 'link', attrs: { rel: 'icon', href: `${BASE}/favicon-32.png`, sizes: '32x32', type: 'image/png' } },
        { tag: 'link', attrs: { rel: 'apple-touch-icon', href: `${BASE}/apple-touch-icon.png` } },
        { tag: 'meta', attrs: { property: 'og:image', content: `${SITE}${BASE}/og.png` } },
        { tag: 'meta', attrs: { property: 'og:image:width', content: '1200' } },
        { tag: 'meta', attrs: { property: 'og:image:height', content: '630' } },
        { tag: 'meta', attrs: { property: 'og:image:alt', content: 'repo-ai: context before the change, evidence after it. A pass means the tests that ran observed a pass.' } },
        { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: `${SITE}${BASE}/og.png` } },
        { tag: 'meta', attrs: { name: 'theme-color', content: '#0e1211' } },
        {
          // Make horizontally scrollable code blocks and tables reachable by keyboard
          // (WCAG 2.1.1; axe "scrollable-region-focusable"), only when they actually scroll.
          tag: 'script',
          // Also makes the search button's accessible name include its visible shortcut hint
          // (WCAG 2.5.3 Label in Name; axe "label-content-name-mismatch"), e.g. "Search Ctrl K".
          content: `(()=>{const s='.sl-markdown-content pre,.sl-markdown-content table';function f(){document.querySelectorAll('button[data-open-modal]').forEach(b=>{const k=b.querySelector(':scope > kbd');const t=k?Array.from(k.querySelectorAll('kbd')).map(x=>x.textContent.trim()).join(' '):'';if(t&&getComputedStyle(k).display!=='none')b.setAttribute('aria-label','Search '+t)});document.querySelectorAll(s).forEach(e=>{if(e.scrollWidth>e.clientWidth+1){if(!e.hasAttribute('tabindex'))e.setAttribute('tabindex','0');e.dataset.riScroll='1'}else if(e.dataset.riScroll){e.removeAttribute('tabindex');delete e.dataset.riScroll}})}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',f);else f();let t;addEventListener('resize',()=>{clearTimeout(t);t=setTimeout(f,150)})})();`,
        },
      ],
      customCss: ['./src/styles/tokens.css', './src/styles/starlight.css'],
      disable404Route: true,
      lastUpdated: false,
      credits: false,
      pagefind: true,
      editLink: undefined,
      tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 3 },
      components: {
        // Adds a "Home" link and the source-availability label next to the search box.
        SocialIcons: './src/components/docs/HeaderLinks.astro',
      },
      sidebar: [
        {
          label: 'Start here',
          items: [
            { label: 'Introduction', slug: 'docs' },
            { label: 'Install', slug: 'docs/install' },
            { label: 'Quickstart (no agent)', slug: 'docs/quickstart' },
          ],
        },
        {
          label: 'Evidence',
          items: [
            { label: 'Verify a change', slug: 'docs/verify' },
            { label: 'Requirement coverage', slug: 'docs/coverage' },
            { label: 'CI recipe', slug: 'docs/ci', badge: { text: 'Example', variant: 'note' } },
          ],
        },
        {
          label: 'Agents (optional)',
          items: [
            { label: 'Missions with agents', slug: 'docs/missions', badge: { text: 'Experimental', variant: 'caution' } },
            { label: 'Tournaments & shortlist', slug: 'docs/tournaments', badge: { text: 'Experimental', variant: 'caution' } },
            { label: 'Handoff', slug: 'docs/handoff', badge: { text: 'Experimental', variant: 'caution' } },
            { label: 'Providers', slug: 'docs/providers' },
          ],
        },
        {
          label: 'Trust',
          items: [
            { label: 'Security & privacy', slug: 'docs/security' },
            { label: 'Evaluation & methodology', slug: 'docs/evaluation' },
            { label: 'Status matrix', slug: 'docs/status' },
          ],
        },
        {
          label: 'More',
          items: [
            { label: 'Skills', slug: 'docs/skills' },
            { label: 'Troubleshooting', slug: 'docs/troubleshooting' },
            { label: 'CLI reference', slug: 'docs/reference/cli' },
            { label: 'Changelog', slug: 'docs/changelog' },
            { label: 'Contributing', slug: 'docs/contributing' },
          ],
        },
      ],
    }),
  ],
});
