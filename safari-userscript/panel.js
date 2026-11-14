function mountFjordSeedPanel(api, cssText) {
  'use strict';
  const trackers = {
    'https://nordicbytes.org': 'NordicBytes',
    'https://sagmire.org': 'Sagmire'
  };
  if (window.top !== window || !Object.hasOwn(trackers, location.origin) ||
      !api?.runtime?.sendMessage || globalThis.__fjordseedSafariPanel) return;
  globalThis.__fjordseedSafariPanel = true;
  const documentStyle = document.createElement('style');
  documentStyle.textContent = cssText;
  document.documentElement.append(documentStyle);

  // Match common.mjs link shapes, restricted to this tracker's origin so the
  // runtime can fetch with this tab's login. Private URLs stay in script
  // state; the panel receives labels, never tracker URLs or RSS passkeys.
  function sourceLink(value) {
    try {
      const url = new URL(value);
      if (url.origin !== location.origin || !Object.hasOwn(trackers, url.origin) ||
          url.username || url.password) return null;
      let kind;
      if (/^\/torrents\/download\/[1-9]\d*\/?$/.test(url.pathname)) kind = 'torrent';
      else if (url.href.length <= 4096 &&
          /^\/(?:torrents\/)?rss(?:\.(?:xml|php))?(?:\/|$)/i.test(url.pathname) &&
          !/\/(?:create|edit|delete|manage)(?:\/|$)/i.test(url.pathname)) kind = 'rss';
      else return null;
      url.hash = '';
      return {kind, url: url.href, tracker: trackers[url.origin]};
    } catch { return null; }
  }

  function labelFor(link, item) {
    const id = new URL(item.url).pathname.split('/').filter(Boolean).at(-1);
    const fallback = item.kind === 'rss' ? `${item.tracker} · RSS-feed` : `${item.tracker} · Torrent #${id}`;
    function readable(value) {
      const label = (value || '').replace(/\s+/g, ' ').trim();
      // Trackers may use the full private feed address as link text. Generic
      // download/icon labels also don't identify which torrent was selected.
      const secretField = /(?:^|[?&;\s])(?:passkey|authkey|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|pwd|auth|key|rss[_-]?(?:key|token)|pk)\s*[=:]/i.test(label);
      const privateRssLabel = item.kind === 'rss' && (
        /(?:^|[?&])[^\s=?&]+=[^\s&]*/.test(label) ||
        /^\/?(?:torrents\/)?rss(?:[/.?]|$)/i.test(label) ||
        /^[A-Za-z0-9_-]{24,}={0,2}$/.test(label)
      );
      if (!label || /https?:\/\/|magnet:/i.test(label) || secretField || privateRssLabel ||
          !/[A-Za-zÆØÅæøå0-9]/.test(label) ||
          /^(?:download|download torrent|download torrent file|hent|hent torrent|hent torrentfil|torrent|rss|rss-feed|feed|åbn|open)[\s.!…]*$/i.test(label)) return null;
      return label.length > 120 ? label.slice(0, 117) + '…' : label;
    }
    function labelOf(anchor) {
      return readable(anchor.getAttribute('aria-label')) || readable(anchor.getAttribute('title')) || readable(anchor.textContent);
    }
    const ownLabel = labelOf(link);
    if (ownLabel) return ownLabel;
    if (item.kind === 'torrent') {
      // Only use a nearby details link with this exact torrent ID and tracker.
      // This never picks the first title from a row containing several torrents.
      let container = link.parentElement;
      for (let depth = 0; container && container !== document.body && depth < 5; depth++, container = container.parentElement) {
        for (const candidate of [...container.querySelectorAll('a[href*="/torrents/"]')].slice(0, 200)) {
          try {
            const url = new URL(candidate.href);
            if (url.origin === new URL(item.url).origin &&
                (url.pathname === `/torrents/${id}` || url.pathname === `/torrents/${id}/`)) {
              const title = labelOf(candidate);
              if (title) return title;
            }
          } catch { /* Ignore unrelated malformed links. */ }
        }
      }
    }
    return fallback;
  }

  function safeMessage(message, fallback) {
    if (typeof message !== 'string' || !message.trim()) return fallback;
    return message.replace(/https?:\/\/\S+|magnet:\S+/gi, '[link]').slice(0, 400);
  }

  const MAX_LINKS = 100;
  let enabled = true, timer = null, host = null, shadow = null;
  let tab = null, panel = null, list = null, count = null, overflow = null, showAll = null;
  let items = new Map(), cards = new Map(), opened = false, settingsRevision = 0;
  let selectedUrl = null, selectedItem = null, gesture = null, suppressedClick = null, suppressionTimer = null;
  const eligibleLinks = new Set();

  function cancelGesture() {
    if (gesture) clearTimeout(gesture.timer);
    gesture = null;
  }

  function suppressNextClick(anchor) {
    clearTimeout(suppressionTimer);
    suppressedClick = {anchor, expires: Date.now() + 1000};
    suppressionTimer = setTimeout(() => { suppressedClick = null; }, 1000);
  }

  function closePanel(restoreFocus = false) {
    if (!panel) return;
    opened = false;
    panel.hidden = true;
    tab.hidden = false;
    tab.setAttribute('aria-expanded', 'false');
    if (restoreFocus) tab.focus();
  }

  function removePanel() {
    host?.remove();
    host = shadow = tab = panel = list = count = overflow = showAll = null;
    cards.clear();
    opened = false;
    selectedUrl = null;
    selectedItem = null;
  }

  function openPanel(url = null) {
    selectedUrl = url;
    selectedItem = url ? items.get(url) : null;
    render();
    if (!panel) return;
    opened = true;
    tab.hidden = true;
    panel.hidden = false;
    tab.setAttribute('aria-expanded', 'true');
    panel.querySelector('.close').focus();
  }

  function element(name, className, text) {
    const node = document.createElement(name);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function ensurePanel() {
    if (host?.isConnected) return;
    host = document.createElement('fjordseed-safari-panel');
    // The host is fixed; all styles are bundled locally with the userscript.
    host.style.cssText = 'all:initial!important;position:fixed!important;right:0!important;top:50%!important;z-index:2147483647!important;';
    shadow = host.attachShadow({mode: 'open'});
    const sheet = document.createElement('style');
    sheet.textContent = cssText;
    shadow.append(sheet);

    tab = element('button', 'fjordseed-tab');
    tab.type = 'button';
    tab.setAttribute('aria-expanded', 'false');
    tab.setAttribute('aria-controls', 'fjordseed-links');
    tab.append(element('span', 'tab-name', 'FjordSeed'), element('span', 'tab-count'));
    panel = element('section', 'fjordseed-panel');
    panel.id = 'fjordseed-links';
    panel.hidden = true;
    panel.setAttribute('aria-label', 'FjordSeed-links på denne side');
    const heading = element('div', 'panel-heading');
    const title = element('div', 'panel-title');
    title.append(element('h2', '', 'FjordSeed'));
    count = element('p', 'link-count');
    title.append(count);
    const close = element('button', 'close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Luk FjordSeed-panelet');
    close.addEventListener('click', event => {
      if (!event.isTrusted) return;
      event.preventDefault();
      event.stopPropagation();
      closePanel(true);
    });
    heading.append(title, close);
    list = element('div', 'links');
    showAll = element('button', 'show-all', 'Vis alle links');
    showAll.type = 'button';
    showAll.hidden = true;
    showAll.addEventListener('click', event => {
      if (!event.isTrusted) return;
      event.preventDefault();
      event.stopPropagation();
      selectedUrl = null;
      selectedItem = null;
      render();
      list.querySelector('button')?.focus();
    });
    overflow = element('p', 'overflow-note', 'Viser de første 100 links. Åbn en detaljeside for at vælge andre.');
    overflow.hidden = true;
    const footer = element('div', 'panel-footer');
    const openSeed = element('button', 'action open-seed', 'Åbn FjordSeed');
    openSeed.type = 'button';
    const footerStatus = element('p', 'feedback');
    footerStatus.setAttribute('role', 'status');
    footerStatus.hidden = true;
    openSeed.addEventListener('click', async event => {
      if (!event.isTrusted) return;
      event.preventDefault();
      event.stopPropagation();
      openSeed.disabled = true;
      try {
        const result = await api.runtime.sendMessage({type: 'package-open'});
        if (!result?.ok) throw Error(result?.error || 'FjordSeed kunne ikke åbnes.');
        footerStatus.textContent = result.message || 'Fortsæt i FjordSeed.';
        footerStatus.classList.remove('error');
      } catch (error) {
        footerStatus.textContent = safeMessage(error.message, 'Åbn FjordSeed i Safari for at fortsætte.');
        footerStatus.classList.add('error');
      } finally {
        footerStatus.hidden = false;
        openSeed.disabled = false;
      }
    });
    footer.append(openSeed, element('p', '', 'Du vælger indstillinger og starter i FjordSeed.'), footerStatus);
    panel.append(heading, showAll, list, overflow, footer);
    shadow.append(tab, panel);
    tab.addEventListener('click', event => {
      if (!event.isTrusted) return;
      event.preventDefault();
      event.stopPropagation();
      openPanel();
    });
    shadow.addEventListener('keydown', event => {
      if (event.isTrusted && event.key === 'Escape' && opened) {
        event.preventDefault();
        event.stopPropagation();
        closePanel(true);
      }
    });
    document.documentElement.append(host);
  }

  function createCard(item) {
    const card = element('article', 'link-card');
    const meta = element('p', 'link-meta', `${item.tracker} · ${item.kind === 'rss' ? 'RSS-feed' : 'Torrent'}`);
    const label = element('h3', 'link-label', item.label);
    const actions = element('div', 'link-actions');
    const feedback = element('p', 'feedback');
    feedback.setAttribute('role', 'status');
    feedback.setAttribute('aria-live', 'polite');
    feedback.hidden = true;
    const buttons = [];
    let available = true, busy = false;

    function addButton(type, text, quiet = false) {
      const button = element('button', quiet ? 'action quiet' : 'action', text);
      button.type = 'button';
      button.addEventListener('click', async event => {
        if (!event.isTrusted) return;
        event.preventDefault();
        event.stopPropagation();
        // Revalidate the current selection; page updates can remove links while
        // the panel is open. The userscript runtime independently checks every message.
        const selected = items.get(item.url);
        const validated = selected && sourceLink(selected.url);
        if (!validated || (type === 'package-add' && validated.kind !== 'torrent')) {
          feedback.textContent = 'Linket findes ikke længere på siden. Åbn panelet igen.';
          feedback.hidden = false;
          feedback.classList.add('error');
          scheduleScan();
          return;
        }
        busy = true;
        buttons.forEach(control => { control.disabled = true; });
        feedback.classList.remove('error');
        feedback.hidden = false;
        feedback.textContent = 'Sender linket…';
        try {
          const result = await api.runtime.sendMessage({type, url: validated.url});
          if (!result?.ok) throw Error(safeMessage(result?.error, 'Linket kunne ikke sendes. Åbn FjordSeed i Safari for at prøve igen.'));
          feedback.textContent = safeMessage(result.message, type === 'package-add'
            ? 'Valgt til pakken. Tryk Åbn FjordSeed for at fortsætte.'
            : 'Linket er sendt videre. Fortsæt i FjordSeed.');
        } catch (error) {
          feedback.classList.add('error');
          feedback.textContent = safeMessage(error.message, 'Åbn FjordSeed i Safari og prøv igen.');
        } finally {
          busy = false;
          buttons.forEach(control => { control.disabled = !available; });
        }
      });
      buttons.push(button);
      actions.append(button);
    }
    addButton('send-link', 'Send til FjordSeed');
    if (item.kind === 'torrent') addButton('package-add', 'Føj til pakke', true);
    card.append(meta, label, actions, feedback);
    if (item.kind === 'torrent') {
      const audio = element('section', 'audio-info');
      audio.setAttribute('aria-label', 'Lydspor');
      const showAudio = element('button', 'action quiet audio-toggle', 'Vis lydspor');
      showAudio.type = 'button';
      const result = element('div', 'audio-result');
      result.hidden = true;
      const status = element('p', 'audio-status');
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      const tracks = element('ol', 'audio-tracks');
      result.append(status, tracks);
      audio.append(showAudio, result);
      card.append(audio);
      let loaded = false;
      showAudio.addEventListener('click', async event => {
        if (!event.isTrusted || !available) return;
        event.preventDefault();
        event.stopPropagation();
        if (loaded) {
          result.hidden = !result.hidden;
          showAudio.textContent = result.hidden ? 'Vis lydspor' : 'Skjul lydspor';
          showAudio.setAttribute('aria-expanded', String(!result.hidden));
          return;
        }
        if (!items.has(item.url)) return;
        showAudio.disabled = true;
        showAudio.setAttribute('aria-expanded', 'true');
        result.hidden = false;
        result.setAttribute('aria-busy', 'true');
        status.textContent = 'Henter lydspor fra detaljesiden…';
        try {
          const labels = await loadFjordSeedAudio(item.url);
          tracks.replaceChildren(...labels.map(text => element('li', '', text)));
          status.textContent = labels.length ? `${labels.length} lydspor · fra trackerens MediaInfo` :
            'Ingen lydoplysninger fundet på detaljesiden. Det betyder ikke, at filen er uden lyd.';
          loaded = true;
          showAudio.textContent = 'Skjul lydspor';
        } catch (error) {
          status.textContent = safeMessage(error.message, 'Lydsporene kunne ikke hentes.');
          showAudio.textContent = 'Prøv lydspor igen';
        } finally {
          result.setAttribute('aria-busy', 'false');
          showAudio.disabled = !available;
        }
      });
      showAudio.setAttribute('aria-expanded', 'false');
      buttons.push(showAudio);
    }
    return {node: card, label, setAvailable(value) {
      if (available === value) return;
      available = value;
      buttons.forEach(control => { control.disabled = busy || !available; });
      if (!available) {
        feedback.hidden = false;
        feedback.classList.add('error');
        feedback.textContent = 'Linket findes ikke længere på siden. Vælg Vis alle links for at vælge igen.';
      } else if (!busy) {
        feedback.hidden = true;
      }
    }};
  }

  function render() {
    if (!enabled || !items.size) { removePanel(); return; }
    ensurePanel();
    const number = `${items.size}`;
    tab.querySelector('.tab-count').textContent = number;
    tab.setAttribute('aria-label', `FjordSeed: ${number} links på siden`);
    count.textContent = selectedUrl ? 'Valgt link' : `${number} ${items.size === 1 ? 'link' : 'links'} på denne side`;
    showAll.hidden = !selectedUrl;
    overflow.hidden = !!selectedUrl || items.size <= MAX_LINKS;
    const visible = new Map(selectedUrl && selectedItem
      ? [[selectedUrl, selectedItem]] : [...items].slice(0, MAX_LINKS));
    for (const [url, card] of cards) {
      if (!visible.has(url)) { card.node.remove(); cards.delete(url); }
    }
    let position = 0;
    for (const [url, item] of visible) {
      let card = cards.get(url);
      if (!card) { card = createCard(item); cards.set(url, card); }
      if (card.label.textContent !== item.label) card.label.textContent = item.label;
      card.setAvailable(items.has(url));
      if (list.children[position] !== card.node) list.insertBefore(card.node, list.children[position] || null);
      position++;
    }
  }

  function scan() {
    if (!enabled) return;
    const next = new Map();
    const activeLinks = new Set();
    for (const link of document.querySelectorAll('a[href]')) {
      const item = sourceLink(link.href);
      if (!item) continue;
      activeLinks.add(link);
      link.classList.add('fjordseed-longpress-link');
      if (!next.has(item.url)) next.set(item.url, {...item, label: labelFor(link, item)});
    }
    for (const link of eligibleLinks) {
      if (!activeLinks.has(link)) {
        link.classList.remove('fjordseed-longpress-link');
        eligibleLinks.delete(link);
        if (gesture?.anchor === link) cancelGesture();
        if (suppressedClick?.anchor === link) {
          suppressedClick = null;
          clearTimeout(suppressionTimer);
        }
      }
    }
    for (const link of activeLinks) eligibleLinks.add(link);
    items = next;
    render();
  }

  function scheduleScan() {
    if (!enabled || timer !== null) return;
    // Coalesce page changes, and never observe changes inside our shadow root.
    timer = setTimeout(() => { timer = null; scan(); }, 150);
  }

  const observer = new MutationObserver(mutations => {
    if (!enabled) return;
    if (mutations.some(mutation => mutation.type === 'attributes' ||
      [...mutation.addedNodes, ...mutation.removedNodes].some(node =>
        node.nodeType === Node.ELEMENT_NODE && node !== host && node.localName !== 'fjordseed-safari-panel'))) scheduleScan();
  });
  observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['href']});
  document.addEventListener('pointerdown', event => {
    if (event.isTrusted && opened && host && event.target !== host && !host.contains(event.target)) closePanel();
  }, true);

  function anchorAt(target) {
    return target instanceof Element ? target.closest('a[href]') : null;
  }

  document.addEventListener('pointerdown', event => {
    if (!event.isTrusted || !enabled || event.pointerType !== 'touch') return;
    cancelGesture();
    if (event.isPrimary === false || event.button !== 0) return;
    const anchor = anchorAt(event.target);
    const selected = anchor && sourceLink(anchor.href);
    if (!selected) return;
    anchor.classList.add('fjordseed-longpress-link');
    eligibleLinks.add(anchor);
    const current = {anchor, url: selected.url, pointerId: event.pointerId,
      x: event.clientX, y: event.clientY, fired: false, timer: null};
    gesture = current;
    current.timer = setTimeout(() => {
      if (!enabled || gesture !== current || !anchor.isConnected ||
          sourceLink(anchor.href)?.url !== current.url) return;
      current.fired = true;
      suppressNextClick(anchor);
      scan();
      openPanel(current.url);
    }, 550);
    // Do not prevent pointerdown: a normal tap, swipe or pinch remains native.
  }, {capture: true, passive: true});

  document.addEventListener('pointermove', event => {
    if (!event.isTrusted || gesture?.pointerId !== event.pointerId) return;
    if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 10) cancelGesture();
  }, {capture: true, passive: true});

  document.addEventListener('pointerup', event => {
    if (!event.isTrusted || gesture?.pointerId !== event.pointerId) return;
    if (gesture.fired) suppressNextClick(gesture.anchor);
    cancelGesture();
  }, {capture: true, passive: true});
  document.addEventListener('pointercancel', event => {
    if (event.isTrusted && gesture?.pointerId === event.pointerId) cancelGesture();
  }, {capture: true, passive: true});
  document.addEventListener('scroll', cancelGesture, {capture: true, passive: true});

  document.addEventListener('click', event => {
    if (!event.isTrusted || !suppressedClick || Date.now() > suppressedClick.expires ||
        anchorAt(event.target) !== suppressedClick.anchor) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    suppressedClick = null;
    clearTimeout(suppressionTimer);
  }, true);

  document.addEventListener('contextmenu', event => {
    if (!event.isTrusted || !enabled) return;
    const anchor = anchorAt(event.target);
    if (anchor && (gesture?.anchor === anchor ||
        (suppressedClick?.anchor === anchor && Date.now() <= suppressedClick.expires))) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);

  api.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !Object.hasOwn(changes, 'showButtons')) return;
    settingsRevision++;
    enabled = changes.showButtons.newValue !== false;
    if (enabled) scheduleScan();
    else {
      cancelGesture();
      suppressedClick = null;
      clearTimeout(suppressionTimer);
      for (const link of eligibleLinks) link.classList.remove('fjordseed-longpress-link');
      eligibleLinks.clear();
      items.clear();
      removePanel();
    }
  });
  const initialRevision = settingsRevision;
  api.storage.local.get('showButtons').then(settings => {
    if (settingsRevision === initialRevision) enabled = settings.showButtons !== false;
    scheduleScan();
  }).catch(() => scheduleScan());
}
