/**
 * Client-side behaviour for skillporter.dev.
 * Everything here is progressive: the pages are readable and navigable with
 * JavaScript disabled. No framework, no third-party runtime.
 */

const $ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) => root.querySelector<T>(sel);
const $$ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) =>
  Array.from(root.querySelectorAll<T>(sel));

/* ------------------------------------------------------------------ theme */

function initTheme(): void {
  const buttons = $$<HTMLButtonElement>('[data-theme-toggle]');
  if (!buttons.length) return;
  let switchTimer = 0;

  const apply = (mode: 'light' | 'dark', persist = false) => {
    if (persist) {
      document.documentElement.setAttribute('data-theme-switching', '');
      window.clearTimeout(switchTimer);
      switchTimer = window.setTimeout(() => document.documentElement.removeAttribute('data-theme-switching'), 250);
    }
    document.documentElement.dataset.theme = mode;
    const meta = $<HTMLMetaElement>('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', mode === 'dark' ? '#070D19' : '#F5F6FA');
    const nextLabel = mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    for (const button of buttons) {
      button.setAttribute('aria-label', nextLabel);
      button.setAttribute('title', nextLabel);
    }
    if (persist) {
      try {
        localStorage.setItem('skillporter-theme', mode);
      } catch {
        // Private browsing or blocked storage: keep session state in DOM.
      }
    }
  };

  const current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  apply(current, false);

  for (const button of buttons) {
    button.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      apply(next, true);
    });
  }
}

/* ----------------------------------------------------------------- header */

function initHeader(): void {
  const header = $('[data-header]');
  if (!header) return;
  const update = () => header.setAttribute('data-scrolled', String(window.scrollY > 8));
  update();
  window.addEventListener('scroll', update, { passive: true });

  const toggle = $<HTMLButtonElement>('[data-menu-toggle]');
  const menu = $('[data-mobile-menu]');
  if (!toggle || !menu) return;

  const setOpen = (open: boolean, restoreFocus = false) => {
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    header.setAttribute('data-menu-open', String(open));
    menu.hidden = !open;
    document.documentElement.style.overflow = open ? 'hidden' : '';
    if (open) $<HTMLAnchorElement>('a', menu)?.focus();
    else if (restoreFocus) toggle.focus();
  };

  toggle.addEventListener('click', () => setOpen(toggle.getAttribute('aria-expanded') !== 'true'));
  menu.addEventListener('click', (event) => {
    if ((event.target as Element).closest('a')) setOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') setOpen(false, true);
  });
  window.matchMedia('(min-width: 941px)').addEventListener('change', (mq) => {
    if (mq.matches) setOpen(false);
  });
}

/* Highlight the nav item for the home-page section currently in view. */
function initSectionSpy(): void {
  const links = $$<HTMLAnchorElement>('[data-nav-section]');
  if (!links.length || !('IntersectionObserver' in window)) return;
  const byId = new Map<string, HTMLAnchorElement>();
  const sections: HTMLElement[] = [];
  for (const link of links) {
    const id = link.dataset.navSection!;
    const section = document.getElementById(id);
    if (section) {
      byId.set(id, link);
      sections.push(section);
    }
  }
  if (!sections.length) return;

  const visible = new Set<string>();
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) visible.add(entry.target.id);
        else visible.delete(entry.target.id);
      }
      const current = sections.find((s) => visible.has(s.id))?.id;
      for (const [id, link] of byId) {
        if (id === current) link.setAttribute('aria-current', 'true');
        else link.removeAttribute('aria-current');
      }
    },
    { rootMargin: '-35% 0px -55% 0px' },
  );
  sections.forEach((section) => observer.observe(section));
}

/* ------------------------------------------------------------------- tabs */

