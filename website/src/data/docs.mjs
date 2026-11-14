/**
 * Documentation manifest.
 *
 * The Markdown itself lives in the repository's top-level `docs/` directory so
 * GitHub and skillporter.dev render the same source. This file only decides
 * which of those documents are published, under which URL, and in what order.
 * Keep it dependency-free: `astro.config.mjs` and the rehype plugin import it.
 */

/**
 * @typedef {object} DocPage
 * @property {string} slug         URL segment: /docs/<slug>
 * @property {string} dir          Source directory: docs/<dir>/README.md
 * @property {string} title
 * @property {string} description  Used for meta description and listings.
 */

/**
 * @typedef {object} DocSection
 * @property {string} title
 * @property {DocPage[]} pages
 */

/** @type {DocSection[]} */
export const DOC_SECTIONS = [
  {
    title: 'Start',
    pages: [
      {
        slug: 'getting-started',
        dir: 'getting-started',
        title: 'Getting started',
        description: 'Run the demo, install the CLI, add your first skill and check the workspace.',
      },
      {
        slug: 'installation',
        dir: 'installation',
        title: 'Installation',
        description: 'Every install channel, and how the standalone installer verifies what it downloads.',
      },
      {
        slug: 'quick-start',
        dir: 'quick-start',
        title: 'Quick start',
        description: 'The full lifecycle in one page: install, scan, pin, detect drift and roll back.',
      },
    ],
  },
  {
    title: 'Using Skillporter',
    pages: [
      {
        slug: 'cli',
        dir: 'commands',
        title: 'CLI reference',
        description: 'Every command, option and exit code in the skillporter CLI.',
      },
      {
        slug: 'skill-management',
        dir: 'skill-management',
        title: 'Skill management',
        description: 'Sources, strategies, scopes, removal, updates and how installs stay consistent.',
      },
      {
        slug: 'synchronization',
        dir: 'synchronization',
        title: 'Synchronization',
        description: 'How sync reconciles a workspace and how content drift is detected and resolved.',
      },
      {
        slug: 'lockfiles',
        dir: 'lockfiles',
        title: 'Lockfiles',
        description: 'What skillporter.lock records, what its pin states mean and what reproducible covers.',
      },
      {
        slug: 'configuration',
        dir: 'configuration',
        title: 'Configuration',
        description: 'The skillporter.yaml manifest, environment variables and local state.',
      },
      {
        slug: 'portability',
        dir: 'portability',
        title: 'Portability and profiles',
        description: 'Export and import .skillpack environments offline, compare setups and switch named profiles.',
      },
    ],
  },
  {
    title: 'Harnesses',
    pages: [
      {
        slug: 'harnesses',
        dir: 'harnesses',
        title: 'Harness compatibility',
        description: 'The 19 adapters, their install paths, support types and verification tiers.',
      },
      {
        slug: 'adapters',
        dir: 'adapters',
        title: 'Custom adapters',
        description: 'Describe an internal or unsupported harness with a declarative adapter.',
      },
    ],
  },
  {
    title: 'Security',
    pages: [
      {
        slug: 'security',
        dir: 'security',
        title: 'Security model',
        description: 'Trust boundaries, what Skillporter protects, and the limits of static analysis.',
      },
      {
        slug: 'security-scanning',
        dir: 'security-scanning',
        title: 'Security scanning',
        description: 'What the static assessment analyzes, finding codes, risk scoring and postures.',
      },
    ],
  },
  {
    title: 'Automation',
    pages: [
      {
        slug: 'mcp',
        dir: 'mcp',
        title: 'MCP integration',
        description: 'Run Skillporter as a read-only MCP server inside an agent harness.',
      },
      {
        slug: 'ci',
        dir: 'ci',
        title: 'CI and GitHub Actions',
        description: 'Validate, scan and verify lockfiles in CI, with SARIF and the GitHub Action.',
      },
    ],
  },
  {
    title: 'Project',
    pages: [
      {
        slug: 'troubleshooting',
        dir: 'troubleshooting',
        title: 'Troubleshooting',
        description: 'What MISSING, DRIFT, DUPLICATE, INVALID and blocked installs mean, and how to fix them.',
      },
      {
        slug: 'architecture',
        dir: 'architecture',
        title: 'Architecture',
        description: 'How the core, the commands, the adapters and the transaction engine fit together.',
      },
      {
        slug: 'contributing',
        dir: 'contributing',
        title: 'Contributing',
        description: 'Development setup, quality gates and the rules for adding a harness adapter.',
      },
    ],
  },
];

/** @type {DocPage[]} */
export const DOC_PAGES = DOC_SECTIONS.flatMap((section) => section.pages);

/** @type {Map<string, string>} source directory -> slug */
export const DIR_TO_SLUG = new Map(DOC_PAGES.map((page) => [page.dir, page.slug]));

export const GITHUB_REPO = 'https://github.com/Shanmukh-l33t/skillporter';
