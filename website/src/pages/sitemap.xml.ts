import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { DOC_PAGES } from '../data/docs.mjs';
import { SITE } from '../data/site';

// A hand-written sitemap keeps the build free of extra integrations and lists
// exactly the canonical URLs the pages declare. New marketing pages and blog
// articles are discovered from their content collections, so adding a file is
// enough to get it listed.
export const GET: APIRoute = async () => {
  const [pages, posts] = await Promise.all([getCollection('pages'), getCollection('blog')]);
  const paths = [
    '/',
    '/docs',
    ...DOC_PAGES.map((page) => `/docs/${page.slug}`),
    ...pages.map((entry) => `/${entry.id}`),
    '/blog',
    ...posts
      .map((entry) => ({ id: entry.id, date: (entry.data.date as string | undefined) ?? '' }))
      .sort((a, b) => b.date.localeCompare(a.date))
      .map((entry) => `/blog/${entry.id}`),
  ];
  const lastmod = new Map<string, string>([['/blog', '']]);
  for (const entry of posts) {
    const date = entry.data.date as string | undefined;
    if (date) lastmod.set(`/blog/${entry.id}`, `<lastmod>${date}</lastmod>`);
  }
  const urls = paths
    .map((path) => {
      const loc = new URL(path, SITE.url).href.replace(/\/$/, path === '/' ? '/' : '');
      return `  <url><loc>${loc}</loc>${lastmod.get(path) ?? ''}</url>`;
    })
    .join('\n');
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
  return new Response(body, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
};