function initTabs(): void {
  for (const group of $$('[data-tabs]')) {
    const tablist = $<HTMLElement>('.tabs', group);
    const tabs = $$<HTMLButtonElement>('[role="tab"]', group);
    let glide: HTMLSpanElement | null = null;
    if (tablist && tabs.length) {
      glide = document.createElement('span');
      glide.className = 'tabs__glide';
      glide.setAttribute('aria-hidden', 'true');
      tablist.appendChild(glide);
    }

    const syncGlide = (tab: HTMLButtonElement) => {
      if (!tablist || !glide) return;
      const pad = parseFloat(getComputedStyle(tab).paddingLeft) || 0;
      const x = tab.offsetLeft + pad;
      const w = Math.max(12, tab.offsetWidth - pad * 2);
      tablist.style.setProperty('--glide-x', `${x}px`);
      tablist.style.setProperty('--glide-w', `${w}px`);
      tablist.dataset.glideReady = 'true';
    };

    const initial = tabs.find((t) => t.getAttribute('aria-selected') === 'true') ?? tabs[0];
    if (initial) syncGlide(initial);
    if (tablist && 'ResizeObserver' in window) {
      new ResizeObserver(() => {
        const cur = tabs.find((t) => t.getAttribute('aria-selected') === 'true');
        if (cur) syncGlide(cur);
      }).observe(tablist);
    }

    const select = (tab: HTMLButtonElement, focus = false) => {
      for (const other of tabs) {
        const selected = other === tab;
        other.setAttribute('aria-selected', String(selected));
        other.tabIndex = selected ? 0 : -1;
        const panel = document.getElementById(other.getAttribute('aria-controls') ?? '');
        if (panel) {
          panel.hidden = !selected;
          if (selected) {
            panel.dataset.entering = 'true';
            panel.addEventListener('animationend', () => delete panel.dataset.entering, { once: true });
          } else {
            delete panel.dataset.entering;
          }
        }
      }
      syncGlide(tab);
      if (focus) tab.focus();
      tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    };
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => select(tab));
      tab.addEventListener('keydown', (event) => {
        let next: number | null = null;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = tabs.length - 1;
        if (next === null) return;
        event.preventDefault();
        select(tabs[next]!, true);
      });
    });
  }
}

/* ------------------------------------------------------------------- copy */

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    area.remove();
    return ok;
  }
}

function bindCopy(button: HTMLButtonElement, getText: () => string): void {
  const label = $('[data-copy-label]', button) ?? button;
  const idle = label.textContent ?? 'Copy';
  let timer = 0;
  button.addEventListener('click', async () => {
    const ok = await writeClipboard(getText());
    button.dataset.copied = String(ok);
    label.textContent = ok ? 'Copied' : 'Failed';
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      delete button.dataset.copied;
      label.textContent = idle;
    }, 1800);
  });
}

function initCopy(): void {
  for (const button of $$<HTMLButtonElement>('[data-copy]')) {
    bindCopy(button, () => button.dataset.copy ?? '');
  }
  // Documentation code blocks get a copy button at runtime.
  for (const pre of $$<HTMLPreElement>('.prose pre')) {
    const wrapper = document.createElement('div');
    wrapper.className = 'codeblock';
    pre.replaceWith(wrapper);
    wrapper.appendChild(pre);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'copy codeblock__copy';
    button.setAttribute('aria-label', 'Copy code');
    button.innerHTML = '<span data-copy-label>Copy</span>';
    wrapper.appendChild(button);
    bindCopy(button, () => (pre.textContent ?? '').replace(/\n$/, ''));
  }
}

/* --------------------------------------------------------- harness matrix */

function initMatrix(): void {
  const matrix = $('[data-matrix]');
  if (!matrix) return;
  const buttons = $$<HTMLButtonElement>('[data-filter]', matrix);
  const rows = $$<HTMLTableRowElement>('tbody tr', matrix);
  const status = $('[data-matrix-status]', matrix);

  const apply = (filter: string) => {
    const [kind, value] = filter.split(':');
    let shown = 0;
    for (const row of rows) {
      const match =
        filter === 'all' ||
        (kind === 'tier' && row.dataset.tier === value) ||
        (kind === 'category' && row.dataset.category === value);
      row.hidden = !match;
      if (match) {
        row.style.setProperty('--row-delay', `${Math.min(shown * 16, 160)}ms`);
        row.dataset.entering = 'true';
        row.addEventListener('animationend', () => delete row.dataset.entering, { once: true });
        shown += 1;
      } else {
        delete row.dataset.entering;
      }
    }
    for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.filter === filter));
    if (status) status.textContent = `Showing ${shown} of ${rows.length} harnesses.`;
  };
  for (const button of buttons) button.addEventListener('click', () => apply(button.dataset.filter ?? 'all'));
}

/* ----------------------------------------------------------------- search */

interface PagefindSubResult {
  title: string;
  url: string;
  excerpt: string;
}
interface PagefindData {
  url: string;
  excerpt: string;
  meta: { title?: string; section?: string };
  sub_results?: PagefindSubResult[];
}
interface PagefindApi {
  init(): Promise<void>;
  options(options: Record<string, unknown>): Promise<void>;
  debouncedSearch(
    query: string,
    options?: Record<string, unknown>,
    debounceMs?: number,
  ): Promise<{ results: { id: string; data(): Promise<PagefindData> }[] } | null>;
}

const MAX_RESULTS = 8;

/** Pagefind excerpts start with the heading text; the title is already shown above. */
function trimExcerpt(excerpt: string, title: string): string {
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '(?:\\s|</?mark>)+');
  return excerpt.replace(new RegExp(`^(?:<mark>)?${escaped}[.:]?(?:</mark>)?[.:]?\\s*`, 'i'), '');
}

