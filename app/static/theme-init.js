/* Runs in <head>, before any stylesheet is applied: sets the stored theme on <html> so a dark-theme page
   never paints light first (a white flash on every page load). app.js keeps the toggle in step. */
try {
  if (localStorage.getItem('ds-theme') === 'dark') document.documentElement.dataset.theme = 'dark';
} catch (e) { /* storage blocked: the page starts light */ }
/* The favicon follows the page's theme, not the system's: black W with a white border on light, white W with a black border on dark (garv, 2026-10-28). Bump ?v= when the icon changes: browsers keep a favicon
   by its URL. */
window.wortFavicon = (theme) => {
  const icon = document.getElementById('wort-favicon');
  if (icon) icon.href = theme === 'dark' ? '/static/favicon-dark.svg?v=3' : '/static/favicon-light.svg?v=3';
};
window.wortFavicon(document.documentElement.dataset.theme);
