/* Interface texts the page hands to this script (base.html #wort-i18n), already in the user's language. */
const wortText = (() => {
  let texts = {};
  try { texts = JSON.parse(document.getElementById('wort-i18n')?.textContent || '{}'); } catch (e) { /* none */ }
  return (key) => texts[key] || key;
})();

/* The header's language switch (nav-bar's switcher): the pick is posted with the hidden #wort-lang-form, which
   stores it in the profile and comes back to this page. */
document.addEventListener('ds-dropdown-select', (e) => {
  const form = document.getElementById('wort-lang-form');
  if (!form || !e.target.closest('.ds-nav-bar__switcher') || !e.detail || !e.detail.value) return;
  if (form.elements.lang.value === e.detail.value) return;
  form.elements.lang.value = e.detail.value;
  form.elements.next.value = window.location.pathname + window.location.search;
  form.submit();
});

/* Scrollbars show only while something scrolls (layout.css keeps the thumbs transparent): whatever is being scrolled,
   the page or any inner scroll container, gets .is-scrolling until it has been still for 800 ms. One capturing listener:
   scroll events do not bubble, but every one passes the document in the capture phase. */
(() => {
  const timers = new WeakMap();
  document.addEventListener('scroll', (e) => {
    const el = e.target === document ? document.documentElement : e.target;
    if (!(el instanceof Element)) return;
    el.classList.add('is-scrolling');
    clearTimeout(timers.get(el));
    timers.set(el, setTimeout(() => el.classList.remove('is-scrolling'), 800));
  }, { capture: true, passive: true });
})();

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
  const selectedRows = () => Array.from(table.querySelectorAll('.ds-table-row[data-selected="true"][data-word-id]:not([data-phrase])'));
  const gated = () => Array.from(document.querySelectorAll('[data-needs-selection]'));

  const syncButtons = () => {
    const on = selectedRows().length > 0;
    gated().forEach((b) => {
      b.dataset.status = on ? 'active' : 'disabled';
      if (b.tagName === 'BUTTON') b.disabled = !on;
    });
  };
  // Nothing is selected on load; only a preset from the server ("10 schwächste", "Letzte 20") pre-selects rows.
  // A phrase row has no checkbox and is never selected (Üben has no exercise for it); "select all" skips it, and the
  // header checkbox counts only the rows that can be selected, so a second click still clears them.
  const header = table.querySelector('.ds-table-cell[data-checkbox-role="select-all"]');
  const afterSelect = () => {
    table.querySelectorAll('.ds-table-row[data-phrase][data-selected="true"]').forEach((r) => r.setAttribute('data-selected', 'false'));
    if (header && table.querySelector('.ds-table-row[data-phrase]')) {
      const rows = Array.from(table.querySelectorAll('.ds-table-row[data-word-id]:not([data-phrase])'));
      const on = rows.filter((r) => r.getAttribute('data-selected') === 'true').length;
      header.setAttribute('data-state', rows.length && on === rows.length ? 'checked' : on ? 'indeterminate' : 'unchecked');
    }
    syncButtons();
  };
  document.addEventListener('ds-table-row-select', afterSelect);
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
    const labels = { Word: 'word', Wort: 'word', Added: 'added', Erstellt: 'added', Score: 'score' };  // EN / DE
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

/* Üben: where the focus starts. A task waiting for an answer: the answer box (not on a phone, where it would open the
   keyboard and cover the task). An answer already given on a page without steps (the Quiz): its verdict. */
(() => {
  const coarse = window.matchMedia('(hover: none)').matches;
  const box = document.querySelector('.wort-composer textarea, .wort-composer input[name="text"], .wort-quiz form.wort-answer textarea, .wort-quiz form.wort-answer input[name="text"]');
  if (box && !coarse) { box.focus({ preventScroll: true }); return; }
  const verdict = document.querySelector('.wort-verdict[data-autofocus]');
  if (verdict) verdict.focus({ preventScroll: true });
})();

