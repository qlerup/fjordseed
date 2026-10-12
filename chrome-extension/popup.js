import {seedAddress, permissionOrigin} from './common.mjs';
const $ = selector => document.querySelector(selector);
const {seedUrl} = await chrome.storage.local.get('seedUrl');
$('#address').value = seedUrl || '';
async function refresh() {
  const {status, pending} = await chrome.storage.session.get(['status', 'pending']);
  $('#status').textContent = status || 'Klar til dit første link.';
  $('#pending').hidden = !pending;
}
await refresh();
chrome.storage.onChanged.addListener((_, area) => {if (area === 'session') refresh();});
$('#settings').onsubmit = async event => {
  event.preventDefault();
  $('#save').disabled = true;
  try {
    const address = seedAddress($('#address').value);
    const granted = await chrome.permissions.request({origins: [permissionOrigin(address)]});
    if (!granted) throw Error('Giv adgang til FjordSeed for at kunne åbne torrentdialogen.');
    await chrome.storage.local.set({seedUrl: address});
    $('#address').value = address;
    $('#status').textContent = 'Adressen er gemt. Højreklik nu på et NordicBytes-downloadlink.';
  } catch (e) { $('#status').textContent = e.message; }
  finally { $('#save').disabled = false; }
};
for (const type of ['retry', 'clear']) $(`#${type}`).onclick = async () => {
  $(`#${type}`).disabled = true;
  try {
    const result = await chrome.runtime.sendMessage({type});
    if (result?.error) throw Error(result.error);
    await refresh();
  } catch (e) { $('#status').textContent = e.message; }
  finally { $(`#${type}`).disabled = false; }
};
