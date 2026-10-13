/**
 * Operations panel enhancements.
 *
 * The menu drawer on narrow screens, the dialogs for plan and limit changes,
 * and closing menus on an outside click.
 */
(() => {
  const ready = (fn) =>
    document.readyState === 'loading'
      ? document.addEventListener('DOMContentLoaded', fn)
      : fn();

  ready(() => {
    // The sidebar as a drawer below 960px.
    const toggle = document.querySelector('[data-nav-toggle]');
    const setNav = (open) => {
      document.body.classList.toggle('nav-open', open);
      toggle?.setAttribute('aria-expanded', String(open));
      if (open) document.querySelector('#sidebar .nav-link')?.focus();
    };
    toggle?.addEventListener('click', () => setNav(!document.body.classList.contains('nav-open')));
    document.querySelectorAll('[data-nav-close]').forEach((el) =>
      el.addEventListener('click', () => setNav(false))
    );
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && document.body.classList.contains('nav-open')) {
        setNav(false);
        toggle?.focus();
      }
    });

    // A button names the dialog it opens; the backdrop and Cancel close it.
    document.querySelectorAll('[data-dialog-open]').forEach((button) => {
      const dialog = document.getElementById(button.dataset.dialogOpen);
      if (!dialog || typeof dialog.showModal !== 'function') return;
      button.addEventListener('click', () => dialog.showModal());
    });
    document.querySelectorAll('dialog').forEach((dialog) => {
      dialog.addEventListener('click', (event) => {
        if (event.target === dialog) dialog.close();
      });
      dialog.querySelectorAll('[data-dialog-close]').forEach((button) =>
        button.addEventListener('click', () => dialog.close())
      );
    });

    // Menus built on <details> close when you click elsewhere.
    document.addEventListener('click', (event) => {
      document.querySelectorAll('details.language-menu[open], details.more-filters[open]').forEach((menu) => {
        if (!menu.contains(event.target)) menu.removeAttribute('open');
      });
    });
  });
})();
