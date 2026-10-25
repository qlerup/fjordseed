"""Animated backdrop remains decorative, bounded and respectful of motion settings."""
from pathlib import Path
import sys, tempfile, threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

root=Path(__file__).resolve().parents[1]
(root/'test-results').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder, testing=True, runtime_factory=FakeRuntime)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            scene=page.locator('.ambient-scene')
            expect(scene).to_have_attribute('aria-hidden','true')
            assert scene.evaluate('e=>getComputedStyle(e).pointerEvents')=='none'
            assert page.locator('.ambient-glow').first.evaluate('e=>getComputedStyle(e).animationName')=='ambient-tide'
            initial=page.locator('.ambient-glow').first.evaluate('e=>getComputedStyle(e).transform')
            page.wait_for_function('(initial)=>getComputedStyle(document.querySelector(".ambient-glow")).transform!==initial',arg=initial)
            for width in (1440,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert scene.bounding_box()['width']==width
                if width!=320:
                    page.screenshot(path=str(root/'test-results'/f'ambient-{width}.png'))
            page.locator('.nav[href="#torrents"]').click();page.locator('[data-download-filter=rss]').click()
            page.locator('#downloads-manage-feeds').click()
            expect(page.locator('#rss-feeds-dialog')).to_be_visible()
            assert page.locator('.ambient-glow').first.evaluate('e=>getComputedStyle(e).animationPlayState')=='paused'
            page.locator('#rss-feeds-dialog').get_by_role('button',name='Luk',exact=True).click()
            assert page.locator('.ambient-glow').first.evaluate('e=>getComputedStyle(e).animationPlayState')=='running'
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('.ambient-glow').first.evaluate('e=>getComputedStyle(e).animationName')=='none'
            expect(page.locator('.ambient-particles')).to_be_hidden()
            page.emulate_media(reduced_motion='no-preference')
            assert page.locator('.ambient-glow').first.evaluate('e=>getComputedStyle(e).animationName')=='ambient-tide'
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS ambient animation, modal pause, reduced motion, responsive layout and navigation')