/** Pagefind indexes the built files; the site serves them without `.html`. */
function cleanUrl(url: string): string {
  return url.replace(/\/index\.html(?=$|[#?])/, '').replace(/\.html(?=$|[#?])/, '') || '/';
}

function initSearch(): void {
  const dialog = $<HTMLDialogElement>('[data-search]');
  const input = $<HTMLInputElement>('[data-search-input]');
  const list = $<HTMLUListElement>('[data-search-results]');
  const status = $('[data-search-status]');
  if (!dialog || !input || !list || !status) return;

  const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
  for (const kbd of $$('[data-search-kbd]')) kbd.textContent = isMac ? '⌘K' : 'Ctrl K';

  let pagefind: PagefindApi | null = null;
  let loading: Promise<PagefindApi | null> | null = null;
  let active = -1;
  let token = 0;

  const load = () => {
    loading ??= (async () => {
      try {
        const path = '/pagefind/pagefind.js';
        const mod = (await import(/* @vite-ignore */ path)) as PagefindApi;
        await mod.options({ excerptLength: 22 });
        await mod.init();
        pagefind = mod;
        return mod;
      } catch {
        status.textContent = 'Search is available on the built site. Run "npm run build" and "npm run preview".';
        return null;
      }
    })();
    return loading;
  };

  const options = () => $$<HTMLAnchorElement>('.search-result', list);
  const setActive = (index: number) => {
    const items = options();
    active = items.length ? (index + items.length) % items.length : -1;
    items.forEach((item, i) => {
      item.setAttribute('aria-selected', String(i === active));
      if (i === active) {
        input.setAttribute('aria-activedescendant', item.id);
        item.scrollIntoView({ block: 'nearest' });
      }
    });
    if (active === -1) input.removeAttribute('aria-activedescendant');
  };

  const render = (items: { crumb: string; title: string; url: string; excerpt: string }[], query: string) => {
    list.replaceChildren();
    items.forEach((item, i) => {
      const li = document.createElement('li');
      li.setAttribute('role', 'presentation');
      const a = document.createElement('a');
      a.className = 'search-result';
      a.id = `search-result-${i}`;
      a.href = item.url;
      a.setAttribute('role', 'option');
      a.setAttribute('aria-selected', 'false');
      const crumb = document.createElement('span');
      crumb.className = 'search-result__crumb';
      crumb.textContent = item.crumb;
      const title = document.createElement('span');
      title.className = 'search-result__title';
      title.textContent = item.title;
      const excerpt = document.createElement('span');
      excerpt.className = 'search-result__excerpt';
      // Pagefind returns its own escaped excerpt with <mark> around matches.
      excerpt.innerHTML = item.excerpt;
      a.append(crumb, title, excerpt);
      a.addEventListener('mousemove', () => setActive(i));
      li.appendChild(a);
      list.appendChild(li);
    });
    input.setAttribute('aria-expanded', String(items.length > 0));
    if (!items.length) {
      status.textContent = `No results for "${query}". Try a command name, a flag or a finding code.`;
      setActive(-1);
    } else {
      status.textContent = `${items.length} result${items.length === 1 ? '' : 's'}`;
      setActive(0);
    }
  };

  const search = async () => {
    const query = input.value.trim();
    const mine = ++token;
    if (!query) {
      list.replaceChildren();
      input.setAttribute('aria-expanded', 'false');
      status.textContent = 'Type to search the documentation.';
      setActive(-1);
      return;
    }
    const api = pagefind ?? (await load());
    if (!api || mine !== token) return;
    const response = await api.debouncedSearch(query, {}, 120);
    if (response === null || mine !== token) return;
    const pages = await Promise.all(response.results.slice(0, MAX_RESULTS).map((result) => result.data()));
    if (mine !== token) return;

    const items: { crumb: string; title: string; url: string; excerpt: string }[] = [];
    for (const page of pages) {
      const pageTitle = page.meta.title ?? 'Documentation';
      const subs = (page.sub_results ?? []).filter((sub) => sub.excerpt.includes('<mark>'));
      if (!subs.length) {
        items.push({ crumb: 'Docs', title: pageTitle, url: cleanUrl(page.url), excerpt: trimExcerpt(page.excerpt, pageTitle) });
        continue;
      }
      for (const sub of subs.slice(0, 2)) {
        const isPage = sub.title === pageTitle || !sub.url.includes('#');
        items.push({
          crumb: isPage ? 'Docs' : `Docs / ${pageTitle}`,
          title: isPage ? pageTitle : sub.title,
          url: cleanUrl(sub.url),
          excerpt: trimExcerpt(sub.excerpt, sub.title),
        });
      }
    }
    render(items.slice(0, MAX_RESULTS), query);
  };

  const open = () => {
    if (dialog.open) return;
    dialog.showModal();
    input.focus();
    input.select();
    void load();
  };
  const close = () => dialog.open && dialog.close();

  for (const trigger of $$('[data-search-open]')) trigger.addEventListener('click', open);
  $('[data-search-close]', dialog)?.addEventListener('click', close);
  $('[data-search-form]', dialog)?.addEventListener('submit', (event) => event.preventDefault());
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) close();
  });
  list.addEventListener('click', (event) => {
    if ((event.target as Element).closest('a')) close();
  });

  input.addEventListener('input', () => void search());
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive(active + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive(active - 1);
    } else if (event.key === 'Escape') {
      // <dialog> closes on Escape natively; handled here too so it never depends on it.
      event.preventDefault();
      close();
    } else if (event.key === 'Enter') {
      const item = options()[active];
      if (item) {
        event.preventDefault();
        close();
        window.location.assign(item.href);
      }
    }
  });

  document.addEventListener('keydown', (event) => {
    const key = event.key.toLowerCase();
    if ((event.metaKey || event.ctrlKey) && key === 'k') {
      event.preventDefault();
      if (dialog.open) close();
      else open();
      return;
    }
    const target = event.target as HTMLElement | null;
    const typing = target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
    if (event.key === '/' && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      open();
    }
  });
}

