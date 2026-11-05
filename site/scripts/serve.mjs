// Minimal static server for dist/ that mimics GitHub Pages under the /repo-ai base
// path (directory index.html, 404.html for misses). Used by the QA scripts so they do
// not depend on a separately running `astro preview`.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname, normalize, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
export const BASE = '/repo-ai/';
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.xml': 'application/xml',
  '.txt': 'text/plain; charset=utf-8',
  '.woff2': 'font/woff2',
  '.pf_meta': 'application/octet-stream',
  '.pf_index': 'application/octet-stream',
  '.pf_fragment': 'application/octet-stream',
  '.pagefind': 'application/octet-stream',
};

export function startServer(port = 0, distDir = join(root, 'dist')) {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://localhost');
    let path = decodeURIComponent(url.pathname);
    if (!path.startsWith(BASE)) {
      if (path === BASE.slice(0, -1)) {
        res.writeHead(301, { location: BASE });
        return res.end();
      }
      res.writeHead(404, { 'content-type': 'text/plain' });
      return res.end('outside base path');
    }
    let file = normalize(join(distDir, path.slice(BASE.length)));
    if (!file.startsWith(distDir)) {
      res.writeHead(403);
      return res.end();
    }
    try {
      const s = await stat(file);
      if (s.isDirectory()) {
        if (!path.endsWith('/')) {
          res.writeHead(301, { location: `${path}/` });
          return res.end();
        }
        file = join(file, 'index.html');
      }
      const body = await readFile(file);
      res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' });
      res.end(body);
    } catch {
      try {
        const body = await readFile(join(distDir, '404.html'));
        res.writeHead(404, { 'content-type': TYPES['.html'] });
        res.end(body);
      } catch {
        res.writeHead(404);
        res.end('not found');
      }
    }
  });
  return new Promise((resolve) => {
    server.listen(port, '127.0.0.1', () => {
      const { port: p } = server.address();
      resolve({ server, origin: `http://127.0.0.1:${p}`, close: () => new Promise((r) => server.close(r)) });
    });
  });
}

/** Every built HTML page, as a path under the base (e.g. "docs/verify/"). */
export async function allPages(distDir = join(root, 'dist')) {
  const { readdir } = await import('node:fs/promises');
  const out = [];
  async function walk(dir, rel) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (entry.name === 'pagefind' || entry.name === '_astro') continue;
        await walk(join(dir, entry.name), `${rel}${entry.name}/`);
      } else if (entry.name === 'index.html') out.push(rel);
      else if (entry.name === '404.html') out.push(`${rel}404.html`);
    }
  }
  await walk(distDir, '');
  return out.sort();
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT ?? 4322);
  const { origin } = await startServer(port);
  console.log(`serving dist/ at ${origin}${BASE}`);
}
