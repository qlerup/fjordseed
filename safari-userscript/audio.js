// Read tracker metadata only. No media file or torrent payload is downloaded.
function fjordSeedAudioTracks(doc) {
  const clean = value => (value || '').replace(/\s+/g, ' ').trim().slice(0, 500);
  // UNIT3D's desktop MediaInfo summary contains one dd per audio stream.
  const summary = [...doc.querySelectorAll('.mediainfo__audio dd')]
    .map(node => clean(node.textContent)).filter(Boolean);
  // Prefer the raw dump: desktop summaries may replace the technical codec
  // (E-AC-3 JOC, MLP FBA, DTS XLL) with its commercial name.
  for (const node of doc.querySelectorAll('[x-ref="mediainfo"], .torrent-mediainfo-dump, pre')) {
    const raw = node.textContent || '';
    if (raw.length > 256 * 1024) continue;
    const tracks = [];
    let audio = null;
    for (const line of raw.split(/\r?\n/)) {
      if (/^(?:General|Video|Audio|Text|Menu|Image)(?:\s*#\d+)?\s*$/i.test(line.trim())) {
        if (audio) tracks.push(audio);
        audio = /^Audio\b/i.test(line.trim()) ? {} : null;
        continue;
      }
      if (!audio) continue;
      const match = line.match(/^\s*(Language|Format|Commercial name|Format\/Commercial(?: name)?|Channel\(s\)|Bit rate|Title)\s*:\s*(.*?)\s*$/i);
      if (match) audio[match[1].toLowerCase()] = clean(match[2]);
    }
    if (audio) tracks.push(audio);
    const labels = tracks.filter(track => track.format || track.language).slice(0, 64).map(track => {
      const commercial = track['commercial name'] || track['format/commercial name'] || track['format/commercial'];
      const format = track.format && commercial && track.format.toLowerCase() !== commercial.toLowerCase()
        ? `${track.format} (${commercial})` : track.format || commercial;
      return [track.language || 'Sprog ikke oplyst', format || 'Format ikke oplyst',
        track['channel(s)'], track['bit rate'], track.title].filter(Boolean).join(' / ');
    });
    if (labels.length) return labels;
  }
  return summary.slice(0, 64);
}

let fjordSeedDesktopAudioQueue = Promise.resolve();

async function loadFjordSeedAudio(downloadUrl) {
  const source = new URL(downloadUrl);
  const match = source.pathname.match(/^\/torrents\/download\/([1-9]\d*)\/?$/);
  if (!match || source.origin !== location.origin || source.username || source.password ||
      !['https://nordicbytes.org', 'https://sagmire.org'].includes(source.origin)) {
    throw Error('Vælg en torrent på denne tracker.');
  }
  const path = '/torrents/' + match[1];
  if (location.pathname.replace(/\/$/, '') === path) {
    const existing = fjordSeedAudioTracks(document);
    if (existing.length) return existing;
  }
  async function readPage(query = '', restorePreference = false) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(source.origin + path + query, {
        credentials: 'same-origin', redirect: 'error', signal: controller.signal,
        headers: {Accept: 'text/html'}
      });
      if (!response.ok || !response.headers.get('Content-Type')?.includes('text/html')) {
        throw Error('Detaljesiden kunne ikke læses. Kontrollér, at du er logget ind på trackeren.');
      }
      if (response.url) {
        const final = new URL(response.url);
        if (final.origin !== source.origin || final.pathname.replace(/\/$/, '') !== path) {
          throw Error('Log ind på trackeren, og prøv igen.');
        }
      }
      if (restorePreference) {
        await response.body?.cancel();
        return [];
      }
      // Bound the response while streaming, including chunked responses.
      const reader = response.body.getReader(), chunks = [];
      let size = 0;
      try {
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > 2 * 1024 * 1024) {
            await reader.cancel();
            throw Error('Detaljesiden er for stor til at indlæse.');
          }
          chunks.push(value);
        }
      } finally { reader.releaseLock(); }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      const doc = new DOMParser().parseFromString(new TextDecoder().decode(bytes), 'text/html');
      if (doc.querySelector('input[type="password"], meta[http-equiv="refresh" i]')) {
        throw Error('Log ind på trackeren, og prøv igen.');
      }
      return fjordSeedAudioTracks(doc);
    } catch (error) {
      if (controller.signal.aborted) throw Error('Detaljesiden svarede ikke. Prøv igen.');
      if (error instanceof TypeError) throw Error('Detaljesiden kunne ikke hentes. Kontrollér tracker-login og Userscripts-adgang.');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  const tracks = await readPage();
  if (tracks.length || source.origin !== 'https://nordicbytes.org' ||
      !/iPhone|iPad|Android/i.test(navigator.userAgent) ||
      new URL(location.href).searchParams.get('desktop') === '1') return tracks;

  // NordicBytes' view switch is persistent: desktop=1 sets force_desktop and
  // clears force_mobile. Restore mobile=1 even when loading/parsing fails.
  // Serialize these switches so concurrent cards cannot overwrite each other.
  const loadDesktop = async () => {
    try {
      return await readPage('?desktop=1');
    } finally {
      try { await readPage('?mobile=1', true); }
      catch { throw Error('Mobilvisningen kunne ikke gendannes. Åbn NordicBytes med ?mobile=1, og prøv igen.'); }
    }
  };
  const request = fjordSeedDesktopAudioQueue.then(loadDesktop, loadDesktop);
  fjordSeedDesktopAudioQueue = request.then(() => undefined, () => undefined);
  return request;
}
