/**
 * Content and integrity checks for the built site.
 *
 * Run with `npm test` after `npm run build`. Node's built-in test runner is
 * used, so there are no test dependencies. These checks exist to stop the site
 * from drifting away from the released product: versions, harness data, CLI
 * commands, install instructions and links are all verified against the
 * repository's own sources.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { DOC_PAGES } from '../src/data/docs.mjs';
import { rewriteHref, transformDocHtml } from '../src/lib/docs-html.mjs';

const WEBSITE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const REPO = resolve(WEBSITE, '..');
const DIST = join(WEBSITE, 'dist');

const readJson = (path) => JSON.parse(readFileSync(path, 'utf8'));
const harnessData = readJson(join(WEBSITE, 'src/data/harnesses.json'));
const cliData = readJson(join(WEBSITE, 'src/data/cli.json'));
const release = readJson(join(WEBSITE, 'src/data/release.json'));

assert.ok(existsSync(join(DIST, 'index.html')), 'dist/ is missing. Run "npm run build" before "npm test".');

/* ------------------------------------------------------------- helpers */

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const htmlFiles = walk(DIST).filter(
  (file) =>
    file.endsWith('.html') &&
    !file.includes(`${join(DIST, 'pagefind')}`) &&
    // Third party ownership checks, not pages of the site.
    !/google[0-9a-f]+\.html$/.test(file) &&
    !/^indexnow-/.test(file),
);
const pages = new Map(htmlFiles.map((file) => [relative(DIST, file), readFileSync(file, 'utf8')]));

/** The route a built file is served at. */
function routeOf(file) {
  if (file === 'index.html') return '/';
  return `/${file.replace(/\/index\.html$/, '').replace(/\.html$/, '')}`;
}

