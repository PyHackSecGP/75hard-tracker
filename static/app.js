// Keyboard shortcuts + small UX helpers for the tracker.
(() => {
  const focusLog = () => {
    const el = document.getElementById('log-input');
    if (el) { el.focus(); el.select?.(); }
  };

  document.addEventListener('keydown', (e) => {
    const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName);

    // n = focus hero log input (unless typing in another field)
    if (e.key === 'n' && !typing) { e.preventDefault(); focusLog(); }

    // Ctrl/Cmd + Enter inside hero log textarea = submit
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      const ta = document.getElementById('log-input');
      if (ta && document.activeElement === ta) {
        ta.form?.requestSubmit();
      }
    }
  });

  // After HTMX replaces a tick, flash green briefly to confirm
  document.body.addEventListener('htmx:afterSwap', (ev) => {
    const tick = ev.detail?.target;
    if (tick?.classList?.contains('gps-tick') && tick.classList.contains('done')) {
      tick.animate(
        [{ transform: 'scale(1)' }, { transform: 'scale(1.25)' }, { transform: 'scale(1)' }],
        { duration: 250, easing: 'ease-out' }
      );
    }
  });
})();
