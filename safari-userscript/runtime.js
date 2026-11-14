async function startFjordSeedUserscript(seedOrigin, cssText) {
  'use strict';

  const VERSION = '1.1.1';
  const PREFIX = 'fjordseed:pending:';
  const LIMIT_COUNT = 50;
  const LIMIT_BYTES = 8 * 1024 * 1024;
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const allowedFields = new Set(['version', 'id', 'seedOrigin', 'kind', 'created', 'expires',
    'sourceOrigin', 'sourcePath', 'base64', 'name', 'url']);
  const configuredOrigin = new URL(seedAddress(seedOrigin)).origin;
  const isSeed = location.origin === configuredOrigin;
  const isTracker = Object.hasOwn(TRACKER_ORIGINS, location.origin);
  if (window.top !== window || (!isSeed && !isTracker)) return {stop() {}};

  let stopped = false, running = false, leaseHeld = false, mutationChain = Promise.resolve();
  let notice = null, noticeText = null, retryButton = null, clearButton = null;
  let interval = null, lastNotice = '', dismissedNotice = '', expiryCount = 0;

  function friendly(value, fallback = 'Handlingen kunne ikke gennemføres. Prøv igen.') {
    if (typeof value !== 'string' || !value.trim()) return fallback;
    return value.replace(/https?:\/\/\S+|magnet:\S+/gi, '[link]')
      .replace(/\b(?:passkey|authkey|token|api[_-]?key)\s*[=:]\s*\S+/gi, '[privat værdi]').slice(0, 400);
  }

  function status(message, error = false, controls = false) {
    lastNotice = friendly(message);
    if (lastNotice === dismissedNotice) return;
    dismissedNotice = '';
    if (!notice?.isConnected) {
      notice = document.createElement('fjordseed-userscript-status');
      notice.style.cssText = 'all:initial!important;position:fixed!important;left:12px!important;right:12px!important;bottom:max(12px,env(safe-area-inset-bottom))!important;z-index:2147483646!important;';
      const shadow = notice.attachShadow({mode: 'open'});
      const style = document.createElement('style');
      style.textContent = ':host{font:14px/1.45 system-ui,sans-serif;color:#e7f0f5}*{box-sizing:border-box}.box{font:14px/1.45 system-ui,sans-serif;color:#e7f0f5;max-width:460px;margin:0 auto;padding:12px 14px;background:#14262c;border:1px solid #51776c;border-radius:12px;box-shadow:0 6px 24px #0005}.top{display:flex;align-items:center;gap:8px}.top p{flex:1;min-width:0}p{margin:0;overflow-wrap:anywhere}.error{color:#ffb9bd}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:9px}button{min-height:44px;padding:8px 12px;border:1px solid #7aa998;border-radius:8px;background:#95e5c8;color:#09281d;font:inherit;cursor:pointer}button:disabled{opacity:.6}button:focus-visible{outline:2px solid white;outline-offset:2px}.quiet{background:transparent;color:#deeee7}.dismiss{flex:none;width:44px;min-height:44px;padding:0;border:0;background:transparent;color:#deeee7;font-size:24px}[hidden]{display:none!important}';
      const box = document.createElement('div');
      box.className = 'box';
      noticeText = document.createElement('p');
      noticeText.setAttribute('role', 'status');
      noticeText.setAttribute('aria-live', 'polite');
      const top = document.createElement('div');
      top.className = 'top';
      const dismiss = document.createElement('button');
      dismiss.type = 'button';
      dismiss.className = 'dismiss';
      dismiss.textContent = '×';
      dismiss.setAttribute('aria-label', 'Luk besked');
      dismiss.addEventListener('click', event => {
        if (!event.isTrusted) return;
        dismissedNotice = lastNotice;
        notice?.remove();
      });
      top.append(noticeText, dismiss);
      const actions = document.createElement('div');
      actions.className = 'actions';
      retryButton = document.createElement('button');
      retryButton.type = 'button';
      retryButton.textContent = 'Fortsæt';
      retryButton.addEventListener('click', event => {
        if (event.isTrusted) void receive().catch(() => status('Overførslen kunne ikke fortsættes. Prøv igen.', true, true));
      });
      clearButton = document.createElement('button');
      clearButton.type = 'button';
      clearButton.className = 'quiet';
      clearButton.textContent = 'Ryd ventende links';
      clearButton.addEventListener('click', async event => {
        if (!event.isTrusted) return;
        if (running) { status('Vent, til den igangværende overførsel er færdig.', false, true); return; }
        clearButton.disabled = true;
        try {
          for (const item of await readQueue()) await GM.deleteValue(PREFIX + item.id);
          status('Ventende links er ryddet. Gemte pakker, feeds og downloads i FjordSeed er uændrede.');
        } catch { status('Ventende links kunne ikke ryddes. Kontrollér Userscripts-adgang.', true, true); }
        finally { clearButton.disabled = false; }
      });
      actions.append(retryButton, clearButton);
      box.append(top, actions);
      shadow.append(style, box);
      document.documentElement.append(notice);
    }
    noticeText.textContent = lastNotice;
    noticeText.classList.toggle('error', error);
    retryButton.hidden = clearButton.hidden = !controls;
  }

  if (typeof GM === 'undefined' ||
      ['getValue', 'setValue', 'deleteValue', 'listValues', 'openInTab'].some(name => typeof GM[name] !== 'function')) {
    status('FjordSeed mangler Userscripts-adgang. Installer scriptet i Userscripts, aktivér det i Safari, og giv adgang til trackersiderne og FjordSeed.', true);
    return {stop() { notice?.remove(); }};
  }

  function newId() {
    if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = bytes[6] & 15 | 64;
    bytes[8] = bytes[8] & 63 | 128;
    const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  const owner = newId();
  const leaseKey = 'fjordseed:delivery-lock:' + encodeURIComponent(configuredOrigin);
  const bytesOf = item => new TextEncoder().encode(JSON.stringify(item)).byteLength;

  function validRecord(item, key, now) {
    if (!item || typeof item !== 'object' || Array.isArray(item) ||
        Object.keys(item).some(field => !allowedFields.has(field)) ||
        item.version !== 1 || typeof item.id !== 'string' || !UUID.test(item.id) || key !== PREFIX + item.id ||
        item.seedOrigin !== configuredOrigin || !['torrent', 'rss', 'package'].includes(item.kind) ||
        !Number.isSafeInteger(item.created) || !Number.isSafeInteger(item.expires) ||
        item.created > now + 30000 || item.expires !== item.created + MAX_AGE || item.expires <= now ||
        !Object.hasOwn(TRACKER_ORIGINS, item.sourceOrigin)) return false;
    if (item.kind === 'rss') {
      if (typeof item.url !== 'string' || item.sourcePath !== undefined || item.base64 !== undefined || item.name !== undefined) return false;
      try { return rssLink(item.url) === item.url && new URL(item.url).origin === item.sourceOrigin; }
      catch { return false; }
    }
    if (item.url !== undefined || typeof item.sourcePath !== 'string' ||
        !/^\/torrents\/download\/[1-9]\d*\/?$/.test(item.sourcePath) ||
        typeof item.base64 !== 'string' || item.base64.length < 4 || item.base64.length % 4 !== 0 ||
        item.base64.length > Math.ceil(MAX_BYTES / 3) * 4 ||
        !/^[A-Za-z0-9+/]+={0,2}$/.test(item.base64)) return false;
    const id = item.sourcePath.split('/').filter(Boolean).at(-1);
    if (item.name !== `${TRACKER_ORIGINS[item.sourceOrigin]}-${id}.torrent`) return false;
    const padding = item.base64.endsWith('==') ? 2 : item.base64.endsWith('=') ? 1 : 0;
    if (item.base64.length / 4 * 3 - padding > MAX_BYTES) return false;
    try { return atob(item.base64.slice(0, 4))[0] === 'd' && atob(item.base64.slice(-4)).at(-1) === 'e'; }
    catch { return false; }
  }

  async function readQueue() {
    const keys = await GM.listValues();
    if (!Array.isArray(keys)) throw Error('Userscripts kunne ikke læse de ventende links.');
    const records = [];
    const now = Date.now();
    for (const key of keys.filter(key => typeof key === 'string' && key.startsWith(PREFIX))) {
      const item = await GM.getValue(key, null);
      if (!validRecord(item, key, now)) {
        if (item && Number.isFinite(item.expires) && item.expires <= now) expiryCount++;
        await GM.deleteValue(key);
        continue;
      }
      records.push(item);
    }
    records.sort((a, b) => a.created - b.created || a.id.localeCompare(b.id));
    // Per-item keys prevent simultaneous tracker tabs overwriting one another.
    // Recheck capacity after writes as well, so races cannot leave an oversized queue.
    const kept = [];
    let bytes = 0;
    for (const item of records) {
      const size = bytesOf(item);
      if (kept.length >= LIMIT_COUNT || bytes + size > LIMIT_BYTES) await GM.deleteValue(PREFIX + item.id);
      else { kept.push(item); bytes += size; }
    }
    return kept;
  }

  async function enqueue(type, value) {
    if (!isTracker) throw Error('Vælg linket på trackersiden.');
    const source = sourceLink(value);
    const url = new URL(source.url);
    if (url.origin !== location.origin) throw Error('Åbn linket på den tilhørende trackerside først.');
    if (type === 'package-add' && source.kind !== 'torrent') throw Error('RSS-feeds kan ikke føjes til en torrentpakke.');
    const created = Date.now();
    const record = {version: 1, id: newId(), seedOrigin: configuredOrigin,
      kind: type === 'package-add' ? 'package' : source.kind,
      created, expires: created + MAX_AGE, sourceOrigin: url.origin};
    if (source.kind === 'rss') record.url = source.url;
    else {
      let response;
      try {
        response = await fetch(source.url, {credentials: 'include', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(20000)});
      } catch { throw Error('Torrentfilen kunne ikke hentes. Kontrollér tracker-login og forbindelsen.'); }
      record.base64 = await readTorrent(response, TRACKER_ORIGINS[url.origin]);
      record.sourcePath = url.pathname;
      record.name = `${TRACKER_ORIGINS[url.origin]}-${url.pathname.split('/').filter(Boolean).at(-1)}.torrent`;
    }
    const queue = await readQueue();
    if (queue.length >= LIMIT_COUNT) throw Error('Der venter allerede 50 links. Åbn FjordSeed eller ryd de ventende links først.');
    if (queue.reduce((size, item) => size + bytesOf(item), 0) + bytesOf(record) > LIMIT_BYTES) {
      throw Error('De ventende filer fylder for meget. Åbn FjordSeed eller ryd dem før du vælger flere.');
    }
    await GM.setValue(PREFIX + record.id, record);
    if (!(await readQueue()).some(item => item.id === record.id)) {
      throw Error('Køen blev fuld. Åbn FjordSeed, og vælg derefter linket igen.');
    }
    if (type !== 'package-add') {
      try { await GM.openInTab(configuredOrigin, false); }
      catch { throw Error('Linket er gemt. Åbn FjordSeed i Safari for at fortsætte.'); }
    }
    return {ok: true, message: type === 'package-add'
      ? 'Føjet til ventende pakke. Tryk Åbn FjordSeed for at overføre den.'
      : 'Linket er gemt. Fortsæt i FjordSeed.'};
  }

  function serial(action) {
    const next = mutationChain.then(action);
    mutationChain = next.catch(() => {});
    return next;
  }

  if (isTracker) {
    try { await readQueue(); }
    catch { status('Userscripts kunne ikke åbne lageret. Kontrollér adgangen, og genindlæs siden.', true); return {stop() { notice?.remove(); }}; }
    mountFjordSeedPanel({
      runtime: {async sendMessage(message) {
        try {
          if (message?.type === 'package-open') {
            await readQueue();
            await GM.openInTab(configuredOrigin, false);
            return {ok: true, message: 'Fortsæt i FjordSeed. De ventende links overføres, når du er logget ind.'};
          }
          if (!['send-link', 'package-add'].includes(message?.type) || typeof message.url !== 'string') throw Error('Ukendt handling.');
          return await serial(() => enqueue(message.type, message.url));
        } catch (error) { return {error: friendly(error.message)}; }
      }},
      storage: {local: {async get() { return {showButtons: true}; }}, onChanged: {addListener() {}}}
    }, cssText);
    return {stop() { stopped = true; notice?.remove(); }};
  }

  document.documentElement.dataset.fjordseedUserscript = VERSION;

  async function deliverQueue() {
    if (stopped || document.visibilityState === 'hidden' || !document.querySelector('#add-form')) return;
    const queue = await readQueue();
    if (!queue.length) {
      if (expiryCount) { status(`${expiryCount} ventende links er udløbet efter 15 minutter. Vælg dem igen på trackeren.`, true); expiryCount = 0; }
      return;
    }
    for (const item of queue) {
      if (stopped || document.visibilityState === 'hidden') break;
      if (leaseHeld) {
        if ((await GM.getValue(leaseKey, null))?.owner !== owner) break;
        await GM.setValue(leaseKey, {owner, expires: Date.now() + 60000});
      }
      // Re-read immediately before acting: another tab or a clear action may
      // have removed a record since the initial snapshot.
      const current = await GM.getValue(PREFIX + item.id, null);
      if (!validRecord(current, PREFIX + item.id, Date.now())) continue;
      let outcome;
      if (item.kind === 'package') {
        outcome = await stageTorrent(item.base64, item.name, configuredOrigin);
        if (outcome?.status === 'stored') {
          await GM.deleteValue(PREFIX + item.id);
          status(`${outcome.count} torrents ligger klar i FjordSeed-pakken. Gennemse pakken og vælg indstillinger før start.`);
          continue;
        }
        if (outcome?.status === 'login') return;
        status(friendly(outcome?.message, 'Pakken kunne ikke overføres. Opdatér FjordSeed, og prøv igen.'), true, true);
        break;
      }
      outcome = item.kind === 'rss'
        ? showRss(item.url, item.id, configuredOrigin)
        : await showTorrent(item.base64, item.name, item.id, configuredOrigin);
      if (outcome === 'delivered') {
        await GM.deleteValue(PREFIX + item.id);
        status(item.kind === 'rss' ? 'RSS-linket er klar. Vælg indstillinger, og tryk Gem feed.' : 'Torrenten er klar. Vælg indstillinger, og tryk Start download.');
        // A single-link handoff opens a dialog; leave subsequent links pending.
        break;
      }
      if (outcome === 'login') return;
      const messages = {
        busy: 'Et link venter. Afslut eller luk den åbne dialog, og tryk Fortsæt.',
        offline: 'Et link venter. Kontrollér FjordSeeds VPN-forbindelse, og tryk Fortsæt.',
        incompatible: 'FjordSeed skal opdateres for at modtage linket.'
      };
      status(messages[outcome] || 'Linket kunne ikke overføres. Prøv igen.', true, true);
      break;
    }
  }

  async function withLease(action) {
    // Web Locks serialize receiver tabs on the same exact FjordSeed origin.
    if (navigator.locks?.request) {
      await navigator.locks.request('fjordseed-userscript-delivery', {ifAvailable: true}, async lock => { if (lock) await action(); });
      return;
    }
    // The Userscripts store is shared across tabs. A short lease also covers
    // older browsers without Web Locks; expired leases recover after a closed tab.
    const now = Date.now();
    const lease = await GM.getValue(leaseKey, null);
    if (lease && lease.owner !== owner && Number.isFinite(lease.expires) && lease.expires > now && lease.expires <= now + 120000) return;
    await GM.setValue(leaseKey, {owner, expires: now + 60000});
    await new Promise(resolve => setTimeout(resolve, 80));
    if ((await GM.getValue(leaseKey, null))?.owner !== owner) return;
    leaseHeld = true;
    try { await action(); }
    finally {
      leaseHeld = false;
      if ((await GM.getValue(leaseKey, null))?.owner === owner) await GM.deleteValue(leaseKey);
    }
  }

  async function receive() {
    if (running || stopped || document.visibilityState === 'hidden' || !document.querySelector('#add-form')) return;
    running = true;
    try { await withLease(deliverQueue); }
    catch { status('Overførslen kunne ikke afsluttes. Kontrollér Userscripts-adgang og forbindelsen, og tryk Fortsæt.', true, true); }
    finally { running = false; }
  }

  const onFocus = () => { void receive(); };
  const onVisibility = () => { if (document.visibilityState !== 'hidden') void receive(); };
  window.addEventListener('focus', onFocus);
  document.addEventListener('visibilitychange', onVisibility);
  interval = setInterval(() => { if (document.visibilityState !== 'hidden') void receive(); }, 5000);
  // Purge expired private data even on the login/setup page; delivery waits for
  // the normal signed-in FjordSeed interface and never starts a download.
  try { await readQueue(); }
  catch { status('Userscripts kunne ikke læse de ventende links. Kontrollér adgangen.', true); }
  await receive();
  return {stop() {
    stopped = true;
    clearInterval(interval);
    window.removeEventListener('focus', onFocus);
    document.removeEventListener('visibilitychange', onVisibility);
    notice?.remove();
  }};
}