/* Üben: Enter in the answer box sends it, like "Senden"; Shift+Enter starts a new line. An Enter that confirms an
   input-method composition (e.g. a dead key or IME) is left alone. An empty answer is not sent. */
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey || e.isComposing) return;
  const box = e.target instanceof HTMLTextAreaElement ? e.target.closest('.wort-composer form, .wort-quiz form.wort-answer') && e.target : null;
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
    } catch (err) { if (mine === token) message(wortText('lookup_failed')); return; }
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
    // The verdict takes the focus when it appears, so a screen reader reads it (it is a section with tabindex="-1").
    if (el.matches('.wort-verdict[tabindex]')) el.focus({ preventScroll: true });
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

/* Abfrage: the mode radio (dis-system radio) starts a new round in that mode with the same words. */
(() => {
  const form = document.querySelector('form[data-abfrage-mode]');
  if (!form) return;
  form.addEventListener('ds-radio-change', (e) => {
    if (!e.detail || form.elements.art.value === e.detail.value) return;
    form.elements.art.value = e.detail.value;
    form.requestSubmit();
  });
})();

/* Search result: "Weiteres Beispiel zeigen" reveals the next hidden example; gone once all are shown. Runs on the
   page and on blocks swapped in later (event delegation). */
document.addEventListener('click', (e) => {
  const more = e.target instanceof Element ? e.target.closest('[data-more-examples]') : null;
  if (!more) return;
  const section = more.closest('[data-examples]');
  const next = section?.querySelector('.wort-example[hidden]');
  if (next) next.hidden = false;
  if (!section?.querySelector('.wort-example[hidden]')) more.remove();
  const shown = section ? section.querySelectorAll('.wort-example:not([hidden])').length : 0;
  const info = section?.querySelector('.ds-table-header__info');
  if (info) info.textContent = info.textContent.replace(/^\d+/, String(shown));
});

/* Wörter: the row context menu (dis-system context-menu, #wort-word-menu): open the word, practise it alone, or remove
   it after the confirmation popup (#wort-delete-confirm), since removing also deletes its score and answers. */
(() => {
  const confirmBox = document.getElementById('wort-delete-confirm');
  const deleteForm = document.getElementById('wort-delete-form');
  const opener = document.getElementById('wort-delete-open');
  let pending = null;  // the word id waiting for the confirmation
  document.addEventListener('ds-context-menu-select', (e) => {
    const row = e.detail && e.detail.host;
    const id = row && row.dataset.wordId;
    if (!id || !/^\d+$/.test(id)) return;
    const link = row.querySelector('a[href]');
    if (e.detail.value === 'open' && link) {
      link.click();
    } else if (e.detail.value === 'practice') {
      const csrf = document.querySelector('#practice-form input[name="csrf"]');
      if (!csrf) return;
      const form = document.createElement('form');
      form.method = 'post';
      form.action = '/ueben/saetze';
      form.hidden = true;
      for (const [name, value] of [['csrf', csrf.value], ['ids', id]]) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = name;
        input.value = value;
        form.appendChild(input);
      }
      document.body.appendChild(form);
      form.submit();
    } else if (e.detail.value === 'delete' && confirmBox && deleteForm && opener) {
      pending = id;
      const text = confirmBox.querySelector('.ds-popup__body p');
      const word = (link ? link.textContent : '').trim();
      if (text && word) text.textContent = wortText('delete_named').replace('{word}', word);
      opener.click();
    }
  });
  confirmBox?.addEventListener('ds-popup-before-close', (e) => {
    const button = e.detail && e.detail.button;
    if (!pending || !button || !button.hasAttribute('data-popup-confirm')) { pending = null; return; }
    deleteForm.action = `/words/${pending}/delete`;
    pending = null;
    deleteForm.submit();
  });
})();

/* Üben: Send shows the answer at once with a progress bar while the server checks it (the next page brings the
   result in steps); the composer's buttons are disabled so it is sent once. "Next task" shows the progress bar too.
   "Show feedback" brings a hidden feedback out from under its answer, with fade-in. */
