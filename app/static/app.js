/* Theme switch glue for dis-system's nav-bar: remembers the theme (same key as dis-system's site). The stored
   theme is already applied by theme-init.js in <head>, before the first paint. */
(() => {
  const KEY = 'ds-theme';
  let stored = 'light';
  try { stored = localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'; } catch (e) { /* not persisted */ }
  document.documentElement.dataset.theme = stored;
  document.addEventListener('ds-nav-bar-theme-toggle', (e) => {
    document.documentElement.dataset.theme = e.detail.theme;
    try { localStorage.setItem(KEY, e.detail.theme); } catch (err) { /* not persisted */ }
  });
  // nav-bar starts offering "Dark"; if the stored theme is dark, flip it to offer "Light".
  if (stored === 'dark') {
    window.addEventListener('DOMContentLoaded', () => {
      const t = document.querySelector('.ds-nav-bar__theme-toggle');
      if (t) t.click();
      document.documentElement.dataset.theme = 'dark';
    });
  }
})();

/* Show a server message (import result, errors) as a dis-system toast; the text is read with textContent. */
window.addEventListener('DOMContentLoaded', () => {
  const flash = document.querySelector('[data-flash]');
  if (flash && window.dsToast) {
    window.dsToast.show({ message: flash.textContent.trim(), status: flash.dataset.flash || 'default', duration: 0 });
  }
});

/* Word list glue: selection gates the bulk buttons, the selected ids go into the practice form,
   header sort buttons reload the page sorted server-side, the search box filters the loaded rows.
   Ids are read from data attributes and written back as input values; nothing is inserted as HTML. */
window.addEventListener('DOMContentLoaded', () => {
  const table = document.querySelector('[data-word-table]');
  if (!table) return;
  const selectedRows = () => Array.from(table.querySelectorAll('.ds-table-row[data-selected="true"][data-word-id]'));
  const gated = () => Array.from(document.querySelectorAll('[data-needs-selection]'));

  const syncButtons = () => {
    const on = selectedRows().length > 0;
    gated().forEach((b) => {
      b.dataset.status = on ? 'active' : 'disabled';
      if (b.tagName === 'BUTTON') b.disabled = !on;
    });
  };
  // The chosen words survive moving between the pages (localStorage; ids only). A preset from the server
  // ("10 schwächste", "Letzte 20") replaces them. Ids of rows not loaded on this page are kept untouched.
  const KEY = 'wort-selected';
  const readStored = () => {
    try { const v = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(v) ? v.map(String) : []; } catch (e) { return []; }
  };
  const saveSelection = () => {
    try {
      const visible = new Set(Array.from(table.querySelectorAll('.ds-table-row[data-word-id]')).map((r) => r.dataset.wordId));
      const kept = readStored().filter((id) => !visible.has(id));
      localStorage.setItem(KEY, JSON.stringify([...kept, ...selectedRows().map((r) => r.dataset.wordId)]));
    } catch (e) { /* not persisted */ }
  };
  document.addEventListener('ds-table-row-select', () => { syncButtons(); saveSelection(); });
  if (selectedRows().length) {
    saveSelection();
  } else {
    const stored = new Set(readStored());
    const rows = Array.from(table.querySelectorAll('.ds-table-row[data-word-id]')).filter((r) => stored.has(r.dataset.wordId));
    rows.forEach((r) => r.setAttribute('data-selected', 'true'));
    if (rows.length) table.dispatchEvent(new CustomEvent('ds-table-row-select', { bubbles: true, detail: { selected: true, restored: true } }));
  }
  syncButtons();

  document.querySelector('[data-clear-selection]')?.addEventListener('click', () => {
    table.querySelectorAll('.ds-table-row[data-selected="true"]').forEach((r) => r.setAttribute('data-selected', 'false'));
    table.dispatchEvent(new CustomEvent('ds-table-row-select', { bubbles: true, detail: { selected: false, all: true } }));
  });

  const form = document.getElementById('practice-form');
  form?.addEventListener('submit', (e) => {
    const rows = selectedRows();
    if (!rows.length) { e.preventDefault(); return; }
    form.querySelectorAll('input[name="ids"]').forEach((i) => i.remove());
    rows.forEach((r) => {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'ids';
      input.value = r.dataset.wordId;
      form.appendChild(input);
    });
  });

  table.addEventListener('ds-table-header-cell-sort', (e) => {
    const labels = { 'Wort': 'word', 'Erstellt': 'added', 'Score': 'score' };
    const label = e.target.closest('.ds-table-header-cell')?.textContent.trim();
    const sort = labels[label];
    if (!sort) return;
    const url = new URL(window.location.href);
    url.searchParams.set('sort', sort);
    url.searchParams.set('dir', e.detail.direction === 'asc' ? 'asc' : 'desc');
    window.location.assign(url);
  });

  document.querySelector('.ds-header-block__search input')?.addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    table.querySelectorAll('.ds-table-row').forEach((r) => {
      r.hidden = q !== '' && !r.textContent.toLowerCase().includes(q);
    });
  });
});

