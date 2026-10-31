import {seedAddress, permissionOrigin} from './common.mjs';
const $ = selector => document.querySelector(selector);
const {seedUrl} = await chrome.storage.local.get('seedUrl');
$('#address').value = seedUrl || '';
async function refresh() {
  const {status, pending, packagePending=[], packageStored} = await chrome.storage.session.get(['status', 'pending','packagePending','packageStored']);
  $('#status').textContent = status || 'Klar til dit første link.';
  $('#pending').hidden = !pending;
  $('#package-pending').hidden=!packagePending.length;
  $('#package-status').textContent=`${packagePending.length} links venter på overførsel.`+(packageStored?` Senest gemt: ${packageStored.count} torrents i FjordSeed.`:'');
  const errors=packagePending.filter(item=>item.error);
  $('#package-errors').hidden=!errors.length;
  $('#package-errors').replaceChildren(...errors.slice(0,5).map(item=>{const li=document.createElement('li');li.textContent=(item.name||'Torrentlink')+': '+item.error;return li;}));
}
await refresh();
chrome.storage.onChanged.addListener((_, area) => {if (area === 'session') refresh();});
$('#settings').onsubmit = async event => {
  event.preventDefault();
  $('#save').disabled = true;
  try {
    const address = seedAddress($('#address').value);
    const granted = await chrome.permissions.request({origins: [permissionOrigin(address)]});
    if (!granted) throw Error('Giv adgang til FjordSeed for at kunne åbne dialogerne.');
    await chrome.storage.local.set({seedUrl: address});
    $('#address').value = address;
    $('#status').textContent = 'Adressen er gemt. Højreklik nu på et NordicBytes eller Sagmire-downloadlink eller RSS-feed.';
  } catch (e) { $('#status').textContent = e.message; }
  finally { $('#save').disabled = false; }
};
for (const type of ['retry', 'clear','package-open','package-retry','package-clear']) $(`#${type}`).onclick = async () => {
  $(`#${type}`).disabled = true;
  try {
    const result = await chrome.runtime.sendMessage({type});
    if (result?.error) throw Error(result.error);
    await refresh();
  } catch (e) { $('#status').textContent = e.message; }
  finally { $(`#${type}`).disabled = false; }
};
