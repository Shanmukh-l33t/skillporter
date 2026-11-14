import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { DIR_TO_SLUG, DOC_PAGES } from './data/docs.mjs';

// Documentation is rendered straight from the repository's top-level docs/
// directory. The manifest in src/data/docs.mjs selects and orders the pages.
const docs = defineCollection({
  loader: glob({
    base: '../docs',
    pattern: DOC_PAGES.map((page) => `${page.dir}/README.md`),
    generateId: ({ entry }) => {
      const dir = entry.split('/')[0] ?? entry;
      return DIR_TO_SLUG.get(dir) ?? dir;
    },
  }),
});

export const collections = { docs };