/* Tooltips with the English and Ukrainian for every German button label (app/ui_terms.py, embedded as
   JSON). The tooltip sits on the button's label span, not on the button: text-button draws its hover
   brackets with ::before/::after, and tooltip draws its bubble with ::after. A bare-text label gets a
   span of its own (its text moved into it unchanged). Text is set with setAttribute, never as HTML. */
window.addEventListener('DOMContentLoaded', () => {
  const source = document.getElementById('wort-glossary');
  if (!source) return;
  window.wortLabelButtons = (root) => labelButtons(root);
  let glossary;
  try { glossary = JSON.parse(source.textContent); } catch (e) { return; }
  const patterns = glossary.patterns.map(([re, en, uk]) => [new RegExp(`^(?:${re})$`), en, uk]);
  const lookup = (label) => {
    if (glossary.labels[label]) return glossary.labels[label];
    for (const [re, en, uk] of patterns) {
      const m = label.match(re);
      if (m) return [en.replace('$1', m[1] || ''), uk.replace('$1', m[1] || '')];
    }
    return null;
  };
  const labelButtons = (root) => root.querySelectorAll('.ds-text-button, .ds-header-tab, .ds-table-header-cell__sort-btn').forEach((button) => {
    if (button.closest('[data-tooltip]') || button.querySelector('[data-tooltip]')) return;
    let target = button.querySelector('.ds-text-button__label, .ds-text-button__text, .ds-header-tab__label, .ds-table-cell__text');
    const label = (target || button).textContent.replace(/\s+/g, ' ').trim();
    const tip = lookup(label);
    if (!tip) return;
    if (!target) {
      if (button.children.length) return;  // an icon-only or composed button: leave it alone
      target = document.createElement('span');
      target.className = 'wort-tip';
      target.textContent = button.textContent;
      button.textContent = '';
      button.appendChild(target);
    }
    target.setAttribute('data-tooltip', `${tip[0]}\n${tip[1]}`);
  });
  labelButtons(document);
});

/* Tooltips are dis-system's layer mode (data-tooltip-mode="layer" on <html>: one fixed layer, 500 ms delay, never cut
   by a scrolling table or covered by the sticky bar). On top of it: any German word in a text shows its lemma,
   Ukrainian and English when the pointer rests on it (GET /api/gloss, 404 for anything that is not a German
   dictionary word). The word is found under the pointer in the text itself, so no page needs extra markup; fields
   and controls with a tooltip of their own are left alone. Answers, misses included, are kept for the page's life. */
