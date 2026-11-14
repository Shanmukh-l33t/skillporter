# skillporter.dev

The official Skillporter website and documentation. It is a static site: no server, no database, no runtime dependency on the Python package.

- Canonical domain: `https://skillporter.dev`
- Framework: [Astro](https://astro.build) with TypeScript, static output
- Search: [Pagefind](https://pagefind.app), built at compile time, queried in the browser
- Fonts: Geist and Geist Mono, self-hosted from `@fontsource-variable`

## Requirements

- Node.js 22.23.4 or newer (24 LTS recommended)
- Python 3.9 or newer, to regenerate data from the CLI sources
- Pillow, only if you regenerate brand assets

## Commands

Run these inside `website/`.

| Command | What it does |
|---|---|
| `npm ci` | Install the pinned build dependencies. |
| `npm run dev` | Start the development server. Search is not available in dev mode. |
| `npm run build` | Build the site into `dist/` and build the search index. |
| `npm run preview` | Serve `dist/` locally with the same clean URLs a static host uses. |
| `npm run data` | Regenerate `src/data/*.json` and the harness table in `docs/harnesses/README.md` from the Python sources. |
| `npm run data:check` | Fail if the generated data is out of date. |
| `npm run typecheck` | Type-check Astro and TypeScript files. |
| `npm test` | Run the content and integrity tests against `dist/`. |
| `npm run verify` | `data:check`, `typecheck`, `build` and `test`, in that order. CI runs this. |

## Where content comes from

Nothing about the product is typed into the site by hand if it can be read from the repository.

| Content | Source of truth | How it reaches the site |
|---|---|---|
| Harness names, paths, support type, verification tier, vendor links, counts | `skillporter/harnesses.py` | `scripts/generate_site_data.py` writes `src/data/harnesses.json` |
| CLI commands and flags | `skillporter/cli.py` (the real `argparse` parser) | `scripts/generate_site_data.py` writes `src/data/cli.json` |
| Version, license, release and installer URLs | `skillporter/__init__.py`, `package.json` | `scripts/generate_site_data.py` writes `src/data/release.json` |
| Terminal output | The real CLI, run in a throwaway workspace | `scripts/record_cli_output.py` writes `src/data/recordings/` |
| Lockfile example | The lockfile the CLI wrote during recording | `src/data/recordings/skillporter.lock.json` |
| Documentation pages | `docs/<topic>/README.md` in the repository root | Astro content collection, see `src/content.config.ts` |
| Documentation order and URLs | `src/data/docs.mjs` | Imported by pages and the sitemap |

`npm run data:check` runs in CI. If someone changes the adapter registry or the CLI without regenerating, the build fails. The home page also checks every command it shows against `cli.json` at build time.

### Updating after a release

```bash
python3 website/scripts/generate_site_data.py
python3 website/scripts/record_cli_output.py   # needs network access and the new CLI
cd website && npm run verify
```

Then update the pinned SHA-256 in `docs/installation/README.md` and `docs/ci/README.md` to the new `skillporter.pyz` digest, and the matching assertion in `tests/site.test.mjs`.

## Documentation

The Markdown under `docs/` is the single source for both GitHub and the website. Pages use GitHub-relative links such as `../security/README.md`. At build time `src/lib/docs-html.mjs` rewrites those to site routes, sends links to other repository files to GitHub, drops the leading `# Title` (the layout renders it) and wraps tables so they scroll on small screens.

To add a page: create `docs/<dir>/README.md`, then add an entry to `src/data/docs.mjs`.

## Brand

- `public/brand/skillporter-logo.png` is the approved logo, copied byte for byte from the owner's file. Its SHA-256 is stored next to it and checked by the tests. Do not edit or replace it without the owner's approval.
- `scripts/make_brand_assets.py` derives every other asset from that file: it removes the flat background, crops the lockup and the bridge mark out of the original pixels and scales them. It never redraws the logo.
- Colour tokens live in `src/styles/global.css` and match the official palette. A test checks the nine official values.

| Asset | Use |
|---|---|
| `brand/skillporter-lockup.webp`, `.png` | Header, footer and documentation logo |
| `brand/skillporter-mark.webp`, `.png` | Bridge mark alone |
| `favicon.ico`, `favicon-32.png`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png` | Favicons and touch icons |
| `brand/skillporter-social.png` | Open Graph and X card image, 1200 by 630 |

## Structure

```text
website/
  astro.config.mjs        site URL, static output, Markdown highlighting
  public/                 logo, icons, robots.txt, web manifest
  scripts/                data generator, CLI recorder, brand assets, local server
  src/
    components/           header, footer, search, install panel, terminal, matrix
    data/                 generated JSON, recordings, docs manifest, site constants
    layouts/              Base (every page) and Docs (documentation pages)
    lib/                  docs HTML post-processing, terminal rendering, code theme
    pages/                index, docs index, docs/[slug], 404, sitemap.xml
    scripts/ui.ts         tabs, copy, filters, search, menus
    styles/global.css     design tokens and shared styles
  tests/site.test.mjs     content, link, SEO, accessibility and accuracy checks
```

## Deployment

The build output is the `website/dist/` directory. Any static host can serve it. Nothing here deploys the site or changes DNS; that is an owner decision.

**Build settings**

| Setting | Value |
|---|---|
| Root directory | `website` |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Output directory | `dist` |
| Node version | 24 |

The build needs only Node. `.nvmrc` and `.node-version` pin Node 24 for hosts that read them. Python is needed for `npm run verify` and for regenerating data, not for `npm run build`.

**URL behaviour and headers**

Pages are emitted as files: `/docs/cli` is `dist/docs/cli.html`, and `/docs` is `dist/docs/index.html`. Cloudflare Pages, Netlify and GitHub Pages serve extensionless clean URLs and `dist/404.html` by default, and `vercel.json` enables `"cleanUrls": true` and `"trailingSlash": false` for Vercel. `public/_headers` (copied to `dist/_headers`) and `vercel.json` also configure immutable caching for `/_astro/*` and baseline security headers.

**Domain**

1. Add `skillporter.dev` as a custom domain in the host's dashboard.
2. Create the DNS records the host asks for. For an apex domain that is usually an `A`/`AAAA` record or an `ALIAS`/flattened `CNAME`; add a `www` record if you want it.
3. Redirect `www.skillporter.dev` to `skillporter.dev` so one hostname is canonical. Every page already declares `https://skillporter.dev/...` as its canonical URL.
4. Enforce HTTPS. `.dev` is on the HSTS preload list, so browsers will not load the site over plain HTTP.

**After the first deploy**

- Open `https://skillporter.dev/sitemap.xml` and `https://skillporter.dev/robots.txt`.
- Check a documentation URL without a trailing slash, for example `/docs/cli`.
- Search for a term in the documentation to confirm `/pagefind/` is being served.
- Paste the home page URL into a social card validator to confirm the preview image.

**Recommended headers** (optional, set at the host)

```text
Cache-Control: public, max-age=31536000, immutable      for /_astro/*
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
```

## Checks before merging

```bash
cd website
npm ci
npm run verify
```

See `EVIDENCE.md` for where each product claim on the site comes from.