const decode = (text) =>
  text
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&#x27;|&apos;/g, "'")
    .replace(/&#x([0-9a-f]+);/gi, (_m, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_m, dec) => String.fromCodePoint(Number(dec)))
    .replace(/&amp;/g, '&');

const stripTags = (html) => decode(html.replace(/<[^>]+>/g, ''));

/** Visible text of a page, without scripts, styles or preformatted blocks. */
function proseOf(html) {
  return stripTags(
    html
      .replace(/<script\b[\s\S]*?<\/script>/g, ' ')
      .replace(/<style\b[\s\S]*?<\/style>/g, ' ')
      .replace(/<pre\b[\s\S]*?<\/pre>/g, ' '),
  );
}

const blocks = (html, tag) => [...html.matchAll(new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)</${tag}>`, 'g'))].map((m) => stripTags(m[1]));

function resolveRoute(pathname) {
  const clean = pathname.replace(/\/+$/, '') || '/';
  const candidates = clean === '/' ? ['index.html'] : [clean.slice(1), `${clean.slice(1)}.html`, `${clean.slice(1)}/index.html`];
  return candidates.find((candidate) => existsSync(join(DIST, candidate)) && statSync(join(DIST, candidate)).isFile());
}

/* ------------------------------------------------------- release facts */

test('displayed version matches the released package version', () => {
  const pyproject = readFileSync(join(REPO, 'pyproject.toml'), 'utf8');
  const version = /^version = "([^"]+)"/m.exec(pyproject)?.[1];
  assert.ok(version, 'version not found in pyproject.toml');
  assert.equal(release.version, version);
  assert.equal(readJson(join(REPO, 'package.json')).version, version);
  assert.equal(readFileSync(join(WEBSITE, 'src/data/recordings/VERSION'), 'utf8').trim(), `skillporter ${version}`);

  const home = pages.get('index.html');
  assert.ok(home.includes(`v${version}`), 'home page does not show the release tag');
  // Preformatted blocks hold recorded output and examples (a skill's own
  // version, an example Git tag), so only prose is checked here.
  const shown = new Set([...proseOf(home).matchAll(/\bv(\d+\.\d+\.\d+)\b/g)].map((m) => m[1]));
  assert.deepEqual([...shown], [version], 'home page shows a Skillporter version other than the release');
});

test('no outdated v2 branding remains anywhere on the site', () => {
  for (const [file, html] of pages) {
    const text = stripTags(html);
    assert.doesNotMatch(text, /v?2\.0\.0|v?2\.4\.0|\bv2\.\d/, `${file} mentions a 2.x release`);
    assert.doesNotMatch(text, /Skillporter v?2\b/i, `${file} mentions Skillporter 2`);
  }
});

test('removed marketing sections stay removed', () => {
  for (const [file, html] of pages) {
    const text = proseOf(html);
    assert.doesNotMatch(text, /lookalike|skill-porter|agent-skill-porter|\bskillport\b/i, `${file} has a competitor comparison`);
    assert.doesNotMatch(text, /\bGEN \d\b|\broadmap\b/i, `${file} has roadmap marketing`);
  }
});

test('no fabricated metrics, testimonials or certifications', () => {
  const banned =
    /\b(?:github )?stars\b|\bdownloads? (?:per|a) (?:week|month)\b|\btrusted by\b|\bcustomers?\b|\btestimonial|\bSOC ?2\b|\bISO ?27001\b|\b\d[\d,.]*\+? (?:users|developers|teams|companies)\b/i;
  for (const [file, html] of pages) {
    assert.doesNotMatch(proseOf(html), banned, `${file} contains an unsupported metric or claim`);
  }
});

/* -------------------------------------------------------- harness data */

test('generated site data matches the Python registry', () => {
  // Fails when skillporter/harnesses.py or the CLI changed without regenerating.
  const out = execFileSync('python3', [join(WEBSITE, 'scripts/generate_site_data.py'), '--check'], {
    encoding: 'utf8',
    env: { ...process.env, PYTHONPATH: '' },
  });
  assert.match(out, /website data is current/);
});

test('harness matrix renders every registry adapter with its real classification', () => {
  const home = pages.get('index.html');
  const rows = [...home.matchAll(/<tr\b[^>]*data-harness-id="([^"]+)"[^>]*>/g)].map((m) => ({
    id: m[1],
    tier: /data-tier="([^"]+)"/.exec(m[0])?.[1],
    category: /data-category="([^"]+)"/.exec(m[0])?.[1],
  }));
  assert.equal(rows.length, harnessData.counts.total, 'row count differs from the registry');
  assert.equal(new Set(rows.map((r) => r.id)).size, rows.length, 'duplicate harness rows');
  for (const row of rows) {
    const source = harnessData.harnesses.find((h) => h.id === row.id);
    assert.ok(source, `unknown harness on the site: ${row.id}`);
    assert.equal(row.tier, source.verification, `${row.id}: wrong verification tier`);
    assert.equal(row.category, source.category, `${row.id}: wrong category`);
    assert.ok(home.includes(`href="${source.docs}"`), `${row.id}: vendor documentation link missing`);
  }
});

test('verification counts on the page are the registry counts', () => {
  const home = pages.get('index.html');
  const shown = Object.fromEntries(
    [...home.matchAll(/data-tier-count="([A-Z_]+)"[^>]*>\s*(\d+)\s*</g)].map((m) => [m[1], Number(m[2])]),
  );
  for (const [tier, count] of Object.entries(harnessData.counts.verification)) {
    assert.equal(shown[tier], count, `${tier} count`);
  }
  const total = Object.values(harnessData.counts.verification).reduce((a, b) => a + b, 0);
  assert.equal(total, harnessData.counts.total);
  // The site must never claim that every adapter is runtime verified.
  assert.ok(harnessData.counts.verification.RUNTIME_VERIFIED < harnessData.counts.total);
  assert.doesNotMatch(proseOf(home), /\b\d+\s+(?:runtime[- ])?verified (?:ai[- ]agent )?harnesses\b/i);
});

/* ------------------------------------------------------- install rules */

test('installer instructions use the immutable release and keep verification', () => {
  const all = [...pages.values()].join('\n');
  assert.doesNotMatch(all, /raw\.githubusercontent\.com/, 'mutable raw GitHub URL found');
  assert.doesNotMatch(all, /\/(?:main|master|HEAD|latest)\/install\.sh/, 'installer fetched from a mutable ref');
  assert.ok(all.includes(release.installer_url), 'release installer URL missing');
  assert.equal(release.installer_url, `https://github.com/Shanmukh-l33t/skillporter/releases/download/v${release.version}/install.sh`);

  for (const [file, html] of pages) {
    for (const pre of blocks(html, 'pre')) {
      for (const line of pre.split('\n')) {
        if (/^\s*#/.test(line)) continue;
        assert.doesNotMatch(line, /\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b/, `${file}: pipes a download into a shell`);
      }
    }
  }

  const home = stripTags(pages.get('index.html'));
  assert.ok(home.includes(`SKILLPORTER_VERSION=v${release.version} sh install.sh`));
  assert.match(home, /attestation/i, 'home install panel does not explain authenticity verification');

  const install = stripTags(pages.get('docs/installation.html'));
  for (const needle of ['gh attestation verify', 'SKILLPORTER_SHA256', 'SKILLPORTER_PUBLIC_KEY_FILE']) {
    assert.ok(install.includes(needle), `installation page does not document ${needle}`);
  }
});

test('the pinned digest in the docs is the published release artifact', () => {
  const digest = /SKILLPORTER_SHA256=([0-9a-f]{64})/.exec(stripTags(pages.get('docs/installation.html')))?.[1];
  assert.ok(digest, 'no pinned digest found');
  // Recorded from `gh attestation verify` against the v3.0.1 release asset.
  if (release.version === '3.0.1') {
    assert.equal(digest, '8bd7125b8f2a1a4f7c475406c71eaaec317bc4d7a0dd5d19e857301ef127179c');
  }
});

/* --------------------------------------------------------- CLI accuracy */

const LAUNCHERS = /^(?:\$ )?(?:uvx |npx @shanmukhdheekonda\/skillporter(?=\s)|\.venv\/bin\/python -m |python3? -m |[\w./~-]*\/)?(?:skillporter )?/;

function checkCommand(line, where) {
  const body = line.replace(LAUNCHERS, '').trim();
  const tokens = body.split(/\s+/);
  const name = tokens[0];
  if (name?.startsWith('<')) return; // usage synopsis such as `skillporter <command> [options]`
  if (!name || name.startsWith('-')) {
    for (const flag of tokens.filter((t) => t.startsWith('--'))) {
      assert.ok(cliData.global_flags.includes(flag.split('=')[0]), `${where}: unknown global flag in "${line}"`);
    }
    return;
  }
  let spec = cliData.commands[name];
  assert.ok(spec, `${where}: "${line}" uses a command that does not exist: ${name}`);
  const subName = tokens[1];
  const argStart = subName && spec.subcommands?.[subName] ? ((spec = spec.subcommands[subName]), 2) : 1;
  for (const token of tokens.slice(argStart)) {
    if (!token.startsWith('--')) continue;
    const flag = token.split('=')[0].replace(/[),.;`]+$/, '');
    assert.ok(spec.flags.includes(flag) || flag === '--help', `${where}: "${line}" uses an unknown flag for ${name}: ${flag}`);
  }
}

const isInvocation = (line) =>
  /^(?:\$ )?(?:uvx |\.venv\/bin\/python -m |python3? -m )?skillporter(?:\s|$)/.test(line) ||
  /^(?:\$ )?npx @shanmukhdheekonda\/skillporter\s/.test(line);

test('every skillporter command and flag shown on the site exists in the CLI', () => {
  let checked = 0;
  for (const [file, html] of pages) {
    for (const pre of blocks(html, 'pre')) {
      for (const raw of pre.split('\n')) {
        const line = raw.trim().replace(/\s+\\$/, '');
        if (!isInvocation(line) || /^skillporter [\d.]+ /.test(line) || /^skillporter\.(?:lock|yaml)/.test(line)) continue;
        // `skillporter: <key>` style YAML and prose are not invocations.
        if (/^skillporter:/.test(line)) continue;
        checkCommand(line.split(/\s+[|>]\s*/)[0], file);
        checked += 1;
      }
    }
    for (const code of blocks(html.replace(/<pre\b[\s\S]*?<\/pre>/g, ''), 'code')) {
      const line = code.trim();
      if (!/^skillporter [a-z]/.test(line)) continue;
      // Reference headings use placeholders such as <source> and [path].
      checkCommand(line.replace(/[<[][^>\]]*[>\]]/g, '').replace(/\|/g, ' '), file);
      checked += 1;
    }
  }
  assert.ok(checked > 80, `expected to check many commands, only found ${checked}`);
});

test('the CLI reference documents every public command', () => {
  const reference = stripTags(pages.get('docs/cli.html'));
  for (const name of Object.keys(cliData.commands)) {
    assert.ok(reference.includes(`skillporter ${name}`) || reference.includes(`\`${name}\``) || new RegExp(`\\b${name}\\b`).test(reference), `CLI reference does not mention "${name}"`);
  }
});