window.addEventListener('DOMContentLoaded', () => {
  const tip = window.dsTooltip;
  if (!tip) return;
  const DELAY = tip.delay || 500;
  const LETTER = /[A-Za-zÄÖÜäöüß]/;
  const glosses = new Map();
  const glossText = (word) => {
    if (!glosses.has(word)) {
      glosses.set(word, fetch(`/api/gloss?w=${encodeURIComponent(word)}`, {
        credentials: 'same-origin', redirect: 'manual', headers: { Accept: 'application/json' },
      }).then((res) => (res.ok ? res.json() : null)).then((g) => {
        if (!g) return null;
        const head = [g.label, g.pos].filter(Boolean).join(' · ');
        return [head, g.uk, g.en].filter(Boolean).join('\n');
      }).catch(() => null));
    }
    return glosses.get(word);
  };
  const wordAt = (x, y) => {
    let node = null;
    let offset = 0;
    if (document.caretPositionFromPoint) {
      const pos = document.caretPositionFromPoint(x, y);
      if (pos) { node = pos.offsetNode; offset = pos.offset; }
    } else if (document.caretRangeFromPoint) {
      const range = document.caretRangeFromPoint(x, y);
      if (range) { node = range.startContainer; offset = range.startOffset; }
    }
    if (!node || node.nodeType !== Node.TEXT_NODE) return null;
    const el = node.parentElement;
    if (!el || el.closest('input, textarea, select, [contenteditable], script, style, .ds-tooltip-layer')) return null;
    const text = node.data;
    const joins = (i) => (text[i] === '-' || text[i] === "'") && LETTER.test(text[i - 1] || '') && LETTER.test(text[i + 1] || '');
    let start = offset;
    let end = offset;
    while (start > 0 && (LETTER.test(text[start - 1]) || joins(start - 1))) start -= 1;
    while (end < text.length && (LETTER.test(text[end]) || joins(end))) end += 1;
    if (end - start < 2 || end - start > 60) return null;
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, end);
    // The caret API answers the nearest text even past a line's end: only a pointer on the word itself counts.
    const on = Array.from(range.getClientRects()).some((r) => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom);
    return on ? { word: text.slice(start, end), node, start, range } : null;
  };
  let current = null;
  let timer = 0;
  const drop = () => {
    clearTimeout(timer);
    if (current && current.shown) tip.hide();
    current = null;
  };
  document.addEventListener('mousemove', (e) => {
    // A control with its own tooltip: forget the word without hide(), which would also cancel that control's
    // tooltip in the shared layer; its tooltip replaces the word's when it shows.
    if (tip.isTrigger(e.target)) { clearTimeout(timer); current = null; return; }
    const hit = wordAt(e.clientX, e.clientY);
    if (!hit) { if (current) drop(); return; }
    if (current && current.node === hit.node && current.start === hit.start) return;  // still the same word
    drop();
    const t = { node: hit.node, start: hit.start, shown: false };
    current = t;
    timer = setTimeout(async () => {
      if (current !== t || !hit.node.isConnected) return;
      const text = await glossText(hit.word);
      if (current !== t || !text) return;
      tip.show({ getBoundingClientRect: () => hit.range.getBoundingClientRect() }, text);
      t.shown = true;
    }, DELAY);
  });
  ['scroll', 'click', 'keydown'].forEach((type) => window.addEventListener(type, () => { clearTimeout(timer); current = null; }, true));
});

/* dis-system's scripts bind once at load; a block swapped in later (the word pane, a lookup result) gets the
   text-button label wrapper and the tooltips here. */
window.wortPrepare = (root) => {
  root.querySelectorAll('.ds-text-button').forEach((button) => {
    if (button.querySelector(':scope > .ds-text-button__label, :scope > .ds-text-button__text') || button.dataset.iconOnly === 'true') return;
    const text = document.createElement('span');
    text.className = 'ds-text-button__text';
    while (button.firstChild) text.appendChild(button.firstChild);
    button.appendChild(text);
  });
  if (window.wortLabelButtons) window.wortLabelButtons(root);
};

/* The word beside the table opens, switches and closes in place, without a page load: the page keeps its
   scroll position, the table keeps its selection and filter, and only the side pane's content is swapped
   (fetched from the word's own URL, taken from the page by id). The columns change in one step and the pane
   slides in / out (dis-system pane data-motion); switching words changes no layout. The address
   bar follows (pushState), back/forward work, and any failure falls back to a normal page load.
   Clicking the open word again, or "Schließen", closes it. */
