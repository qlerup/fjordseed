"""Real Chromium extension: background draft delivery without starting torrents."""
import base64, json, logging, shutil, sys, tempfile, threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
from manual_package import ManualPackage

logging.getLogger('werkzeug').setLevel(logging.ERROR)
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
 work=Path(folder);app=create_app(work/'data',testing=True,runtime_factory=FakeRuntime)
 app.extensions['state'].save('test-vpn',True)
 attempts=[]
 def rpc(action,data):
  attempts.append(data)
  if b'fixture43' in base64.b64decode(data.get('torrent','')) and sum(b'fixture43' in base64.b64decode(d.get('torrent','')) for d in attempts)==1:
   raise ValueError('Midlertidig fejl')
  return {'ok':True}
 app.extensions['runtime'].rpc.side_effect=rpc
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 address=f'http://127.0.0.1:{server.server_port}/'
 extension=work/'extension';shutil.copytree(root/'chrome-extension',extension)
 manifest=json.loads((extension/'manifest.json').read_text(encoding='utf-8'))
 manifest['host_permissions'].append('http://127.0.0.1/*');(extension/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
 background=extension/'background.js'
 background.write_text('''self.fixtureMenus=[];
const originalCreate=chrome.contextMenus.create.bind(chrome.contextMenus);
chrome.contextMenus.create=options=>{self.fixtureMenus.push(options);return originalCreate(options);};
const originalListen=chrome.contextMenus.onClicked.addListener.bind(chrome.contextMenus.onClicked);
chrome.contextMenus.onClicked.addListener=handler=>{self.fixtureClick=handler;originalListen(handler);};
'''+background.read_text(encoding='utf-8')+'\nself.fixturePackage=packageDelivery;\n',encoding='utf-8')
 try:
  with sync_playwright() as p:
   context=p.chromium.launch_persistent_context(str(work/'chrome'),channel='chromium',headless=True,
    args=[f'--disable-extensions-except={extension}',f'--load-extension={extension}'])
   context.route('**/*',lambda route:route.continue_() if route.request.url.startswith((address,'chrome-extension://')) else route.abort())
   context.route('**/api/streaming',lambda route:route.fulfill(json={'conversion_enabled':False}))
   worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
   worker.evaluate('url=>chrome.storage.local.set({seedUrl:url})',address)
   worker.evaluate(r'''() => {
    self.fetches=[];
    self.fetch=async(url,options)=>{
     const parsed=new URL(url),id=parsed.pathname.split('/').at(-1);
     if(!/^https:\/\/(nordicbytes|sagmire)\.org\/torrents\/download\/\d+/.test(url))throw Error('Unexpected external request');
     if(options.credentials!=='include'||options.redirect!=='error')throw Error('Unsafe request');
     self.fetches.push(url);
     const name='fixture'+id;
     return new Response('d4:infod6:lengthi1e4:name'+name.length+':'+name+'12:piece lengthi16384e6:pieces20:aaaaaaaaaaaaaaaaaaaaee',{headers:{'Content-Type':'application/x-bittorrent'}});
    };
   }''')
   page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(address);page.locator('[name=username]').fill('admin')
   page.locator('[name=password]').fill((work/'data'/'initial-login.txt').read_text().strip());page.get_by_role('button',name='Log ind',exact=True).click()
   page.locator('a[href="#torrents"]').click();page.locator('#new-torrent').click();page.locator('#method-magnet').click()
   page.locator('#magnet').fill('magnet:?xt=urn:btih:'+'a'*40)
   source_id=worker.evaluate("async()=>{const tab=await chrome.tabs.create({url:'about:blank',active:true});return tab.id;}")
   menus=worker.evaluate('self.fixtureMenus')
   assert len(menus)==2
   package_menu=next(m for m in menus if m['id']=='package-fjordseed')
   assert all('/torrents/download/' in pattern and 'rss' not in pattern for pattern in package_menu['targetUrlPatterns'])
   worker.evaluate('''() => {for(const id of [42,43,44])self.fixtureClick({menuItemId:'package-fjordseed',linkUrl:'https://nordicbytes.org/torrents/download/'+id+'?key=fixture-private'});}''')
   expect(page.locator('#manual-package-count')).to_contain_text('3 torrents',timeout=20000)
   assert worker.evaluate('async()=> (await chrome.tabs.query({active:true,currentWindow:true}))[0].id')==source_id
   expect(page.locator('#add-dialog')).to_be_visible();expect(page.locator('#magnet')).to_have_value('magnet:?xt=urn:btih:'+'a'*40)
   app.extensions['runtime'].rpc.assert_not_called()
   await_error=worker.evaluate("async()=>{try{await self.fixturePackage.enqueue('https://nordicbytes.org/rss/42?key=fixture')}catch(e){return e.message}}")
   assert await_error and len(worker.evaluate('self.fetches'))==3
   worker.evaluate("()=>self.fixturePackage.enqueue('https://nordicbytes.org/torrents/download/42')")
   assert ManualPackage(app.extensions['state']).public('local')['count']==3
   assert worker.evaluate('async()=> (await chrome.storage.session.get("packagePending")).packagePending.length')==0
   assert 'fixture-private' not in json.dumps(worker.evaluate('()=>chrome.tabs.query({})'))
   page.locator('#add-dialog .dialog-heading .close').first.click();page.reload()
   expect(page.locator('#manual-package-banner')).to_be_visible()
   page.bring_to_front();page.locator('#manual-package-open').click()
   expect(page.locator('.torrent-batch-item')).to_have_count(3)
   page.locator('#ratio-action').select_option('delete_time');page.locator('#ratio-seed-minutes').fill('60')
   for width in (1440,390):
    page.set_viewport_size({'width':width,'height':1000});assert page.locator('#ratio-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
    page.screenshot(path=str(root/f'test-results/extension-package-{width}.png'))
   page.locator('#ratio-save').click();expect(page.locator('#ratio-error')).to_contain_text('2 torrents er tilføjet')
   assert ManualPackage(app.extensions['state']).public('local')['count']==1
   page.locator('#ratio-save').click();expect(page.locator('#ratio-dialog')).not_to_be_visible()
   assert len(attempts)==4 and all(d['seed_minutes']==60 for d in attempts)
   assert ManualPackage(app.extensions['state']).public('local')['count']==0
   # Login interruption keeps the extension's pending file until authenticated delivery.
   page.close();context.pages[0].wait_for_timeout(500);context.clear_cookies()
   fetch_count=len(worker.evaluate('self.fetches'))
   worker.evaluate('id=>chrome.tabs.update(id,{active:true})',source_id)
   worker.evaluate("()=>self.fixturePackage.enqueue('https://sagmire.org/torrents/download/45')")
   assert worker.evaluate('async()=> (await chrome.storage.session.get("packagePending")).packagePending.length')==1
   for _ in range(100):
    matching=[p for p in context.pages if p.url.startswith(address)]
    if matching:break
    context.pages[0].wait_for_timeout(100)
   page=matching[0]
   expect(page.locator('[name=username]')).to_be_visible()
   assert worker.evaluate('async()=> (await chrome.tabs.query({active:true,currentWindow:true}))[0].url').startswith(address)
   assert len(worker.evaluate('self.fetches'))==fetch_count
   assert len(attempts)==4
   page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((work/'data'/'initial-login.txt').read_text().strip())
   page.get_by_role('button',name='Log ind',exact=True).click()
   expect(page.locator('#manual-package-count')).to_contain_text('1 torrent ligger klar',timeout=20000)
   assert len(attempts)==4
   page.locator('#manual-package-clear').click();expect(page.locator('#manual-package-banner')).to_be_hidden()
   assert len(attempts)==4
   assert not errors,errors
   context.close()
 finally:server.shutdown()
print('PASS real extension menus, rapid background delivery/no focus/no start, per-item package settings, retries, deduplication, RSS rejection and login recovery')
