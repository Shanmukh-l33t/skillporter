import cliData from './cli.json';
import harnessData from './harnesses.json';
import release from './release.json';

export { cliData, harnessData, release };

export const SITE = {
  name: 'Skillporter',
  /** How people type the brand when they use two words. */
  alternateName: 'Skill Porter',
  url: 'https://www.skillporter.dev',
  tagline: 'One skill. Every agent.',
  positioning: 'Skill Porter is the package manager for AI agent skills.',
  description:
    'Install, synchronize, pin, inspect and manage AI agent skills across multiple harnesses through one consistent workflow.',
  socialImage: '/brand/skillporter-social.png',
} as const;

export const LINKS = {
  repo: release.repository,
  release: release.release_url,
  issues: `${release.repository}/issues`,
  changelog: `${release.repository}/blob/main/CHANGELOG.md`,
  security: `${release.repository}/blob/main/SECURITY.md`,
  advisories: `${release.repository}/security/advisories/new`,
  contributing: `${release.repository}/blob/main/CONTRIBUTING.md`,
  license: `${release.repository}/blob/main/LICENSE`,
  pypi: `https://pypi.org/project/${release.pypi_package}/`,
  npm: `https://www.npmjs.com/package/${release.npm_package}`,
} as const;

export interface NavItem {
  label: string;
  href: string;
  /** Section id on the home page, used for scroll-spy. */
  section?: string;
  external?: boolean;
}

export const PRIMARY_NAV: NavItem[] = [
  { label: 'Product', href: '/#product', section: 'product' },
  { label: 'Features', href: '/#features', section: 'features' },
  { label: 'Harnesses', href: '/#harnesses', section: 'harnesses' },
  { label: 'Security', href: '/#security', section: 'security' },
  { label: 'Documentation', href: '/docs' },
  { label: 'GitHub', href: release.repository, external: true },
];

export type Harness = (typeof harnessData.harnesses)[number];

export const VERIFICATION_TIERS = [
  {
    id: 'RUNTIME_VERIFIED',
    label: 'Runtime verified',
    definition: 'Installation and live discovery verified inside the running harness.',
  },
  {
    id: 'INTEGRATION_TESTED',
    label: 'Integration tested',
    definition: 'End-to-end multi-harness workflows verified in automated integration suites.',
  },
  {
    id: 'FIXTURE_TESTED',
    label: 'Fixture tested',
    definition: 'Adapter lifecycle verified against automated fixtures and official vendor documentation.',
  },
  {
    id: 'DOCUMENTATION_VERIFIED',
    label: 'Documentation verified',
    definition: 'Paths confirmed against vendor documentation, without automated fixture execution.',
  },
] as const;

export const SUPPORT_TYPES = [
  { id: 'NATIVE', definition: 'Reads SKILL.md directly.' },
  { id: 'COMPATIBLE', definition: 'Reads SKILL.md through a documented compatibility path.' },
  { id: 'ADAPTED', definition: 'Needs a controlled conversion, such as a rules file.' },
] as const;

export function verificationCount(id: string): number {
  return (harnessData.counts.verification as Record<string, number>)[id] ?? 0;
}

export function tierLabel(id: string): string {
  return VERIFICATION_TIERS.find((tier) => tier.id === id)?.label ?? id;
}
