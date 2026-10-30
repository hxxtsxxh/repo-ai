// Link checker over the built site (dist/).
//
// * every internal href/src (relative, root-relative, or absolute to the production
//   origin) must resolve to a file in dist/ under the /repo-ai base path;
// * every #fragment must match an id (or name) in the target page;
// * no page may load a subresource (script, stylesheet, image, font, iframe) from
//   another origin: the site makes zero third-party requests at runtime.
//
// Exit code 1 on any problem. Usage: node scripts/check-links.mjs [distDir]
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = process.argv[2] ? resolve(process.argv[2]) : join(root, 'dist');
const BASE = '/repo-ai/';
const ORIGIN = 'https://hxxtsxxh.github.io';

if (!existsSync(dist)) {
  console.error(`check-links: ${dist} does not exist; run \`npm run build\` first.`);
  process.exit(2);
}

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

const files = walk(dist);
const htmlFiles = files.filter((f) => f.endsWith('.html'));
const fileSet = new Set(files.map((f) => relative(dist, f).split('\\').join('/')));

const decode = (s) =>
  s.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');

const idCache = new Map();
function idsOf(relFile) {
  if (idCache.has(relFile)) return idCache.get(relFile);
  const html = readFileSync(join(dist, relFile), 'utf8');
  const ids = new Set();
  for (const m of html.matchAll(/\s(?:id|name)="([^"]+)"/g)) ids.add(decode(m[1]));
  idCache.set(relFile, ids);
  return ids;
}

/** Map a site path (beginning with BASE) to a file in dist, or null. */
function resolveSitePath(pathname) {
  if (!pathname.startsWith(BASE) && pathname !== BASE.slice(0, -1)) return { error: `outside base path ${BASE}` };
  let p = decodeURIComponent(pathname.slice(BASE.length));
  if (p === '' || p.endsWith('/')) p = `${p}index.html`;
  if (fileSet.has(p)) return { file: p };
  if (fileSet.has(`${p}/index.html`)) return { file: `${p}/index.html`, needsSlash: true };
  if (fileSet.has(`${p}.html`)) return { file: `${p}.html` };
  return { error: 'no such file in dist' };
}

const problems = [];
const external = new Map();
let checked = 0;

const TAG_RE = /<(a|link|script|img|source|iframe|video|audio|use|image|meta)\b([^>]*)>/gi;
const ATTR_RE = /\s(href|src|srcset|xlink:href|content)="([^"]*)"/gi;

for (const file of htmlFiles) {
  const rel = relative(dist, file).split('\\').join('/');
  const html = readFileSync(file, 'utf8');
  // the page's own URL path, for resolving relative links
  const pagePath = BASE + rel.replace(/index\.html$/, '').replace(/\.html$/, '');

  for (const tag of html.matchAll(TAG_RE)) {
    const tagName = tag[1].toLowerCase();
    const attrs = tag[2];
    for (const a of attrs.matchAll(ATTR_RE)) {
      const attr = a[1].toLowerCase();
      let raw = decode(a[2]).trim();
      if (tagName === 'meta') {
        // only og:image / twitter:image style URLs
        if (attr !== 'content' || !/^https?:\/\//.test(raw)) continue;
      } else if (attr === 'content') continue;
      const candidates = attr === 'srcset' ? raw.split(',').map((s) => s.trim().split(/\s+/)[0]) : [raw];
      for (const url of candidates) {
        if (!url || url.startsWith('data:') || url.startsWith('mailto:') || url.startsWith('javascript:')) continue;
        const isSubresource = tagName !== 'a' && !(tagName === 'link' && /rel="(canonical|sitemap|alternate)"/.test(attrs)) && tagName !== 'meta';
        let target;
        if (/^https?:\/\//i.test(url) || url.startsWith('//')) {
          const u = new URL(url, ORIGIN);
          if (u.origin !== ORIGIN) {
            if (isSubresource) problems.push(`${rel}: third-party subresource <${tagName} ${attr}="${url}">`);
            external.set(url, (external.get(url) ?? 0) + 1);
            continue;
          }
          target = u;
        } else {
          target = new URL(url, ORIGIN + pagePath);
        }
        checked++;
        const res = resolveSitePath(target.pathname);
        if (res.error) {
          problems.push(`${rel}: broken ${attr}="${url}" (${res.error})`);
          continue;
        }
        const frag = target.hash ? decodeURIComponent(target.hash.slice(1)) : '';
        if (frag && res.file.endsWith('.html') && !idsOf(res.file).has(frag)) {
          problems.push(`${rel}: missing anchor #${frag} in ${res.file} (from ${url})`);
        }
      }
    }
  }
}

console.log(`check-links: ${htmlFiles.length} pages, ${checked} internal URLs checked, ${external.size} distinct external link(s).`);
for (const [url, n] of external) console.log(`  external link (not fetched): ${url} ×${n}`);
if (problems.length) {
  console.error(`\n${problems.length} problem(s):`);
  for (const p of problems) console.error(`  ✗ ${p}`);
  process.exit(1);
}
console.log('check-links: 0 broken links, 0 missing anchors, 0 third-party subresources.');