test('terminal demonstrations are real recordings and are labelled', () => {
  const recordings = join(WEBSITE, 'src/data/recordings');
  for (const file of readdirSync(recordings).filter((name) => name.endsWith('.txt') && name !== 'skillporter.yaml.txt')) {
    const text = readFileSync(join(recordings, file), 'utf8');
    assert.match(text, /^# exit: [\d,]+\n\$ skillporter /, `${file} is not a recorder transcript`);
    assert.doesNotMatch(text, /\/root\/|\/home\/|\/tmp\/sp-record/, `${file} leaks a local path`);
  }
  const home = pages.get('index.html');
  assert.match(home, /Recorded output, skillporter \d+\.\d+\.\d+/);
  assert.match(stripTags(home), /Nothing runs in your browser/);
  assert.match(stripTags(home), /test (?:skill|fixture)/i, 'the unsafe scan sample is not identified as a test fixture');
});

/* ----------------------------------------------------- security wording */

test('security claims stay honest', () => {
  const home = proseOf(pages.get('index.html'));
  assert.match(home, /A clean scan does not prove a skill is safe at runtime/);
  assert.match(home, /static/i);
  const banned = /\b(?:guarantees? (?:safety|security)|100% (?:secure|safe)|malware[- ]free|detects all|bulletproof|unhackable|military[- ]grade)\b/i;
  for (const [file, html] of pages) assert.doesNotMatch(proseOf(html), banned, `${file} overclaims security`);
  const model = proseOf(pages.get('docs/security.html'));
  for (const topic of ['Novel prompt injection', 'Runtime-fetched content', 'Obfuscation', 'Host isolation']) {
    assert.ok(model.includes(topic), `security model does not state the limitation: ${topic}`);
  }
});

/* ----------------------------------------------------------- structure */

test('all required routes are built', () => {
  const required = [
    '/', '/docs', '/docs/getting-started', '/docs/installation', '/docs/cli', '/docs/harnesses', '/docs/security',
    '/docs/lockfiles', '/docs/synchronization', '/docs/mcp', '/docs/configuration', '/docs/troubleshooting', '/docs/contributing',
    '/skill-porter', '/faq', '/install', '/blog',
  ];
  for (const route of required) assert.ok(resolveRoute(route), `route not built: ${route}`);
  for (const page of DOC_PAGES) {
    assert.ok(resolveRoute(`/docs/${page.slug}`), `docs page not built: ${page.slug}`);
    assert.ok(existsSync(join(REPO, 'docs', page.dir, 'README.md')), `docs source missing: ${page.dir}`);
  }
  for (const slug of contentSlugs('src/content/pages')) {
    assert.ok(resolveRoute(`/${slug}`), `content page not built: ${slug}`);
  }
  for (const slug of contentSlugs('src/content/blog')) {
    assert.ok(resolveRoute(`/blog/${slug}`), `blog article not built: ${slug}`);
  }
});

test('every page in the pages collection is a substantial page, not a stub', () => {
  for (const slug of contentSlugs('src/content/pages')) {
    const html = pages.get(`${slug}.html`);
    assert.ok(html, `content page missing from the build: ${slug}`);
    const main = /<main\b[\s\S]*?<\/main>/.exec(html)?.[0] ?? '';
    const words = stripTags(main).split(/\s+/).filter(Boolean).length;
    assert.ok(words > 300, `${slug} has only ${words} words`);
  }
  for (const slug of contentSlugs('src/content/blog')) {
    const html = pages.get(`blog/${slug}.html`);
    assert.ok(html, `blog article missing from the build: ${slug}`);
    const main = /<main\b[\s\S]*?<\/main>/.exec(html)?.[0] ?? '';
    const words = stripTags(main).split(/\s+/).filter(Boolean).length;
    assert.ok(words > 600, `${slug} has only ${words} words`);
    assert.match(html, /"@type":"BlogPosting"/, `${slug} has no BlogPosting structured data`);
  }
});

test('the two-word brand name is present on the pages that must rank for it', () => {
  for (const route of ['index.html', 'skill-porter.html', 'faq.html']) {
    const html = pages.get(route);
    assert.ok(html, `${route} missing`);
    assert.ok((stripTags(html).match(/Skill Porter/g) ?? []).length >= 3, `${route} does not use the two-word brand name`);
  }
  for (const file of pages.keys()) {
    assert.doesNotMatch(stripTags(pages.get(file)), /skill-porter/i, `${file} uses the hyphenated brand spelling in prose`);
  }
});

test('no documentation page is an empty placeholder', () => {
  for (const page of DOC_PAGES) {
    const html = pages.get(`docs/${page.slug}.html`);
    const article = /<article\b[\s\S]*?<\/article>/.exec(html)?.[0] ?? '';
    const words = stripTags(article).split(/\s+/).filter(Boolean).length;
    assert.ok(words > 150, `/docs/${page.slug} has only ${words} words`);
    assert.doesNotMatch(stripTags(article), /\b(?:coming soon|TODO|TBD|lorem ipsum)\b/i);
  }
});

test('every internal link and anchor resolves', () => {
  const ids = new Map();
  for (const [file, html] of pages) ids.set(file, new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => decode(m[1]))));
  let checked = 0;
  for (const [file, html] of pages) {
    for (const match of html.matchAll(/\shref="([^"]+)"/g)) {
      const href = decode(match[1]);
      if (/^(?:https?:|mailto:|\/\/)/.test(href)) continue;
      const [pathPart, hash] = href.split('#');
      let target = file;
      if (pathPart) {
        assert.ok(pathPart.startsWith('/'), `${file}: relative link "${href}" would break on nested routes`);
        target = resolveRoute(pathPart);
        assert.ok(target, `${file}: broken link ${href}`);
      }
      if (hash && target.endsWith('.html')) {
        assert.ok(ids.get(target)?.has(decodeURIComponent(hash)), `${file}: missing anchor ${href}`);
      }
      checked += 1;
    }
  }
  assert.ok(checked > 300);
});

