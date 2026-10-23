/* Runs in <head>, before any stylesheet is applied: sets the stored theme on <html> so a dark-theme page
   never paints light first (a white flash on every page load). app.js keeps the toggle in step. */
try {
  if (localStorage.getItem('ds-theme') === 'dark') document.documentElement.dataset.theme = 'dark';
} catch (e) { /* storage blocked: the page starts light */ }