(() => {
  const split = document.getElementById('wort-table');
  const side = document.getElementById('wort-side');
  if (!split || !side) return;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const narrow = window.matchMedia('(max-width: 720px)');
  let token = 0;
  let leaving = false;
  const isOpen = () => split.dataset.open === 'true';
  // Runs one entrance / exit animation of the word pane (dis-system pane data-motion: a slide beside the table,
  // a fade when the pane sits above it at phone width), then done. Starting another one, or settle(), cancels the
  // running one (its done never runs). With reduced motion done runs at once; if the animation never reports its
  // end, a fallback timer finishes it. While leaving, the split carries data-leaving (layout.css: the pane lies
  // over the already widened table).
  let running = null;
  const settle = () => {
    if (running) running.cancel();
    running = null;
    leaving = false;
    split.removeAttribute('data-leaving');
  };
  const animate = (kind, done) => {
    settle();
    if (reduce.matches) { if (done) done(); return; }
    const pane = side.querySelector('.ds-pane');
    if (!pane) { if (done) done(); return; }
    const motion = narrow.matches ? (kind === 'enter' ? 'fade-in' : 'fade-out') : kind;
    let over = false;
    const onEnd = (e) => { if (e.target === pane) finish(); };
    const timer = setTimeout(() => finish(), 400);
    const stop = () => {
      over = true; clearTimeout(timer); pane.removeEventListener('animationend', onEnd);
      delete pane.dataset.motion; split.removeAttribute('data-leaving');
    };
    const finish = () => { if (over) return; stop(); running = null; if (done) done(); };
    running = { cancel: () => { if (!over) stop(); } };
    pane.addEventListener('animationend', onEnd);
    if (kind === 'leave') split.setAttribute('data-leaving', '');
    pane.dataset.motion = motion;
  };
  const idOf = (href) => (/^\/words\/(\d+)/.exec(href) || [])[1] || null;
  const openId = () => (isOpen() ? idOf(location.pathname) : null);
  const listHref = (href) => {
    const q = href.split('#')[0].split('?')[1];
    return q ? `/?${q}` : '/';
  };
  const mark = (id) => split.querySelectorAll('.ds-table-row[data-word-id]').forEach((row) => {
    if (row.dataset.wordId === id) row.setAttribute('aria-current', 'true'); else row.removeAttribute('aria-current');
  });
  const prepare = window.wortPrepare;
  const load = async (href) => {
    const res = await fetch(href, { credentials: 'same-origin', headers: { Accept: 'text/html' } });
    if (!res.ok) throw new Error(String(res.status));
    const pane = new DOMParser().parseFromString(await res.text(), 'text/html').getElementById('detail');
    if (!pane) throw new Error('no word');
    return pane;
  };
  // A word's pane is fetched ahead while the pointer rests on its row, so the click shows it without waiting
  // for the server. Kept 30 s, at most 20 words; a failed fetch is not kept.
  const cache = new Map();
  const TTL = 30000;
  const fetched = (href) => {
    const key = href.split('#')[0];
    const hit = cache.get(key);
    if (hit && Date.now() - hit.at < TTL) return hit.pane;
    const pane = load(key);
    cache.set(key, { at: Date.now(), pane });
    pane.catch(() => cache.delete(key));
    while (cache.size > 20) cache.delete(cache.keys().next().value);
    return pane;
  };
  const fetchPane = async (href) => document.importNode(await fetched(href), true);
  let hoverTimer = 0;
  split.addEventListener('pointerover', (e) => {
    const row = e.target instanceof Element && e.target.closest('.wort-word-table .ds-table-row[data-href]');
    if (!row || e.pointerType === 'touch') return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => { if (idOf(row.dataset.href) !== openId()) fetched(row.dataset.href); }, 80);
  });
  split.addEventListener('pointerout', () => clearTimeout(hoverTimer));
  const reveal = () => split.scrollIntoView({ behavior: reduce.matches ? 'auto' : 'smooth', block: 'start' });

  const show = async (href, { push = true, scroll = false } = {}) => {
    const mine = ++token;
    let pane;
    try { pane = await fetchPane(href); } catch (err) { location.assign(href); return; }
    if (mine !== token) return;
    const wasOpen = isOpen();
    side.replaceChildren(pane);
    prepare(pane);
    mark(idOf(href));
    if (!wasOpen || leaving) {
      settle();
      split.dataset.open = 'true';
      animate('enter');
    }
    if (push) history.pushState(null, '', href.split('#')[0]);
    if (scroll) reveal();
  };
  const close = (href, { push = true } = {}) => {
    token += 1;
    if (!isOpen() || leaving) return;
    mark(null);
    if (push) history.pushState(null, '', href);
    const mine = token;
    // Wide: the table widens at once under the fading pane (layout.css data-leaving). Narrow: the word sits above
    // the table, so it fades first and the table moves up after.
    const overlay = !narrow.matches;
    animate('leave', () => {
      leaving = false;
      if (mine !== token) return;  // reopened meanwhile
      delete split.dataset.open;
      side.replaceChildren();
    });
    if (overlay) delete split.dataset.open;
    leaving = !reduce.matches && (overlay || isOpen());
  };

  const activate = (href, inTable) => {
    if (idOf(href) === openId()) {
      if (inTable) close(listHref(href)); else reveal();
      return;
    }
    show(href, { scroll: !inTable });
  };
  // dis-system's table-row navigates on a row click unless the host cancels its ds-table-row-open event:
  // the word opens here, in place, and the click handler below leaves that click alone.
  let rowEventClick = false;
  document.addEventListener('ds-table-row-open', (e) => {
    const href = e.detail && e.detail.href;
    if (!(e.target instanceof Element) || !e.target.closest('.wort-word-table') || !idOf(href || '')) return;
    e.preventDefault();
    rowEventClick = true;
    activate(href, true);
  });

  document.addEventListener('click', (e) => {
    if (rowEventClick) { rowEventClick = false; return; }
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (!(e.target instanceof Element)) return;
    const closer = e.target.closest('.wort-word a[href^="/?"]');
    if (closer) { e.preventDefault(); close(closer.getAttribute('href').split('#')[0]); return; }
    const link = e.target.closest('a[href^="/words/"]');
    const row = e.target.closest('.wort-word-table .ds-table-row[data-href]');
    let href = null;
    if (link && !link.closest('.wort-word') && idOf(link.getAttribute('href'))) {
      href = link.getAttribute('href');
    } else if (!link && row && !e.target.closest('a, button, input, label, [data-type="checkbox-cell"], [data-type="icon-cell"]') && !String(window.getSelection())) {
      href = row.dataset.href;
    }
    if (!href || !idOf(href)) return;
    e.preventDefault();
    activate(href, !!e.target.closest('.wort-word-table'));
  });

  window.addEventListener('popstate', () => {
    const id = idOf(location.pathname);
    if (id) show(location.pathname + location.search, { push: false });
    else close(location.pathname + location.search, { push: false });
  });
})();