test('external links point at the official project and use https', () => {
  const hosts = new Set();
  for (const [file, html] of pages) {
    for (const match of html.matchAll(/\shref="(https?:[^"]+)"/g)) {
      const url = new URL(decode(match[1]));
      assert.equal(url.protocol, 'https:', `${file}: insecure link ${url.href}`);
      hosts.add(url.hostname);
      if (url.hostname === 'github.com' && /skillporter/i.test(url.pathname)) {
        assert.ok(url.pathname.startsWith('/Shanmukh-l33t/skillporter'), `${file}: wrong repository ${url.href}`);
      }
    }
    assert.doesNotMatch(html, /mailto:/, `${file}: contains an email address that was never provided`);
  }
  assert.ok(hosts.has('github.com'));
});

test('repository files linked from the site exist', () => {
  for (const [file, html] of pages) {
    for (const match of html.matchAll(/href="https:\/\/github\.com\/Shanmukh-l33t\/skillporter\/(?:blob|edit)\/main\/([^"#]+)/g)) {
      assert.ok(existsSync(join(REPO, decodeURIComponent(match[1]))), `${file}: links to a missing repository file ${match[1]}`);
    }
  }
});

/* ------------------------------------------------------------------ SEO */

test('every page has canonical, description and social metadata on skillporter.dev', () => {
  const titles = new Set();
  for (const [file, html] of pages) {
    const title = /<title>([^<]+)<\/title>/.exec(html)?.[1];
    assert.ok(title && title.length > 8, `${file}: missing title`);
    assert.ok(!titles.has(title), `${file}: duplicate title "${title}"`);
    titles.add(title);

    const description = /<meta name="description" content="([^"]+)"/.exec(html)?.[1];
    assert.ok(description && description.length >= 50 && description.length <= 200, `${file}: description length ${description?.length}`);

    const canonical = /<link rel="canonical" href="([^"]+)"/.exec(html)?.[1];
    const expected = file === '404.html' ? 'https://www.skillporter.dev/404' : `https://www.skillporter.dev${routeOf(file)}`;
    assert.equal(canonical, expected, `${file}: canonical`);

    for (const property of ['og:title', 'og:description', 'og:url', 'og:image', 'og:type']) {
      assert.match(html, new RegExp(`<meta property="${property}" content="[^"]+"`), `${file}: missing ${property}`);
    }
    assert.match(html, /<meta name="twitter:card" content="summary_large_image"/);
    assert.match(html, /og:image" content="https:\/\/www\.skillporter\.dev\/brand\/skillporter-social\.png"/);
    assert.match(html, /<html lang="en"/);
    assert.equal((html.match(/<h1\b/g) ?? []).length, 1, `${file}: must have exactly one h1`);
    assert.match(html, /<main\b[^>]*id="main"/, `${file}: skip-link target missing`);
  }
  assert.match(pages.get('404.html'), /<meta name="robots" content="noindex"/);
});

