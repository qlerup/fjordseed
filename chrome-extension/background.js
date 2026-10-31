import {sourceLink, seedAddress, permissionOrigin, readTorrent, showTorrent, showRss, selectSeedTab, MAX_AGE, TRACKER_ORIGINS} from './common.mjs';
import {createPackageDelivery} from './package.mjs';

const MENU = 'send-fjordseed';
const PACKAGE_MENU = 'package-fjordseed';
const packageDelivery = createPackageDelivery({destination,status});
let working = false;
let delivering = false;

async function status(message, error = false) {
  await chrome.storage.session.set({status: message});
  await chrome.action.setBadgeText({text: error ? '!' : ''});
  await chrome.action.setBadgeBackgroundColor({color: '#af354b'});
  await chrome.action.setTitle({title: 'FjordSeed: ' + message});
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({id: MENU, title: 'Send til FjordSeed', contexts: ['link'],
    targetUrlPatterns: Object.keys(TRACKER_ORIGINS).flatMap(origin => [origin+'/torrents/download/*', origin+'/rss*', origin+'/torrents/rss*'])});
  chrome.contextMenus.create({id:PACKAGE_MENU,title:'Føj til torrentpakke (flere)',contexts:['link'],
    targetUrlPatterns:Object.keys(TRACKER_ORIGINS).map(origin=>origin+'/torrents/download/*')});
});

async function destination() {
  const {seedUrl} = await chrome.storage.local.get('seedUrl');
  if (!seedUrl) throw Error('Åbn FjordSeed-udvidelsen og gem din FjordSeed-adresse først.');
  const url = seedAddress(seedUrl);
  if (!await chrome.permissions.contains({origins: [permissionOrigin(url)]})) {
    throw Error('Åbn udvidelsen og gem adressen igen for at give adgang til FjordSeed.');
  }
  return url;
}

async function openDestination(seedUrl, preferredId) {
  const tabs = await chrome.tabs.query({url: permissionOrigin(seedUrl)});
  const existing = selectSeedTab(tabs, seedUrl, preferredId);
  const tab = existing
    ? await chrome.tabs.update(existing.id, {active: true})
    : await chrome.tabs.create({url: seedUrl});
  await chrome.windows.update(tab.windowId, {focused: true});
  return tab;
}

async function begin(link) {
  if (working) throw Error('En overførsel er allerede i gang.');
  working = true;
  try {
    const {kind, url} = sourceLink(link), seedUrl = await destination();
    const {pending} = await chrome.storage.session.get('pending');
    if (pending && Date.now() - pending.created < MAX_AGE) {
      throw Error('Der ligger allerede et link klar. Åbn udvidelsen for at fortsætte eller rydde det.');
    }
    await chrome.storage.session.remove('pending');
    let item;
    if (kind === 'rss') {
      // RSS URLs can contain passkeys: never put them in the destination URL or fetch them here.
      item = {id: crypto.randomUUID(), kind, seedUrl, url, created: Date.now()};
    } else {
      const trackerName = TRACKER_ORIGINS[new URL(url).origin];
      await status('Henter torrentfilen fra '+trackerName+'…');
      let response;
      try {
        response = await fetch(url, {credentials: 'include', redirect: 'error', cache: 'no-store',
          signal: AbortSignal.timeout(20000)});
      } catch {
        throw Error('Torrentfilen kunne ikke hentes. Kontrollér dit '+trackerName+'-login og prøv igen.');
      }
      const base64 = await readTorrent(response, trackerName);
      const id = new URL(url).pathname.split('/').filter(Boolean).at(-1);
      // Keep metadata in session memory, not sync storage or the destination URL.
      item = {id: crypto.randomUUID(), kind, seedUrl, base64, name: `${trackerName}-${id}.torrent`, created: Date.now()};
    }
    await chrome.storage.session.set({pending: item});
    const tab = await openDestination(seedUrl);
    item.tabId = tab.id;
    await chrome.storage.session.set({pending: item});
    await status('Åbner FjordSeed. Log ind dér, hvis du bliver bedt om det.');
    await deliver(tab.id);
  } finally { working = false; }
}

async function deliver(tabId) {
  if (delivering) return;
  delivering = true;
  try {
    const {pending} = await chrome.storage.session.get('pending');
    if (!pending || pending.tabId !== tabId) return;
    if (Date.now() - pending.created >= MAX_AGE) {
      await chrome.storage.session.remove('pending');
      await status('Overførslen udløb efter 15 minutter. Send linket igen.', true);
      return;
    }
    const tab = await chrome.tabs.get(tabId);
    if (tab.status !== 'complete') return;
    const target = new URL(tab.url);
    if (target.origin !== new URL(pending.seedUrl).origin) return;
    const rss = pending.kind === 'rss';
    const origin = new URL(pending.seedUrl).origin;
    const result = await chrome.scripting.executeScript({target: {tabId}, func: rss ? showRss : showTorrent,
      args: rss ? [pending.url, pending.id, origin] : [pending.base64, pending.name, pending.id, origin]});
    const outcome = result[0]?.result;
    if (outcome === 'delivered') {
      await chrome.storage.session.remove('pending');
      await status(rss ? 'RSS-linket er klar i FjordSeed. Vælg navn og indstillinger, og tryk Gem feed.' : 'Klar i FjordSeed. Vælg indstillinger og tryk Start download.');
    } else {
      const messages = {
        login: 'Log ind i FjordSeed-fanen. Linket venter, indtil du er logget ind.',
        busy: 'Luk den åbne dialog i FjordSeed, og tryk Fortsæt her.',
        offline: 'FjordSeed er ikke klar. Kontrollér VPN-forbindelsen, og tryk Fortsæt her.',
        incompatible: 'FjordSeeds dialog kunne ikke åbnes. Opdatér FjordSeed og prøv igen.'
      };
      await status(messages[outcome] || 'Overførslen kunne ikke åbnes i FjordSeed.', true);
    }
  } finally { delivering = false; }
}

async function retry() {
  const {pending} = await chrome.storage.session.get('pending');
  if (!pending) throw Error('Der er intet ventende link.');
  const tab = await openDestination(pending.seedUrl, pending.tabId);
  pending.tabId = tab.id;
  await chrome.storage.session.set({pending});
  await deliver(tab.id);
}

chrome.contextMenus.onClicked.addListener(info => {
  if (info.menuItemId === MENU) begin(info.linkUrl).catch(e => status(e.message, true));
  if (info.menuItemId === PACKAGE_MENU) packageDelivery.enqueue(info.linkUrl).catch(e=>status(e.message,true));
});
chrome.tabs.onUpdated.addListener((id, change) => {
  if (change.status === 'complete') deliver(id).catch(() => status('Åbn udvidelsen og tryk Fortsæt for at prøve igen.', true));
  if (change.status === 'complete') packageDelivery.process().catch(()=>status('Pakken venter. Prøv igen fra udvidelsen.',true));
});
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('popup.html')) return;
  const run = async () => {
    if (message.type === 'package-open') await packageDelivery.open();
    else if (message.type === 'package-retry') await packageDelivery.retry();
    else if (message.type === 'package-clear') await packageDelivery.clear();
    else if (message.type === 'retry') await retry();
    else if (message.type === 'clear') {
      if (working || delivering) throw Error('Vent, til overførslen er færdig.');
      await chrome.storage.session.remove('pending');
      await status('Ventende link ryddet. Ingen download er startet.');
    } else throw Error('Ukendt handling.');
  };
  run().then(() => reply({ok: true})).catch(async e => {await status(e.message, true); reply({error: e.message});});
  return true;
});