/* Lookup in place: the hero's field submits by fetch and only the result block (.wort-lookup) is swapped in
   below the hero, fading in; the hero and the field do not move, the page is not reloaded and the scroll stays.
   The result block's own "Suche schließen" removes it. Address bar and back/forward follow (pushState); a
   failed fetch falls back to the normal page load. */
(() => {
  const hero = document.querySelector('.ds-hero-block');
  const form = hero?.querySelector('form[role="search"]');
  if (!form) return;
  const input = form.querySelector('input[name="q"]');
  let token = 0;
  const swap = (section) => {
    document.querySelector('.wort-lookup')?.remove();
    if (!section) return;
    const block = document.importNode(section, true);
    hero.after(block);
    window.wortPrepare(block);
    block.classList.add('ds-fade-in');  // dis-system fade-in: the result block arrives softly, the field stays put
    block.addEventListener('animationend', () => block.classList.remove('ds-fade-in'), { once: true });
  };
  const load = async (url, { push = true } = {}) => {
    const mine = ++token;
    let section;
    try {
      const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'text/html' } });
      if (!res.ok) throw new Error(String(res.status));
      section = new DOMParser().parseFromString(await res.text(), 'text/html').querySelector('.wort-lookup');
    } catch (err) { location.assign(url); return; }
    if (mine !== token) return;
    swap(section);
    if (push) history.pushState(null, '', url);
  };
  form.addEventListener('submit', (e) => {
    if (!input || !input.value.trim()) return;
    e.preventDefault();
    load(`/?${new URLSearchParams(new FormData(form))}`);
  });
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (!(e.target instanceof Element) || !e.target.closest('.wort-lookup > .wort-row a[href="/"]')) return;
    e.preventDefault();
    token += 1;
    swap(null);
    history.pushState(null, '', '/');
  });
  window.addEventListener('popstate', () => {
    if (location.pathname !== '/') return;
    const q = new URLSearchParams(location.search).get('q') || '';
    if (input) input.value = q;
    if (q) load(location.pathname + location.search, { push: false }); else { token += 1; swap(null); }
  });
})();

