// @ts-check
import { defineConfig } from 'astro/config';
import { skillporterLightTheme, skillporterTheme } from './src/lib/shiki-theme.mjs';

// Static, host-agnostic build. Pages are emitted as `/docs/cli.html` (and
// `/docs/index.html`) and served at `/docs/cli`, matching the canonical URLs.
export default defineConfig({
  site: 'https://skillporter.dev',
  output: 'static',
  trailingSlash: 'never',
  build: {
    format: 'preserve',
    inlineStylesheets: 'auto',
  },
  compressHTML: true,
  markdown: {
    // Keep flags verbatim: smartypants rewrites "--check" into an en dash,
    // which breaks both the visible text and the structured data that quotes it.
    smartypants: false,
    syntaxHighlight: 'shiki',
    shikiConfig: {
      themes: {
        light: skillporterLightTheme,
        dark: skillporterTheme,
      },
      wrap: false,
    },
  },
  vite: {
    server: {
      fs: {
        // The documentation source lives in the repository's top-level docs/.
        allow: ['..'],
      },
    },
  },
});
