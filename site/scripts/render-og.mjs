// Renders the social card and PNG favicons from SVG sources into public/.
// Run with `npm run og` after changing the brand; the PNGs are committed, so the
// site build itself never needs this script (or the fonts it uses).
import { Resvg } from '@resvg/resvg-js';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const pub = join(root, 'public');
mkdirSync(pub, { recursive: true });

const SANS = 'Helvetica Neue, Helvetica, Arial, DejaVu Sans, sans-serif';
const MONO = 'Menlo, SF Mono, DejaVu Sans Mono, Consolas, monospace';

function render(svg, width, out) {
  const resvg = new Resvg(svg, {
    fitTo: { mode: 'width', value: width },
    font: { loadSystemFonts: true, defaultFontFamily: 'Helvetica Neue' },
    background: 'rgba(0,0,0,0)',
  });
  const png = resvg.render().asPng();
  writeFileSync(join(pub, out), png);
  console.log(`wrote public/${out} (${png.length} bytes)`);
}

// ---- social card ----
const lines = Array.from({ length: 20 }, (_, i) => `<path d="M0 ${i * 32 + 6.5}H1200" stroke="#1b2421" stroke-width="1"/>`).join('');
const chip = (x, label, color) => {
  const w = 18 + label.length * 13.2;
  return `<g transform="translate(${x} 0)"><rect x="0" y="0" width="${w}" height="40" rx="6" fill="none" stroke="${color}" stroke-width="2"/><text x="${w / 2}" y="27" text-anchor="middle" font-family="${MONO}" font-size="21" font-weight="700" fill="${color}">${label}</text></g>`;
};
let cx = 0;
const chips = [
  ['PASSED', '#62d6a6'],
  ['REGRESSION', '#ff8f80'],
  ['already failing', '#f2c46b'],
  ['ABSTAIN', '#b3bcff'],
]
  .map(([l, c]) => {
    const g = chip(cx, l, c);
    cx += 18 + l.length * 13.2 + 16;
    return g;
  })
  .join('');

const og = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#0e1211"/>
  ${lines}
  <rect x="0" y="0" width="10" height="630" fill="#62d6a6"/>
  <g transform="translate(80 78)">
    <rect x="0" y="0" width="64" height="64" rx="14" fill="#0e1211" stroke="#34433e" stroke-width="2"/>
    <path d="M16 15v34" stroke="#62d6a6" stroke-width="4.6" stroke-linecap="round"/>
    <path d="M25 19h22M25 32h12M25 45h17" stroke="#e8ede9" stroke-width="4.6" stroke-linecap="round"/>
    <rect x="42" y="26.5" width="11" height="11" rx="2.5" fill="#62d6a6"/>
    <text x="88" y="45" font-family="${MONO}" font-size="38" font-weight="700" fill="#e8ede9">repo<tspan fill="#62d6a6">-</tspan>ai</text>
  </g>
  <text x="80" y="270" font-family="${SANS}" font-size="72" font-weight="700" fill="#e8ede9" letter-spacing="-2">Context before the change.</text>
  <text x="80" y="356" font-family="${SANS}" font-size="72" font-weight="700" fill="#62d6a6" letter-spacing="-2">Evidence after it.</text>
  <text x="80" y="420" font-family="${SANS}" font-size="27" fill="#a4b0ab">A local-first CLI: offline repository context, sandboxed change verification,</text>
  <text x="80" y="456" font-family="${SANS}" font-size="27" fill="#a4b0ab">and optional coding agents under frozen tests.</text>
  <g transform="translate(80 500)">${chips}</g>
  <text x="80" y="588" font-family="${MONO}" font-size="19" fill="#8f9c97">A pass means the tests that ran observed a pass. Never that the task is correct.</text>
</svg>`;
render(og, 1200, 'og.png');

// ---- favicons ----
const mark = readFileSync(join(root, 'src/assets/logo.svg'), 'utf8');
render(mark, 32, 'favicon-32.png');
// apple-touch-icon: opaque, with padding
const touch = `<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180" viewBox="0 0 32 32">
  <rect width="32" height="32" fill="#0e1211"/>
  <path d="M9 8.5v15" stroke="#62d6a6" stroke-width="2.2" stroke-linecap="round"/>
  <path d="M13 10h10M13 16h5.5M13 22h8" stroke="#e8ede9" stroke-width="2.2" stroke-linecap="round"/>
  <rect x="20.5" y="13.5" width="5" height="5" rx="1.2" fill="#62d6a6"/>
</svg>`;
render(touch, 180, 'apple-touch-icon.png');