/** Slugs of the Markdown files in a content collection directory. */
function contentSlugs(dir) {
  const path = join(WEBSITE, dir);
  if (!existsSync(path)) return [];
  return readdirSync(path)
    .filter((name) => name.endsWith('.md'))
    .map((name) => name.replace(/\.md$/, ''))
    .sort();
}

test('sitemap and robots.txt cover every canonical route', () => {
  const sitemap = readFileSync(join(DIST, 'sitemap.xml'), 'utf8');
  const locs = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]).sort();
  const extraPages = contentSlugs('src/content/pages');
  const posts = contentSlugs('src/content/blog');
  const expected = [
    'https://www.skillporter.dev/',
    'https://www.skillporter.dev/docs',
    ...DOC_PAGES.map((page) => `https://www.skillporter.dev/docs/${page.slug}`),
    ...extraPages.map((slug) => `https://www.skillporter.dev/${slug}`),
    'https://www.skillporter.dev/blog',
    ...posts.map((slug) => `https://www.skillporter.dev/blog/${slug}`),
  ].sort();
  assert.deepEqual(locs, expected);
  const robots = readFileSync(join(DIST, 'robots.txt'), 'utf8');
  assert.match(robots, /Sitemap: https:\/\/www\.skillporter\.dev\/sitemap\.xml/);
  assert.doesNotMatch(robots, /Disallow: \/\s*$/m);
});

