/**
 * Post-processing for rendered documentation HTML.
 *
 * The docs are plain Markdown that must read correctly on GitHub, so they use
 * GitHub-relative links (`../security/README.md`, `../../LICENSE`) and start
 * with an `# H1`. For the website this module:
 *
 *   1. drops the leading H1 (the layout renders the title from the manifest),
 *   2. rewrites links between docs to site routes (`/docs/security`) and links
 *      to other repository files to their GitHub URL,
 *   3. marks external links,
 *   4. wraps tables so wide ones scroll on their own on small screens.
 *
 * It works on the HTML string, so it does not depend on which Markdown
 * processor Astro uses, and it has no dependencies.
 */
import { DIR_TO_SLUG, GITHUB_REPO } from '../data/docs.mjs';

/** Resolve `href` as if it were written inside `docs/<dir>/README.md`. */
function resolveRepoPath(href) {
  const parts = ['docs', '_page'];
  for (const segment of href.split('/')) {
    if (segment === '' || segment === '.') continue;
    if (segment === '..') parts.pop();
    else parts.push(segment);
  }
  return parts.join('/');
}

/**
 * @param {string} href
 * @returns {{ href: string, external: boolean }}
 */
export function rewriteHref(href) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(href)) return { href, external: /^https?:/i.test(href) };
  if (href.startsWith('/')) return { href, external: false };

  const [pathPart = '', hash = ''] = href.split('#');
  const repoPath = resolveRepoPath(pathPart);
  const suffix = hash ? `#${hash}` : '';

  const docMatch = /^docs\/([^/]+)\/README\.md$/.exec(repoPath);
  if (docMatch && DIR_TO_SLUG.has(docMatch[1])) {
    return { href: `/docs/${DIR_TO_SLUG.get(docMatch[1])}${suffix}`, external: false };
  }
  return { href: `${GITHUB_REPO}/blob/main/${repoPath}${suffix}`, external: true };
}

/**
 * @param {string} html Rendered Markdown.
 * @returns {string}
 */
export function transformDocHtml(html) {
  let out = html.replace(/<h1\b[^>]*>[\s\S]*?<\/h1>\s*/, '');

  out = out.replace(/<a\b([^>]*?)\bhref="([^"]*)"([^>]*)>/g, (_match, before, rawHref, after) => {
    const { href, external } = rewriteHref(rawHref.replace(/&amp;/g, '&'));
    const safeHref = href.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    const extra = external ? ' class="external" rel="noopener noreferrer"' : '';
    return `<a${before}href="${safeHref}"${after}${extra}>`;
  });

  out = out
    .replace(/<table\b/g, '<div class="table-scroll" tabindex="0" role="region" aria-label="Table"><table')
    .replace(/<\/table>/g, '</table></div>');

  return out;
}
