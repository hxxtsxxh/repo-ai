// Accessibility and layout QA over the built site.
//
// For every built page, in dark and light themes:
//   * axe-core (WCAG 2.0/2.1/2.2 A and AA rules) must report 0 violations;
//   * at 390 px and 1440 px wide; at 390 px the page must not scroll horizontally.
// Also checks that no request leaves the local server (zero third-party requests).
//
// Exit code 1 on any violation. Writes qa/a11y-report.json.
import { chromium } from 'playwright';
import { AxeBuilder } from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startServer, allPages, BASE } from './serve.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const { origin, close } = await startServer();
const pages = await allPages();
const browser = await chromium.launch();
const report = [];
let violations = 0;
let overflow = 0;
const foreign = new Set();

for (const [theme, width] of [['dark', 390], ['light', 390], ['dark', 1440], ['light', 1440]]) {
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 }, colorScheme: theme, reducedMotion: 'reduce' });
  await context.addInitScript((t) => {
    try {
      localStorage.setItem('starlight-theme', t);
    } catch {}
  }, theme);
  context.on('request', (req) => {
    const u = new URL(req.url());
    if (u.origin !== origin && !u.protocol.startsWith('data') && !u.protocol.startsWith('blob')) foreign.add(req.url());
  });
  const page = await context.newPage();
  for (const p of pages) {
    const url = `${origin}${BASE}${p}`;
    await page.goto(url, { waitUntil: 'load' });
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
      .analyze();
    const v = results.violations.map((x) => ({
      id: x.id,
      impact: x.impact,
      help: x.help,
      nodes: x.nodes.slice(0, 5).map((n) => ({ target: n.target.join(' '), summary: n.failureSummary })),
    }));
    violations += v.length;
    const widths = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    const over = width === 390 && widths.scroll > widths.client;
    if (over) overflow++;
    report.push({ page: p || '/', theme, width, violations: v, overflowAt390: over, widths });
    const flag = v.length || over ? '✗' : '✓';
    console.log(`${flag} [${theme} ${width}] /${p}  axe: ${v.length} violation(s)${over ? `  OVERFLOW ${widths.scroll}>${widths.client}` : ''}`);
    for (const x of v) {
      console.log(`    - ${x.id} (${x.impact}): ${x.help}`);
      for (const n of x.nodes) console.log(`        ${n.target}`);
    }
  }
  await context.close();
}

await browser.close();
await close();
mkdirSync(join(root, 'qa'), { recursive: true });
writeFileSync(join(root, 'qa', 'a11y-report.json'), JSON.stringify({ violations, overflow, foreignRequests: [...foreign], report }, null, 2));
console.log(`\na11y: ${pages.length} pages × 2 themes × 2 widths; ${violations} axe violation(s); ${overflow} page(s) overflow at 390px; ${foreign.size} third-party request(s).`);
for (const f of foreign) console.log(`  third-party request: ${f}`);
process.exit(violations || overflow || foreign.size ? 1 : 0);
