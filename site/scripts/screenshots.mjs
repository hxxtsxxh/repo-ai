// Full-page screenshots of the landing page and three docs pages at phone, tablet
// and desktop widths, in light and dark themes. Output: qa/screenshots/ (gitignored).
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { startServer, BASE } from './serve.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, 'qa', 'screenshots');
mkdirSync(out, { recursive: true });

const pages = [
  ['landing', ''],
  ['docs-quickstart', 'docs/quickstart/'],
  ['docs-verify', 'docs/verify/'],
  ['docs-providers', 'docs/providers/'],
];
const viewports = [
  [390, 844],
  [768, 1024],
  [1440, 900],
];

const { origin, close } = await startServer();
const browser = await chromium.launch();
let n = 0;
let overflow = 0;
for (const theme of ['light', 'dark']) {
  for (const [w, h] of viewports) {
    const context = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: theme, reducedMotion: 'reduce', deviceScaleFactor: 1 });
    await context.addInitScript((t) => {
      try {
        localStorage.setItem('starlight-theme', t);
      } catch {}
    }, theme);
    const page = await context.newPage();
    for (const [name, path] of pages) {
      await page.goto(`${origin}${BASE}${path}`, { waitUntil: 'load' });
      const file = join(out, `${name}-${w}x${h}-${theme}.png`);
      await page.screenshot({ path: file, fullPage: true });
      n++;
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (over > 0) {
        overflow++;
        console.log(`  horizontal overflow ${over}px: ${name} ${w}x${h} ${theme}`);
      }
    }
    await context.close();
  }
}
await browser.close();
await close();
console.log(`screenshots: ${n} written to qa/screenshots/; ${overflow} with horizontal overflow.`);