test('structured data is valid JSON-LD', () => {
  const home = pages.get('index.html');
  const scripts = [...home.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) => JSON.parse(m[1]));
  const app = scripts.find((s) => s['@type'] === 'SoftwareApplication');
  assert.ok(app, 'SoftwareApplication structured data missing');
  assert.equal(app.softwareVersion, release.version);
  assert.equal(app.url, 'https://www.skillporter.dev');
  assert.ok(!('aggregateRating' in app), 'ratings must not be invented');
});

/* ---------------------------------------------------------------- brand */

test('the approved logo is present, unmodified and used in the header', () => {
  const master = join(WEBSITE, 'public/brand/skillporter-logo.png');
  assert.ok(existsSync(master), 'approved logo missing from website/public/brand/');
  const sha = createHash('sha256').update(readFileSync(master)).digest('hex');
  assert.equal(sha, readFileSync(join(WEBSITE, 'public/brand/skillporter-logo.sha256'), 'utf8').trim(), 'master logo bytes changed');
  for (const asset of [
    'brand/skillporter-lockup.webp',
    'brand/skillporter-lockup.png',
    'brand/skillporter-lockup-light.webp',
    'brand/skillporter-lockup-light.png',
    'brand/skillporter-social.png',
    'favicon.ico',
    'apple-touch-icon.png',
    'icon-512.png',
  ]) {
    assert.ok(existsSync(join(DIST, asset)), `brand asset not built: ${asset}`);
  }
  for (const [file, html] of pages) {
    assert.match(html, /<header\b[\s\S]*?skillporter-lockup-light\.(?:webp|png)[\s\S]*?<\/header>/, `${file}: header missing light-mode logo`);
    assert.match(html, /<header\b[\s\S]*?skillporter-lockup\.(?:webp|png)[\s\S]*?<\/header>/, `${file}: header does not use the approved logo`);
    assert.match(html, /<img[^>]+alt="Skillporter"/, `${file}: logo has no text alternative`);
    assert.match(html, /<html lang="en" data-theme="light"/, `${file}: default theme must be light`);
    assert.match(html, /data-theme-toggle/, `${file}: theme toggle missing`);
  }
});

