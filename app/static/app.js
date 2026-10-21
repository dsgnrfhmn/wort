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
