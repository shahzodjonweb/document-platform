/**
 * Operations panel enhancements.
 *
 * Everything here is optional: without JavaScript the grant form still submits
 * and a document link still opens, it simply asks for the reason on the server
 * instead of collecting it first.
 */
(() => {
  const ready = (fn) =>
    document.readyState === 'loading'
      ? document.addEventListener('DOMContentLoaded', fn)
      : fn();

  ready(() => {
    // A top-up says what the balance will be, so nobody grants blind.
    const inputs = document.querySelectorAll('[data-grant-input]');
    const refresh = (input) => {
      const after = document.querySelector(`[data-grant-after="${input.name}"]`);
      if (!after) return;
      const remaining = Number(input.dataset.remaining || 0);
      const added = Math.max(0, Number(input.value || 0));
      const label = (after.textContent || '').split(':')[0];
      after.textContent = `${label}: ${remaining + added}`;
      after.classList.toggle('changed', added > 0);
    };
    inputs.forEach((input) => {
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

    // Opening a customer document is audited, so collect the reason first and
    // carry it with the request rather than letting the server reject it.
    const reason = document.getElementById('file-reason');
    const links = document.querySelectorAll('[data-file-open]');
    if (!reason || !links.length) return;
    const sync = () => {
      const value = reason.value.trim();
      links.forEach((link) => {
        const base = link.getAttribute('href').split('?')[0];
        link.setAttribute('href', value.length >= 5 ? `${base}?reason=${encodeURIComponent(value)}` : base);
        link.classList.toggle('disabled', value.length < 5);
        link.setAttribute('aria-disabled', String(value.length < 5));
      });
    };
    reason.addEventListener('input', sync);
    sync();
  });
})();