/* Üben: Enter in the answer box sends it, like "Senden"; Shift+Enter starts a new line. An Enter that confirms an
   input-method composition (e.g. a dead key or IME) is left alone. An empty answer is not sent. */
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey || e.isComposing) return;
  const box = e.target instanceof HTMLTextAreaElement ? e.target.closest('.wort-composer form') && e.target : null;
  if (!box) return;
  e.preventDefault();
  if (box.value.trim()) box.form.requestSubmit();
});

/* Terminal-style (readline / emacs) editing in every text field of the app:
   Ctrl+B / Ctrl+F   one character back / forward      Alt+B / Alt+F   one word back / forward
   Ctrl+A / Ctrl+E   start / end of the line           Ctrl+P / Ctrl+N line up / down (textarea)
   Ctrl+D / Ctrl+H   delete the next / previous char   Alt+D           delete the next word
   Ctrl+K / Ctrl+U   cut to the end / start of line    Alt+Backspace   cut the previous word
   Ctrl+Y            paste the last cut text
   Edits go through execCommand so Ctrl+Z still undoes them. Some browsers keep Ctrl+N and Ctrl+W for
   themselves (new window, close tab); Cmd on macOS is left alone. */
(() => {
  let killed = '';
  const isField = (el) => el instanceof HTMLTextAreaElement
    || (el instanceof HTMLInputElement && ['text', 'search', ''].includes(el.type));
  const lineStart = (v, i) => v.lastIndexOf('\n', i - 1) + 1;
  const lineEnd = (v, i) => { const n = v.indexOf('\n', i); return n === -1 ? v.length : n; };
  const wordBack = (v, i) => { while (i > 0 && !/[\wäöüÄÖÜß]/.test(v[i - 1])) i--; while (i > 0 && /[\wäöüÄÖÜß]/.test(v[i - 1])) i--; return i; };
  const wordFwd = (v, i) => { while (i < v.length && !/[\wäöüÄÖÜß]/.test(v[i])) i++; while (i < v.length && /[\wäöüÄÖÜß]/.test(v[i])) i++; return i; };
  const lineMove = (v, i, dir) => {
    const s = lineStart(v, i), col = i - s;
    if (dir < 0) { if (s === 0) return 0; const ps = lineStart(v, s - 1); return Math.min(ps + col, s - 1); }
    const e = lineEnd(v, i); if (e === v.length) return v.length;
    const ns = e + 1; return Math.min(ns + col, lineEnd(v, ns));
  };
  const cut = (el, from, to, keep) => {
    if (from === to) return;
    const [a, b] = from < to ? [from, to] : [to, from];
    if (keep) killed = el.value.slice(a, b);
    el.setSelectionRange(a, b);
    if (!document.execCommand('delete')) el.setRangeText('', a, b, 'end');
  };
  const KEYS = {
    'C-b': (el, v, i) => el.setSelectionRange(Math.max(0, i - 1), Math.max(0, i - 1)),
    'C-f': (el, v, i) => el.setSelectionRange(Math.min(v.length, i + 1), Math.min(v.length, i + 1)),
    'M-b': (el, v, i) => { const j = wordBack(v, i); el.setSelectionRange(j, j); },
    'M-f': (el, v, i) => { const j = wordFwd(v, i); el.setSelectionRange(j, j); },
    'C-a': (el, v, i) => { const j = lineStart(v, i); el.setSelectionRange(j, j); },
    'C-e': (el, v, i) => { const j = lineEnd(v, i); el.setSelectionRange(j, j); },
    'C-p': (el, v, i) => { const j = lineMove(v, i, -1); el.setSelectionRange(j, j); },
    'C-n': (el, v, i) => { const j = lineMove(v, i, 1); el.setSelectionRange(j, j); },
    'C-d': (el, v, i) => cut(el, i, Math.min(v.length, i + 1), false),
    'C-h': (el, v, i) => cut(el, Math.max(0, i - 1), i, false),
    'M-d': (el, v, i) => cut(el, i, wordFwd(v, i), true),
    'M-Backspace': (el, v, i) => cut(el, wordBack(v, i), i, true),
    'C-k': (el, v, i) => cut(el, i, lineEnd(v, i) === i && i < v.length ? i + 1 : lineEnd(v, i), true),
    'C-u': (el, v, i) => cut(el, lineStart(v, i), i, true),
    'C-y': (el) => { if (killed && !document.execCommand('insertText', false, killed)) el.setRangeText(killed, el.selectionStart, el.selectionEnd, 'end'); },
  };
  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.isComposing || e.shiftKey || e.ctrlKey === e.altKey || !isField(e.target)) return;
    const key = e.key === 'Backspace' ? 'Backspace' : (e.code.startsWith('Key') ? e.code.slice(3).toLowerCase() : '');
    const run = KEYS[`${e.ctrlKey ? 'C' : 'M'}-${key}`];
    if (!run) return;
    e.preventDefault();
    const el = e.target;
    run(el, el.value, el.selectionDirection === 'backward' ? el.selectionStart : el.selectionEnd);
  });
})();