(() => {
  const pending = document.getElementById('wort-pending');
  const chat = document.querySelector('.wort-chat');
  const WAIT = 30000;  // ms; a check with LanguageTool or the AI takes a few seconds
  document.querySelectorAll('.wort-composer form').forEach((form) => {
    form.addEventListener('submit', () => {
      if (!pending || !chat || form.dataset.sent) return;
      form.dataset.sent = 'true';
      const node = pending.content.firstElementChild.cloneNode(true);
      const text = form.querySelector('textarea, input[name="text"]');
      const bubble = node.querySelector('[data-pending-answer]');
      if (text && text.value.trim()) {
        bubble.querySelector('.ds-message__text').textContent = text.value.trim();
      } else {
        bubble.remove();  // "Next task": only the progress bar
      }
      node.classList.add('ds-fade-in');
      (document.getElementById('jetzt') || chat).appendChild(node);
      node.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      // After this event: disabling the submitter first would drop it from the form data.
      const controls = () => form.querySelectorAll('button, textarea, input:not([type="hidden"])');
      setTimeout(() => controls().forEach((el) => { el.disabled = true; }), 0);
      // A request that never comes back (the server restarted, the network dropped) must not leave the page stuck:
      // after WAIT the answer can be sent again, with a message.
      setTimeout(() => {
        if (!node.isConnected) return;
        node.remove();
        delete form.dataset.sent;
        controls().forEach((el) => { el.disabled = false; });
        if (window.dsToast) window.dsToast.show({ message: wortText('send_stalled'), status: 'error' });
      }, WAIT);
    });
  });
  // Back to this page from the browser's history (bfcache): the pending state of the earlier Send is not real.
  window.addEventListener('pageshow', (e) => {
    if (!e.persisted) return;
    document.querySelectorAll('.wort-pending').forEach((n) => n.remove());
    document.querySelectorAll('.wort-composer form').forEach((form) => {
      delete form.dataset.sent;
      form.querySelectorAll('button, textarea, input:not([type="hidden"])').forEach((el) => { el.disabled = false; });
    });
  });
  // "Show feedback" / "Hide feedback" under an answer: the feedback block below it comes out from under the bubble.
  document.addEventListener('click', (e) => {
    const button = e.target.closest('[data-feedback-toggle]');
    const box = button && document.getElementById(button.getAttribute('aria-controls'));
    if (!box) return;
    const show = box.hidden;
    box.hidden = !show;
    button.setAttribute('aria-expanded', String(show));
    button.textContent = wortText(show ? 'hide_feedback' : 'explain_more');
    if (show && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      box.classList.add('ds-fade-in');
      box.addEventListener('animationend', () => box.classList.remove('ds-fade-in'), { once: true });
    }
  });
  // "Show original" / "Show corrected" under a corrected answer: the bubble shows the marked version or the answer as written.
  // Both stay in the layout and layout.css hides the one not showing, so no size changes; the focus follows to the other button.
  document.addEventListener('click', (e) => {
    const button = e.target.closest('[data-answer-toggle]');
    const mine = button && button.closest('.wort-reply__mine[data-shown]');
    if (!mine) return;
    mine.dataset.shown = button.dataset.answerToggle;
    mine.querySelector(`[data-answer-toggle]:not([data-answer-toggle="${mine.dataset.shown}"])`)?.focus({ preventScroll: true });
  });
})();

/* Texte: a popup the URL asks for opens on load and closing it goes back to the page behind; the sidebar's "Upload photo"
   opens the upload popup; buttons that are not connected yet ([data-demo]) say so instead of doing nothing. The way into
   the word list: a click on any word posts its place in the text; selecting text opens dis-system's
   context menu at the pointer with its translation and "Add to word list" (a single word is added as a word, longer
   text as a phrase) and posts the selected text. The server decides what is added and answers with a message and what
   is in the list now. */
