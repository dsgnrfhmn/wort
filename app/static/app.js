/* Theme switch glue for dis-system's nav-bar: applies data-theme and remembers it (same key as dis-system's site). */
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
  document.addEventListener('ds-table-row-select', syncButtons);
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
