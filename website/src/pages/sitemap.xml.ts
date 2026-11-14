import type { APIRoute } from 'astro';
import { DOC_PAGES } from '../data/docs.mjs';
import { SITE } from '../data/site';

// A hand-written sitemap keeps the build free of extra integrations and lists
// exactly the canonical URLs the pages declare.
export const GET: APIRoute = () => {
  const paths = ['/', '/docs', ...DOC_PAGES.map((page) => `/docs/${page.slug}`)];
  const urls = paths
    .map((path) => `  <url><loc>${new URL(path, SITE.url).href.replace(/\/$/, path === '/' ? '/' : '')}</loc></url>`)
    .join('\n');
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
  return new Response(body, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
};
