/**
 * Operations panel enhancements.
 *
 * The menu drawer on narrow screens, the dialogs for plan, credit and limit
 * changes, closing menus on an outside click, and the live balance in the
 * credit form.
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

    // A top-up says what the balance will be, so nobody grants blind.
    const refresh = (input) => {
      const after = document.querySelector(`[data-grant-after="${input.name}"]`);
      if (!after) return;
      const remaining = Number(input.dataset.remaining || 0);
      const added = Math.max(0, Number(input.value || 0));
      const label = (after.textContent || '').split(':')[0];
      after.textContent = `${label}: ${remaining + added}`;
      after.classList.toggle('changed', added > 0);
    };
    document.querySelectorAll('[data-grant-input]').forEach((input) => {
      input.addEventListener('input', () => refresh(input));
      refresh(input);
    });
    document.querySelectorAll('[data-grant-preset]').forEach((button) => {
      button.addEventListener('click', () => {
        const input = document.querySelector(`[name="${button.dataset.grantPreset}"][data-grant-input]`);
        if (!input) return;
        input.value = String(Math.max(0, Number(input.value || 0)) + Number(button.dataset.amount || 0));
        refresh(input);
      });
    });
  });
})();
