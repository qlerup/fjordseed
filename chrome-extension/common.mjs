export const MAX_BYTES = 4 * 1024 * 1024;
export const MAX_AGE = 15 * 60 * 1000;
export const TRACKER_ORIGINS = {'https://nordicbytes.org':'NordicBytes', 'https://sagmire.org':'Sagmire'};

export function rssLink(value) {
  const url = new URL(value);
  if (!Object.hasOwn(TRACKER_ORIGINS, url.origin) || url.username || url.password ||
      url.href.length > 4096 || !/^\/(?:torrents\/)?rss(?:\.(?:xml|php))?(?:\/|$)/i.test(url.pathname) ||
      /\/(?:create|edit|delete|manage)(?:\/|$)/i.test(url.pathname)) {
    throw Error('Vælg et RSS-feedlink fra NordicBytes eller Sagmire.');
  }
  url.hash = '';
  return url.href;
}

export function sourceLink(value) {
  try { return {kind: 'torrent', url: torrentLink(value)}; }
  catch { return {kind: 'rss', url: rssLink(value)}; }
}

export function torrentLink(value) {
  const url = new URL(value);
  if (!Object.hasOwn(TRACKER_ORIGINS, url.origin) || url.username || url.password ||
      !/^\/torrents\/download\/[1-9]\d*\/?$/.test(url.pathname)) {
    throw Error('Vælg et torrent-downloadlink fra NordicBytes eller Sagmire.');
  }
  url.hash = '';
  return url.href;
}

export function seedAddress(value) {
  const url = new URL(value.trim());
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.search || url.hash || url.pathname !== '/') {
    throw Error('Indtast FjordSeeds grundadresse, fx https://seed.example.dk eller http://192.168.1.110:8099.');
  }
  if (Object.hasOwn(TRACKER_ORIGINS, url.origin)) throw Error('Indtast adressen til FjordSeed.');
  return url.origin + '/';
}

export function permissionOrigin(address) {
  const url = new URL(address);
  return `${url.protocol}//${url.hostname}/*`;
}

export function selectSeedTab(tabs, address, preferredId) {
  const origin = new URL(address).origin;
  return tabs.filter(tab => {
    try {
      const url = new URL(tab.pendingUrl || tab.url);
      return url.origin === origin && ['/', '/login'].includes(url.pathname);
    } catch { return false; }
  }).sort((a, b) =>
    Number(b.id === preferredId) - Number(a.id === preferredId) ||
    Number(!!b.active) - Number(!!a.active) ||
    (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
}

export async function readTorrent(response, name = 'Trackeren') {
  if (!response.ok) throw Error(`${name} svarede med HTTP ${response.status}. Log ind på trackeren og prøv igen.`);
  if (/text\/html|application\/json/i.test(response.headers.get('content-type') || '')) {
    throw Error(`${name} sendte en side i stedet for en torrentfil. Log ind på trackeren og prøv igen.`);
  }
  if (Number(response.headers.get('content-length')) > MAX_BYTES) throw Error('Torrentfilen er større end 4 MiB.');
  if (!response.body) throw Error('Torrentfilen er tom.');
  const reader = response.body.getReader(), chunks = [];
  let length = 0;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      length += value.length;
      if (length > MAX_BYTES) throw Error('Torrentfilen er større end 4 MiB.');
      chunks.push(value);
    }
  } finally { await reader.cancel(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  // FjordSeed performs the full bencode validation during its normal preview.
  if (bytes[0] !== 100 || bytes.at(-1) !== 101) throw Error('Svaret er ikke en torrentfil.');
  let binary = '';
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(binary);
}

// Runs in the isolated extension world, in the configured FjordSeed tab only.
export function showRss(url, transferId, expectedOrigin) {
  if (location.origin !== expectedOrigin) return 'wrong-host';
  const form = document.querySelector('#rss-form'), add = document.querySelector('#rss-new');
  const input = document.querySelector('#rss-url'), dialog = document.querySelector('#rss-dialog');
  if (!form || !add || !input || !dialog) return 'login';
  if (form.dataset.fjordseedTransfer === transferId) return 'delivered';
  if (document.querySelector('dialog[open]')) return 'busy';
  location.hash = '#rss';
  add.click();
  if (!dialog.open) return 'incompatible';
  input.value = url;
  input.dispatchEvent(new Event('input', {bubbles: true}));
  input.dispatchEvent(new Event('change', {bubbles: true}));
  form.dataset.fjordseedTransfer = transferId;
  document.querySelector('#rss-name')?.focus();
  return 'delivered';
}

export async function showTorrent(base64, name, transferId, expectedOrigin) {
  if (location.origin !== expectedOrigin) return 'wrong-host';
  const form = document.querySelector('#add-form');
  const file = document.querySelector('#torrent-file');
  const add = document.querySelector('#new-torrent');
  const ratio = document.querySelector('#ratio-dialog');
  if (!form || !file || !add || !ratio) return 'login';
  if (form.dataset.fjordseedTransfer === transferId) return 'delivered';
  if (document.querySelector('dialog[open]')) return 'busy';
  // Initial status loading may briefly disable the button after navigation.
  for (let i = 0; add.disabled && i < 20; i++) await new Promise(resolve => setTimeout(resolve, 250));
  if (add.disabled) return 'offline';
  add.click();
  const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
  const data = new DataTransfer();
  data.items.add(new File([bytes], name, {type: 'application/x-bittorrent'}));
  file.files = data.files;
  form.requestSubmit();
  if (!ratio.open) return 'incompatible';
  form.dataset.fjordseedTransfer = transferId;
  return 'delivered';
}
