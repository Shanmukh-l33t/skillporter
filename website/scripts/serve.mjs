#!/usr/bin/env node
/**
 * Minimal static file server for the built site (website/dist).
 *
 * It resolves URLs the way common static hosts do, so local checks exercise
 * the same routes production will serve:
 *
 *   /docs/cli        -> dist/docs/cli.html
 *   /docs            -> dist/docs/index.html
 *   /docs/cli.html   -> 301 /docs/cli
 *   unknown path     -> dist/404.html with status 404
 *
 * Usage: node scripts/serve.mjs [port]      (default 4321)
 * No dependencies. Not intended for production use.
 */
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const DIST = resolve(fileURLToPath(new URL('../dist', import.meta.url)));
const PORT = Number(process.argv[2] ?? process.env.PORT ?? 4321);

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.xml': 'application/xml; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.wasm': 'application/wasm',
};

const isFile = (path) => existsSync(path) && statSync(path).isFile();

function resolveFile(pathname) {
  const safe = normalize(decodeURIComponent(pathname)).replace(/^(\.\.[/\\])+/, '');
  const base = join(DIST, safe);
  if (base !== DIST && !base.startsWith(DIST + sep)) return null;
  const trimmed = base.replace(/[/\\]+$/, '');
  for (const candidate of [base, `${trimmed}.html`, join(trimmed, 'index.html')]) {
    if (isFile(candidate)) return candidate;
  }
  return null;
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);

  if (url.pathname.endsWith('.html') && url.pathname !== '/404.html') {
    const clean = url.pathname.replace(/\/index\.html$/, '/').replace(/\.html$/, '');
    res.writeHead(301, { Location: clean + url.search });
    res.end();
    return;
  }

  const file = resolveFile(url.pathname);
  const target = file ?? join(DIST, '404.html');
  const status = file ? 200 : 404;
  if (!isFile(target)) {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not found. Run "npm run build" first.');
    return;
  }
  res.writeHead(status, {
    'Content-Type': TYPES[extname(target)] ?? 'application/octet-stream',
    'Cache-Control': 'no-store',
  });
  createReadStream(target).pipe(res);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Serving ${DIST} at http://127.0.0.1:${PORT}`);
});
