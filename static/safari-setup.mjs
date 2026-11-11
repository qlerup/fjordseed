// Browser detection is presentation logic, never an authorization boundary.
export function isIPhoneSafari({userAgent = '', standalone = false, displayModeStandalone = false} = {}) {
  return !standalone && !displayModeStandalone &&
    /\biPhone\b/i.test(userAgent) && /\bAppleWebKit\//i.test(userAgent) &&
    /\bVersion\/[\d.]+/i.test(userAgent) && /\bMobile\//i.test(userAgent) &&
    /\bSafari\//i.test(userAgent) &&
    !/(CriOS|FxiOS|EdgiOS|EdgA|OPiOS|DuckDuckGo|Ddg|GSA\/|FBAN|FBAV|Instagram|Twitter|Line\/)/i.test(userAgent);
}

export function initSafariSetup(doc = document, view = window) {
  const trigger = doc.getElementById('safari-setup-open');
  const dialog = doc.getElementById('safari-setup-dialog');
  const address = doc.getElementById('safari-setup-address');
  const copy = doc.getElementById('safari-setup-copy');
  const feedback = doc.getElementById('safari-setup-copy-status');
  const installer = doc.getElementById('safari-setup-install');
  const detected = doc.getElementById('safari-setup-detected');
  if (!trigger || !dialog || !address || !copy || !feedback || !installer || !detected) return;

  const standalone = view.matchMedia?.('(display-mode: standalone)');
  const fullscreen = view.matchMedia?.('(display-mode: fullscreen)');
  const eligible = () => isIPhoneSafari({
    userAgent: view.navigator.userAgent,
    standalone: view.navigator.standalone === true,
    displayModeStandalone: !!standalone?.matches || !!fullscreen?.matches,
  });
  const updateVisibility = () => {
    trigger.hidden = !eligible();
    if (trigger.hidden && dialog.open) dialog.close();
  };
  const updateInstalled = () => {
    // A UX hint supplied by the running script, not a trusted security signal.
    detected.hidden = !doc.documentElement.dataset.fjordseedUserscript;
  };
  const updateAddress = () => {
    address.value = view.location.origin + '/';
    const source = new URL('/browser/fjordseed.user.js', view.location.origin);
    source.searchParams.set('origin', view.location.origin);
    installer.href = source.href;
  };

  trigger.addEventListener('click', () => {
    if (!eligible()) return;
    // The browser's exact origin keeps HTTPS and non-default ports, without
    // copying login paths, hash routes or private query parameters.
    updateAddress();
    updateInstalled();
    feedback.textContent = '';
    dialog.showModal();
    doc.getElementById('safari-setup-title').focus();
  });
  dialog.querySelectorAll('[data-safari-setup-close]').forEach(button => {
    button.addEventListener('click', () => dialog.close());
  });
  dialog.addEventListener('close', () => {
    if (!trigger.hidden) trigger.focus();
  });
  copy.addEventListener('click', async () => {
    feedback.textContent = '';
    try {
      if (!view.navigator.clipboard?.writeText) throw Error('Clipboard unavailable');
      await view.navigator.clipboard.writeText(address.value);
      feedback.textContent = 'Adressen er kopieret.';
    } catch {
      // Local HTTP installations may not expose the Clipboard API. Leave a
      // selected, readable address for manual copying if the fallback fails.
      address.focus();
      address.select();
      address.setSelectionRange(0, address.value.length);
      let copied = false;
      try { copied = doc.execCommand?.('copy') === true; } catch { /* Manual copy remains available. */ }
      feedback.textContent = copied ? 'Adressen er kopieret.' :
        'Adressen er markeret. Hold fingeren på feltet, og vælg Kopiér.';
    }
  });

  standalone?.addEventListener?.('change', updateVisibility);
  fullscreen?.addEventListener?.('change', updateVisibility);
  view.addEventListener('pageshow', updateVisibility);
  if (view.MutationObserver) {
    new view.MutationObserver(updateInstalled).observe(doc.documentElement, {
      attributes: true, attributeFilter: ['data-fjordseed-userscript'],
    });
  }
  updateAddress();
  updateInstalled();
  updateVisibility();
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') {
  initSafariSetup();
}