/* ------------------------------------------------------------------- docs */

function initDocs(): void {
  const toggle = $<HTMLButtonElement>('[data-docs-nav-toggle]');
  const nav = $('[data-docs-nav]');
  if (toggle && nav) {
    const setOpen = (open: boolean) => {
      toggle.setAttribute('aria-expanded', String(open));
      nav.dataset.open = String(open);
    };
    toggle.addEventListener('click', () => setOpen(toggle.getAttribute('aria-expanded') !== 'true'));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  const tocLinks = $$<HTMLAnchorElement>('[data-toc] a');
  if (!tocLinks.length || !('IntersectionObserver' in window)) return;
  const targets = tocLinks
    .map((link) => document.getElementById(decodeURIComponent(link.hash.slice(1))))
    .filter((el): el is HTMLElement => el !== null);
  const setCurrent = (id: string) => {
    for (const link of tocLinks) {
      if (decodeURIComponent(link.hash.slice(1)) === id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
  };
  const observer = new IntersectionObserver(
    (entries) => {
      const hit = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (hit) setCurrent(hit.target.id);
    },
    { rootMargin: '-80px 0px -70% 0px' },
  );
  targets.forEach((target) => observer.observe(target));
}

/* --------------------------------------------------------- scroll reveal */

function initReveal(): void {
  if (!('IntersectionObserver' in window)) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const targets = $$(
    '.section-head, .problems li, .answer, .feature, .steps li, .matrix__legend, .sec-grid, .sec-lower, .repro, .cmds li, .links li, .closing',
  );
  if (!targets.length) return;

  const viewportH = window.innerHeight || document.documentElement.clientHeight;
  const pending: HTMLElement[] = [];

  for (const el of targets) {
    const rect = el.getBoundingClientRect();
    if (rect.top <= viewportH * 0.92) continue;
    el.dataset.reveal = 'pending';
    const parent = el.parentElement;
    if (parent && /^(OL|UL)$/.test(parent.tagName)) {
      const idx = Array.from(parent.children).indexOf(el);
      if (idx > 0) el.style.setProperty('--reveal-delay', `${Math.min(idx * 45, 220)}ms`);
    }
    pending.push(el);
  }
  if (!pending.length) return;

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        (entry.target as HTMLElement).dataset.reveal = 'in';
        observer.unobserve(entry.target);
      }
    },
    { threshold: 0.08, rootMargin: '0px 0px -32px 0px' },
  );
  pending.forEach((el) => observer.observe(el));
}

/* -------------------------------------------------------- hero spotlight */

function initHeroSpotlight(): void {
  const hero = $<HTMLElement>('.hero');
  if (!hero) return;
  if (!window.matchMedia('(hover: hover)').matches) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let raf = 0;
  let px = 26;
  let py = 24;
  hero.addEventListener(
    'pointermove',
    (event) => {
      const rect = hero.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      px = Math.round(((event.clientX - rect.left) / rect.width) * 100);
      py = Math.round(((event.clientY - rect.top) / rect.height) * 100);
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        hero.style.setProperty('--spot-x', `${px}%`);
        hero.style.setProperty('--spot-y', `${py}%`);
      });
    },
    { passive: true },
  );
}

initTheme();
initHeader();
initSectionSpy();
initTabs();
initCopy();
initMatrix();
initSearch();
initDocs();
initReveal();
initHeroSpotlight();
