(() => {
  // Times are written on the server in this computer's zone, which reaches it
  // in a cookie. When the cookie is new or changed and the page was written in
  // another zone, the page is fetched once more. A page that answered a form
  // is never reloaded, so nothing is submitted twice.
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
    const saved = () => (document.cookie.match(/(?:^|;\s*)ops_tz=([^;]*)/) || [])[1];
    if (/^[A-Za-z0-9_+\/-]{1,64}$/.test(zone) && saved() !== zone) {
      document.cookie = `ops_tz=${zone}; path=/ops/; max-age=31536000; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
      const page = document.documentElement.dataset;
      const step = `${page.zone || ''}>${zone}`;
      if (saved() === zone && page.zone !== zone && !('posted' in page)
          && sessionStorage.getItem('pdfmaster-ops-tz') !== step) {
        sessionStorage.setItem('pdfmaster-ops-tz', step);
        location.reload();
      }
    }
  } catch (_) { /* Without cookies or storage the next page simply stays in UTC. */ }
})();

(() => {
  let theme = 'light';
  try {
    if (localStorage.getItem('pdfmaster-ops-theme') === 'dark') theme = 'dark';
  } catch (_) { /* The theme switch also works when browser storage is disabled. */ }

  const apply = () => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      'content', theme === 'dark' ? '#0b111c' : '#f5f7fa'
    );
    document.querySelector('[data-theme-switch]')?.setAttribute(
      'aria-pressed', String(theme === 'dark')
    );
  };

  apply();
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.querySelector('[data-theme-switch]')?.addEventListener('click', () => {
      theme = theme === 'dark' ? 'light' : 'dark';
      apply();
      try { localStorage.setItem('pdfmaster-ops-theme', theme); } catch (_) { /* Optional persistence. */ }
    });
  });
})();