test('light default background is soft off-white with elevated cards and dark brand palette tokens are preserved', () => {
  const css = readFileSync(join(WEBSITE, 'src/styles/global.css'), 'utf8').toLowerCase();
  assert.match(css, /:root,\s*html\[data-theme='light'\]\s*\{[\s\S]*?--midnight:\s*#f5f6fa;/, 'light mode canvas must be #f5f6fa');
  assert.match(css, /:root,\s*html\[data-theme='light'\]\s*\{[\s\S]*?--card:\s*#ffffff;/, 'light mode elevated cards must be #ffffff');
  const darkBlock = /html\[data-theme='dark'\]\s*\{([\s\S]*?)\}/.exec(css)?.[1] ?? '';
  const palette = {
    '--midnight': '#070d19', '--deep-navy': '#0b1425', '--surface': '#111d31', '--electric': '#155be8', '--bridge': '#1461ed',
    '--amber': '#f18a50', '--ivory': '#f3f0e9', '--text-2': '#a6b0c0', '--border': '#263249',
  };
  for (const [token, value] of Object.entries(palette)) assert.ok(darkBlock.includes(`${token}: ${value};`), `${token} is not ${value} in dark mode`);
  assert.match(pages.get('index.html'), /--shiki-dark:/, 'dual-theme Shiki tokens missing');
});

/* ------------------------------------------------------- accessibility */

test('basic accessibility invariants hold on every page', () => {
  for (const [file, html] of pages) {
    for (const img of html.matchAll(/<img\b[^>]*>/g)) assert.match(img[0], /\salt="/, `${file}: image without alt`);
    for (const button of html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)) {
      const named = /aria-label="[^"]+"/.test(button[0]) || stripTags(button[1]).trim().length > 0;
      assert.ok(named, `${file}: button without an accessible name`);
    }
    for (const link of html.matchAll(/<a\b[^>]*>([\s\S]*?)<\/a>/g)) {
      const named = /aria-label="[^"]+"/.test(link[0]) || stripTags(link[1]).trim().length > 0 || /<img[^>]+alt="[^"]+"/.test(link[1]);
      assert.ok(named, `${file}: link without an accessible name`);
    }
    assert.match(html, /class="skip-link"/, `${file}: skip link missing`);
    assert.doesNotMatch(html, /\starget="_blank"(?![^>]*rel="[^"]*noopener)/, `${file}: target=_blank without rel=noopener`);
    // Heading levels never skip downwards by more than one.
    const levels = [...html.matchAll(/<h([1-6])\b/g)].map((m) => Number(m[1]));
    for (let i = 1; i < levels.length; i++) {
      assert.ok(levels[i] - levels[i - 1] <= 1, `${file}: heading level jumps from h${levels[i - 1]} to h${levels[i]}`);
    }
  }
  const css = readFileSync(join(WEBSITE, 'src/styles/global.css'), 'utf8');
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /:focus-visible/);
});

test('tabs, search and filters ship their interactive markup', () => {
  const home = pages.get('index.html');
  assert.ok((home.match(/role="tablist"/g) ?? []).length >= 2, 'install and demo tablists expected');
  for (const tab of home.matchAll(/role="tab"[^>]*aria-controls="([^"]+)"/g)) {
    assert.ok(home.includes(`id="${tab[1]}"`), `tab controls a missing panel: ${tab[1]}`);
  }
  assert.ok((home.match(/data-copy="/g) ?? []).length >= 15, 'copy buttons missing');
  for (const filter of ['all', 'tier:RUNTIME_VERIFIED', 'tier:INTEGRATION_TESTED', 'tier:FIXTURE_TESTED', 'category:coding', 'category:autonomous']) {
    assert.ok(home.includes(`data-filter="${filter}"`), `filter missing: ${filter}`);
  }
  assert.match(home, /<dialog\b[^>]*data-search/);
  assert.ok(existsSync(join(DIST, 'pagefind/pagefind.js')), 'search index was not built');
  const entry = readJson(join(DIST, 'pagefind/pagefind-entry.json'));
  const indexed = Object.values(entry.languages).reduce((sum, lang) => sum + lang.page_count, 0);
  assert.equal(indexed, DOC_PAGES.length, 'search index should contain exactly the documentation pages');
});

/* ------------------------------------------------------------ copy style */

test('site copy avoids em dashes outside recorded output', () => {
  for (const [file, html] of pages) {
    const text = proseOf(html.replace(/<code\b[\s\S]*?<\/code>/g, ' '));
    assert.doesNotMatch(text, /\u2014| -- /, `${file}: em dash or double hyphen in prose`);
  }
});

/* -------------------------------------------------------- docs pipeline */

test('documentation links are rewritten for the site', () => {
  assert.deepEqual(rewriteHref('../security/README.md'), { href: '/docs/security', external: false });
  assert.deepEqual(rewriteHref('../commands/README.md#exit-codes'), { href: '/docs/cli#exit-codes', external: false });
  assert.deepEqual(rewriteHref('../../SECURITY.md'), { href: 'https://github.com/Shanmukh-l33t/skillporter/blob/main/SECURITY.md', external: true });
  assert.deepEqual(rewriteHref('#drift'), { href: '#drift', external: false });
  assert.deepEqual(rewriteHref('https://example.com/a'), { href: 'https://example.com/a', external: true });

  const out = transformDocHtml('<h1 id="t">Title</h1>\n<p><a href="../mcp/README.md">MCP</a></p><table><tr><td>x</td></tr></table>');
  assert.ok(!out.includes('<h1'));
  assert.ok(out.includes('href="/docs/mcp"'));
  assert.ok(out.includes('<div class="table-scroll"'));

  for (const [file, html] of pages) {
    const leftovers = [...html.matchAll(/href="([^"]*README\.md[^"]*)"/g)]
      .map((m) => m[1])
      .filter((href) => !href.startsWith('https://github.com/Shanmukh-l33t/skillporter/edit/main/docs/'));
    assert.deepEqual(leftovers, [], `${file}: unrewritten Markdown link`);
  }
});

test('all local asset references and host configs exist in the build', () => {
  for (const [file, html] of pages) {
    for (const match of html.matchAll(/\b(?:src|srcset|href)="([^"]+)"/g)) {
      const parts = match[0].startsWith('srcset=') ? decode(match[1]).split(',') : [decode(match[1])];
      for (const raw of parts) {
        const url = raw.trim().split(/\s+/)[0];
        if (!url || /^(?:https?:|mailto:|data:|#|\/\/)/.test(url)) continue;
        const clean = url.split('#')[0].split('?')[0];
        if (!clean) continue;
        assert.ok(resolveRoute(clean), `${file}: missing local asset or route ${url}`);
      }
    }
  }
  assert.ok(existsSync(join(DIST, '_headers')), 'Cloudflare/Netlify _headers missing from dist/');
  const vercel = readJson(join(WEBSITE, 'vercel.json'));
  assert.equal(vercel.cleanUrls, true);
  assert.equal(vercel.trailingSlash, false);
  assert.equal(readFileSync(join(WEBSITE, '.nvmrc'), 'utf8').trim(), '24');
  assert.equal(readFileSync(join(WEBSITE, '.node-version'), 'utf8').trim(), '24');
});
