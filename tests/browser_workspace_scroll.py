"""Background workspace and bitrate refreshes preserve scroll and open folders."""
from pathlib import Path,PurePosixPath
import sys,tempfile,threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


class Demo(FakeRuntime):
    host_downloads=PurePosixPath('/mnt/media')


files=[dict(name=f'A series/episode-{i:02}.mkv',size=1000000000) for i in range(20)]
files += [dict(name=f'Film-{i:02}/film.mkv',size=2000000000) for i in range(70)]
device=dict(id='pc',name='Test-pc',online=True,gpu_ready=True,media_folder='Z:/media',
            files_updated_at=1793226867,conversion_version=1,files=files,skip_rules=[])
data=dict(devices=[device],conversion_bitrate=30,conversion_enabled=False,
          conversion_target='server',conversion_configured=True)
rates=dict(media_folder='Z:/media',pending=False,files=[dict(**f,video_bps=7900000,total_bps=8500000,state='ready') for f in files])
with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=Demo)
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch()
   for width in (1440,390):
    page=browser.new_page(viewport={'width':width,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.add_init_script("""const interval=window.setInterval;window.setInterval=(fn,ms,...args)=>{if(ms===5000){window.workspacePoll=fn;return 0;}return interval(fn,ms,...args);};""")
    page.route('**/api/conversion',lambda route:route.fulfill(json=data))
    page.route('**/api/conversion/devices/pc/bitrates',lambda route:route.fulfill(json=rates))
    page.goto(f'http://127.0.0.1:{server.server_port}')
    page.locator('[name=username]').fill('admin')
    page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
    page.get_by_role('button',name='Log ind',exact=True).click()
    page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
    pane=page.locator('.workspace-files');series=page.locator('.workspace-folder').first
    expect(page.locator('.workspace-folder').nth(1)).to_contain_text('Videobitrate: 7,9 Mbps')
    expect(page.locator('.workspace-tools .workspace-skip')).to_have_count(0)
    expect(page.locator('.workspace-folder .workspace-skip').first).to_be_visible()
    series.locator('summary').click()
    expect(series.locator('.workspace-file').first).to_contain_text('Videobitrate: 7,9 Mbps')
    expect(series.locator('.workspace-file').first).to_contain_text('Samlet bitrate: 8,5 Mbps')
    assert 'kb/s' not in pane.inner_text()
    pane.scroll_into_view_if_needed()
    pane.evaluate('(el)=>el.scrollTop=370')
    before=page.evaluate('({top:document.querySelector(".workspace-files").scrollTop,page:scrollY})')
    # A real response change forces a rebuild; both nested and page scroll survive.
    device['files_updated_at']+=1
    page.evaluate('workspacePoll()')
    updated=page.evaluate('stamp=>new Date(stamp*1000).toLocaleString("da-DK")',device['files_updated_at'])
    expect(page.locator('.workspace-summary')).to_contain_text(updated)
    assert pane.evaluate('(el)=>el.scrollTop')==before['top']
    assert page.evaluate('scrollY')==before['page']
    assert series.evaluate('(el)=>el.open')
    # Identical responses leave the existing DOM in place.
    pane.evaluate('(el)=>window.originalPane=el')
    page.evaluate('workspacePoll()');page.wait_for_timeout(200)
    assert pane.evaluate('(el)=>el===window.originalPane')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    Path('test-results').mkdir(exist_ok=True)
    page.screenshot(path=f'test-results/workspace-scroll-{width}.png')
    assert not errors,errors
    page.close()
   browser.close()
 finally:server.shutdown()
print('PASS desktop/mobile scroll, open folders, stable DOM and per-file video/total bitrate in Mbps')
