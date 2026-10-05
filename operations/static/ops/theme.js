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
