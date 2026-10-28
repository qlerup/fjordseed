"""The cleanup list remains readable on mobile and stable while polling."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]
markup=(root/'templates/storage_usage.html').read_text(encoding='utf-8')
script=(root/'static/storage-usage.js').read_text(encoding='utf-8')
gib=1024**3
# Midnight on 29 October in Copenhagen. Span requires six-hour windows.
base=1793228400
points=[dict(at=base+hour*3600,bytes=gib) for hour in (0,1,2,3,4,5,18,18,18,18,18,18)]
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in (390,1440):
        page=browser.new_page(viewport={'width':width,'height':1000},timezone_id='Europe/Copenhagen')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content('<main>'+markup+'</main>')
        page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'))
        page.evaluate("""data=>{
            location.hash='#storage';window.payload=data;
            window.api=url=>Promise.resolve(url.endsWith('temporary-usage')?payload:{path:'/mnt/media',total_bytes:2000*1024**3,used_bytes:1500*1024**3,free_bytes:500*1024**3});
            window.setInterval=callback=>{window.poll=callback;};
        }""",dict(path='/mnt/media',current_rss_bytes=9*gib,release_schedule=dict(items=[],count=12,scheduled_bytes=12*gib,available=True,timeline=points,soon_bytes=0,unplaced_bytes=2*gib)))
        page.add_script_tag(content=script)
        expect(page.locator('.storage-release-list li')).to_have_count(3)
        expect(page.locator('.storage-release-amount').first).to_have_text('Ca. 6,00 GiB frigives')
        expect(page.locator('.storage-release-name').first).to_have_text('29. okt. kl. 00\u201306')
        expect(page.locator('.storage-release-name').nth(1)).to_have_text('29. okt. kl. 18\u201324')
        expect(page.locator('.storage-release-amount').nth(1)).to_have_text('Ca. 6,00 GiB frigives')
        expect(page.locator('.storage-release-name').last).to_have_text('Tidspunkt afventer')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.evaluate("""()=>{window.changes=[];new MutationObserver(rows=>changes.push(...rows)).observe(document.querySelector('main'),{subtree:true,childList:true,attributes:true,characterData:true});poll();}""")
        page.wait_for_timeout(100)
        assert page.evaluate('changes.length')==0
        Path('test-results').mkdir(exist_ok=True)
        page.screenshot(path=f'test-results/storage-release-{width}.png')
        page.evaluate('payload.release_schedule={items:[],count:0,scheduled_bytes:0,available:true};poll()')
        expect(page.locator('[data-usage-release-summary]')).to_contain_text('Ingen midlertidige RSS-filer')
        expect(page.locator('.storage-release-list li')).to_have_count(0)
        assert not errors
        page.close()
    browser.close()
print('PASS desktop/mobile cleanup list, local dates, amounts, empty state, all-download aggregation and stable polling')