/* Header height: --wort-head-h (layout.css) follows the sticky header (nav bar + toolbar), which wraps on
   narrow windows, so the side panel and sticky panes start right below it. */
(() => {
  const head = document.querySelector('.wort-head');
  if (!head) return;
  const set = () => document.documentElement.style.setProperty('--wort-head-h', `${head.offsetHeight}px`);
  set();
  new ResizeObserver(set).observe(head);
})();

/* Lookup side panel: "Nachschlagen" in the toolbar opens and closes it (remembered per browser, a viewer
   convenience only). Its search fetches the Wörter page's lookup for the query and shows that page's result
   block (.wort-lookup) in the panel; "Zu Wörtern hinzufügen" is posted the same way, so the page beside the panel
   (an exercise, the word list) is never left. Results are parsed HTML from our own server, moved in as nodes;
   nothing is built from strings. A failed fetch says so in the panel. */
(() => {
  const side = document.getElementById('wort-lookup-side');
  const toggle = document.querySelector('[data-side-toggle]');
  if (!side || !toggle) return;
  const KEY = 'wort-side';
  const form = side.querySelector('.wort-side__search');
  const input = form.querySelector('input[name="q"]');
  const results = side.querySelector('.wort-side__results');
  const close = side.querySelector('.ds-pane__head .ds-text-button');

  const pane = side.querySelector('.ds-pane');
  const still = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // One entrance / exit of the panel (dis-system pane data-motion, as the word pane on the Wörter page): it slides
  // in when opened; when closed it slides out first and is hidden after. Without motion it just appears / goes.
  const animate = (open, done) => {
    if (still()) { done(); return; }
    pane.dataset.motion = open ? 'enter' : 'leave';
    pane.addEventListener('animationend', () => { delete pane.dataset.motion; done(); }, { once: true });
  };
  const setOpen = (open, { focus = false, motion = true } = {}) => {
    if (open) side.hidden = false;
    if (motion) animate(open, () => { if (!open) side.hidden = true; });
    else side.hidden = !open;
    document.body.dataset.side = open ? 'open' : 'closed';
    toggle.setAttribute('aria-expanded', String(open));
    try { localStorage.setItem(KEY, open ? 'open' : 'closed'); } catch (e) { /* not persisted */ }
    if (open && focus) input.focus();
    if (!open && focus) toggle.focus();
  };
  let stored = 'closed';
  try { stored = localStorage.getItem(KEY) || 'closed'; } catch (e) { /* not persisted */ }
  setOpen(stored === 'open', { motion: false });  // a page load restores the panel without an entrance
  toggle.addEventListener('click', () => setOpen(document.body.dataset.side !== 'open', { focus: true }));
  close?.addEventListener('click', () => setOpen(false, { focus: true }));

  const message = (text) => {
    const p = document.createElement('p');
    p.className = 'wort-side__message';
    p.textContent = text;
    results.replaceChildren(p);
  };
  let token = 0;
  const show = async (url, init = {}) => {
    const mine = ++token;
    let doc;
    try {
      const res = await fetch(url, { ...init, credentials: 'same-origin', headers: { Accept: 'text/html' } });
      if (!res.ok) throw new Error(String(res.status));
      doc = new DOMParser().parseFromString(await res.text(), 'text/html');
    } catch (err) { if (mine === token) message('Nachschlagen fehlgeschlagen. Bitte noch einmal versuchen.'); return; }
    if (mine !== token) return;
    const block = doc.querySelector('.wort-lookup');
    if (!block) { results.replaceChildren(); return; }
    block.querySelector('a[href="/"]')?.remove();  // the Wörter page's "Suche schließen"; the panel has its own close
    const node = document.importNode(block, true);
    results.replaceChildren(node);
    window.wortPrepare(node);
    const flash = doc.querySelector('[data-flash]');
    if (flash && window.dsToast) window.dsToast.show({ message: flash.textContent.trim(), status: flash.dataset.flash || 'default' });
  };
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!input.value.trim()) { results.replaceChildren(); return; }
    show(`/?${new URLSearchParams(new FormData(form))}`);
  });
  results.addEventListener('submit', (e) => {
    const add = e.target instanceof HTMLFormElement && e.target.getAttribute('action') === '/words/add' ? e.target : null;
    if (!add) return;
    e.preventDefault();
    show('/words/add', { method: 'POST', body: new FormData(add) });
  });
})();