(() => {
  const root = document.querySelector('.wort-texts');
  if (!root) return;
  const toast = (message, status = 'default') => { if (window.dsToast) window.dsToast.show({ message, status }); };

  const auto = document.querySelector('[data-autoopen]');
  if (auto) {
    const back = auto.dataset.closeHref;
    document.getElementById(auto.dataset.popupOpen)?.addEventListener('ds-popup-before-close', () => {
      if (back && back.startsWith('/texte')) window.location.assign(back);
    });
    auto.click();
  }
  document.querySelector('.wort-texts__side .ds-sidebar-item[data-role="create"] button')?.setAttribute('data-popup-open', 'wort-texts-upload');

  // The check step. The photo is a small copy the server sent with the page (a data URL in an attribute, nothing is stored);
  // it goes into the image frame, replacing the placeholder, and only a JPEG data URL is taken. The translation preview
  // sends the text to the server one paragraph at a time, so the first lines appear at once and one slow paragraph never
  // holds up the page; lines are written with textContent, in the language they are in. "Update translation" asks again.
  const check = document.getElementById('wort-check-form');
  if (check) {
    const photo = check.querySelector('[data-photo]');
    const frame = photo?.querySelector('.ds-image-regions__frame');
    if (frame && (photo.dataset.photo || '').startsWith('data:image/jpeg;base64,')) {
      const img = document.createElement('img');
      img.className = 'ds-image-regions__img';
      img.alt = photo.dataset.photoAlt || '';
      img.src = photo.dataset.photo;
      frame.querySelector('.ds-image-regions__placeholder')?.remove();
      frame.removeAttribute('role');
      frame.removeAttribute('aria-label');
      frame.prepend(img);
    }
    const panel = check.querySelector('[data-translation]');
    const field = check.querySelector('textarea[name="text"]');
    const token = check.querySelector('input[name="csrf"]')?.value;
    if (panel && field && token) {
      const MAX_PARAGRAPHS = 40;
      const status = panel.querySelector('[data-translation-status]');
      const out = panel.querySelector('[data-translation-lines]');
      let run = 0;
      async function translateAll() {
        const mine = ++run;
        const all = field.value.split(/\n{2,}/).map((p) => p.replace(/\s+/g, ' ').trim()).filter(Boolean);
        const paragraphs = all.slice(0, MAX_PARAGRAPHS);
        out.replaceChildren();
        status.textContent = paragraphs.length ? wortText('translating') : '';
        status.hidden = !paragraphs.length;
        let problem = '';
        for (const paragraph of paragraphs) {
          let data = null;
          try {
            const res = await fetch('/texte/neu/uebersetzung', { method: 'POST', credentials: 'same-origin',
              headers: { Accept: 'application/json' }, body: new URLSearchParams({ csrf: token, text: paragraph }) });
            data = await res.json().catch(() => null);
            if (!data) problem = wortText('translate_failed');
          } catch (err) { problem = wortText('translate_failed'); }
          if (mine !== run) return;  // the text was translated again meanwhile: this run's lines are out of date
          if (data && data.lines && data.lines.length) {
            const block = document.createElement('div');
            data.lines.forEach((line) => {
              const p = document.createElement('p');
              p.lang = line.lang;
              p.textContent = line.text;
              block.appendChild(p);
            });
            out.appendChild(block);
          } else if (data) { problem = data.message || wortText('translate_failed'); }
          if (problem) break;  // no model, busy or failed: the rest would fail the same way
        }
        if (!problem && all.length > MAX_PARAGRAPHS) problem = wortText('translate_cut');
        status.textContent = problem;
        status.hidden = !problem;
      }
      panel.querySelector('[data-translation-update]')?.addEventListener('click', (e) => { e.preventDefault(); translateAll(); });
      translateAll();  // the check step opens with the page (data-autoopen): start at once, it does not block anything
    }
  }

  const textId = root.dataset.textId;
  const csrf = document.querySelector('#wort-text-form input[name="csrf"]')?.value;
  async function post(path, fields, quiet = false) {
    if (!textId || !csrf) return null;
    try {
      const res = await fetch(`/texte/${textId}/${path}`, { method: 'POST', credentials: 'same-origin',
        headers: { Accept: 'application/json' }, body: new URLSearchParams({ csrf, ...fields }) });
      const data = await res.json().catch(() => ({}));
      if (res.ok) return data;
      if (!quiet) toast(res.status === 400 && typeof data.detail === 'string' ? data.detail : wortText('add_failed'), 'error');
    } catch (err) { if (!quiet) toast(wortText('add_failed'), 'error'); }
    return null;
  }
  // What the server says is in the word list now: its words get the dotted underline. The notes list and the sidebar's note
  // counts are fetched again (the page as the server renders it) and put in place of the old ones; nodes of that page,
  // never markup written here.
  function showKnown(data) {
    (data.refs || []).forEach((ref) => root.querySelector(`.ds-word-token[data-ref="${CSS.escape(ref)}"]`)?.setAttribute('data-state', 'known'));
  }
  async function refreshNotes() {
    try {
      const res = await fetch(window.location.pathname, { credentials: 'same-origin', headers: { Accept: 'text/html' } });
      if (!res.ok) return;
      const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
      ['.wort-texts__notes', '.wort-texts__side'].forEach((selector) => {
        const fresh = doc.querySelector(selector);
        const old = root.querySelector(selector);
        if (fresh && old) { old.replaceChildren(...fresh.childNodes); window.wortPrepare?.(old); }
      });
    } catch (err) { /* the old notes stay until the page is loaded again */ }
  }
  async function add(path, fields) {
    const data = await post(path, fields);
    if (!data) return;
    toast(data.message);
    showKnown(data);
    if (data.status === 'added' || data.status === 'exists') refreshNotes();
  }

  const body = root.querySelector('.wort-text__body');
  const menu = document.getElementById('wort-selection-menu');
  const translation = document.getElementById('wort-selection-translation');
  // The text the browser has selected inside the text (the hover cards inside it are not part of the text), as one line.
  const selectedText = () => {
    const sel = window.getSelection();
    if (!body || !sel || sel.isCollapsed || !sel.rangeCount || !body.contains(sel.getRangeAt(0).commonAncestorContainer)) return '';
    const copy = document.createElement('div');
    copy.appendChild(sel.getRangeAt(0).cloneContents());
    copy.querySelectorAll('.ds-word-token__card').forEach((card) => card.remove());
    return copy.textContent.replace(/\s+/g, ' ').trim();
  };

  // A click on a word adds it, a moment later: a double click (which selects the word) or a drag that ends inside the
  // same word is a selection, not a click, and the selection menu takes over. The words are spans (their text can be
  // selected), so the click and the Enter / Space key are handled here, not by the component.
  let clickTimer = 0;
  body?.addEventListener('dblclick', () => clearTimeout(clickTimer));
  document.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches?.('.ds-word-token[data-ref]')) {
      e.preventDefault();
      add('wort', { ref: e.target.dataset.ref });
    }
  });

  document.addEventListener('click', (e) => {
    const word = e.target.closest('.ds-word-token[data-ref]');
    if (word) {
      clearTimeout(clickTimer);
      clickTimer = setTimeout(() => { if (!selectedText()) add('wort', { ref: word.dataset.ref }); }, 250);
      return;
    }
    if (e.target.closest('[data-demo]')) { e.preventDefault(); toast(wortText('demo_stub')); return; }
  });

  // The selection menu: attached to the text for as long as something is selected in it (so everywhere else the
  // browser's own menu stays), opened by the end of a mouse selection and by a right click on a selection. Its first row
  // is the translation, asked for from the server; a late answer for an earlier selection is dropped.
  let selection = '';
  let asked = 0;
  async function translate(text) {
    const mine = ++asked;
    translation.textContent = wortText('translating');
    const data = await post('uebersetzung', { text }, true);
    if (mine !== asked || menu.hidden) return;
    translation.textContent = !data ? wortText('translate_failed') : data.lines.length ? data.lines.join('\n') : data.message;
  }
  body?.addEventListener('contextmenu', () => {
    selection = selectedText();
    if (!selection || !menu || !translation) { body.removeAttribute('data-context-menu'); return; }
    body.setAttribute('data-context-menu', 'wort-selection-menu');
    translate(selection);
  });
  body?.addEventListener('mouseup', (e) => {
    if (e.button !== 0) return;
    const { clientX, clientY } = e;
    setTimeout(() => {
      if (selectedText()) body.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX, clientY }));
    }, 0);
  });
  document.addEventListener('ds-context-menu-select', (e) => {
    if (e.detail && e.detail.host === body && e.detail.value === 'add-selection' && selection) add('auswahl', { text: selection });
  });
})();
