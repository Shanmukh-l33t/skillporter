#!/usr/bin/env node
/**
 * Submit every URL in the live sitemap to IndexNow.
 *
 * IndexNow is a shared endpoint: a submission is forwarded to Bing, Yandex,
 * Seznam and Naver. It needs no account, only a key file served from the site
 * root, which lives in public/<key>.txt and is copied into the build.
 *
 * Usage:
 *   node scripts/indexnow.mjs                 # submit everything in the sitemap
 *   node scripts/indexnow.mjs --dry-run       # print the payload only
 *   node scripts/indexnow.mjs --url /blog     # submit one path
 */
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEBSITE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOST = 'www.skillporter.dev';
const ENDPOINT = 'https://api.indexnow.org/indexnow';
const SITEMAP = `https://${HOST}/sitemap.xml`;

const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const single = args.indexOf('--url') >= 0 ? args[args.indexOf('--url') + 1] : undefined;

function findKey() {
  const candidates = readdirSync(join(WEBSITE, 'public')).filter((name) => /^[0-9a-f]{32}\.txt$/.test(name));
  if (candidates.length !== 1) throw new Error(`expected exactly one IndexNow key file in public/, found ${candidates.length}`);
  const file = candidates[0];
  return { key: readFileSync(join(WEBSITE, 'public', file), 'utf8').trim(), keyLocation: `https://${HOST}/${file}` };
}

async function urlsFromSitemap() {
  const response = await fetch(SITEMAP, { headers: { 'user-agent': 'skillporter-indexnow/1.0' } });
  if (!response.ok) throw new Error(`sitemap fetch failed: ${response.status} ${SITEMAP}`);
  const xml = await response.text();
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
}

const { key, keyLocation } = findKey();
const urlList = single ? [`https://${HOST}${single}`] : await urlsFromSitemap();
const payload = { host: HOST, key, keyLocation, urlList };

if (dryRun) {
  console.log(JSON.stringify(payload, null, 2));
  process.exit(0);
}

const response = await fetch(ENDPOINT, {
  method: 'POST',
  headers: { 'content-type': 'application/json; charset=utf-8' },
  body: JSON.stringify(payload),
});
const text = (await response.text()).trim();
console.log(`IndexNow: ${response.status} ${response.statusText} for ${urlList.length} URLs${text ? ` :: ${text}` : ''}`);
if (!response.ok) process.exit(1);