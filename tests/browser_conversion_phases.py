"""Real browser phase transitions without encoding or touching a live server."""
from pathlib import Path,PurePosixPath
import sys,tempfile,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


class Demo(FakeRuntime):
    host_downloads=PurePosixPath('/mnt/media')


device=dict(id='pc',name='Test-pc',online=True,gpu_ready=True,media_folder='Z:/media',
            files_updated_at=time.time(),conversion_version=1,files=[],skip_rules=[],queue=[])
data=dict(devices=[device],conversion_bitrate=30,conversion_enabled=False,
          conversion_target='server',conversion_configured=True)
phases=[('encoding','encoding',72,'Konverterer'),('metadata','metadata',None,'Bevarer HDR'),
        ('verifying','verifying',None,'Kontrollerer den færdige fil'),
        ('moving','moving',15,'Originaltorrenten flyttes'),
        ('moving','source_verifying',64,'Kontrollerer originalen'),
        ('moving','publishing',None,'Lægger filmen'),('completed','completed',100,'Færdig')]
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
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator('[name=username]').fill('admin')
                page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
                page.get_by_role('button',name='Log ind',exact=True).click()
                page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
                for state,stage,percent,label in phases:
                    device['selection']=dict(action='convert',state=state,stage=stage,name='Movie/film.mkv',
                        detail='Aktuelt trin: '+stage,progress=99,phase_progress=percent,stage_started_at=time.time()-64)
                    page.evaluate('workspacePoll()')
                    expect(page.locator('.workspace-job-state')).to_contain_text(label)
                    bar=page.locator('.workspace-job progress')
                    if percent is None:
                        expect(bar).not_to_have_attribute('value')
                        expect(bar).to_have_class('workspace-job-progress is-indeterminate')
                        expect(page.locator('.workspace-phase-time')).to_contain_text('Tid på dette trin')
                    else:expect(bar).to_have_attribute('value',str(percent))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if stage=='metadata':
                        Path('test-results').mkdir(exist_ok=True)
                        page.locator('.workspace-job').screenshot(path=f'test-results/conversion-phase-{width}.png')
                assert not errors,errors
                page.close()
            browser.close()
    finally:server.shutdown()
print('PASS phase resets, measured/animated progress and elapsed time at desktop/mobile sizes')