/* Üben: the current result arrives in steps — the answer, the correction, the feedback, then the next task —
   each one released from dis-system fade-in's hold (data-fade-hold) and faded in with its class, STEP ms apart.
   With reduced motion everything is shown at once. */
(() => {
  const steps = Array.from(document.querySelectorAll('[data-result-step][data-fade-hold]'))
    .sort((a, b) => Number(a.dataset.resultStep) - Number(b.dataset.resultStep));
  if (!steps.length) return;
  const STEP = 220;
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const release = (el) => {
    el.removeAttribute('data-fade-hold');
    if (still) return;
    el.classList.add('ds-fade-in');
    el.addEventListener('animationend', () => el.classList.remove('ds-fade-in'), { once: true });
  };
  steps.forEach((el, i) => (still ? release(el) : setTimeout(() => release(el), i * STEP)));
})();

/* Side panels (lookup, Fehler erklärt) lie over the page. When one covers the page's column, the column moves left by
   the overlap (--wort-side-push on <html>, layout.css); when it does not, nothing moves. Measured on open/close, on a
   handle drag (dis-system's ds-split-resize), on a window resize and once on load. */
(() => {
  const shell = document.querySelector('.wort-shell');
  const main = shell?.querySelector('.wort-main');
  if (!main) return;
  const root = document.documentElement;
  const panels = () => Array.from(document.querySelectorAll('.wort-side:not([hidden]) > .ds-pane'))
    .filter((p) => !p.dataset.motion || p.dataset.motion === 'enter');
  let frame = 0;
  const measure = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const set = (px) => root.style.setProperty('--wort-side-push', `${px}px`);
      set(0);  // the column where it would be without a push
      const left = Math.min(...panels().map((p) => p.getBoundingClientRect().left), Infinity);
      const right0 = main.getBoundingClientRect().right;
      const overlap = Number.isFinite(left) ? Math.max(0, right0 - left) : 0;
      if (!overlap) return;
      // How far the column's edge moves per pixel of padding depends on the window: half while the column keeps its
      // max width and recentres, all of it once it has to shrink. Try the overlap once and scale by what it did.
      set(overlap);
      const moved = right0 - main.getBoundingClientRect().right;
      set(Math.ceil(moved > 0 ? overlap * (overlap / moved) : overlap));
    });
  };
  window.wortSidePush = measure;
  window.addEventListener('resize', measure);
  document.addEventListener('ds-split-resize', measure);
  new MutationObserver(measure).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['hidden', 'data-motion'] });
  measure();
})();
