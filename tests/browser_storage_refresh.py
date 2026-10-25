"""Background storage polling preserves layout, text selection and existing values."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]
markup=(root/'templates/storage_usage.html').read_text(encoding='utf-8')
script=(root/'static/storage-usage.js').read_text(encoding='utf-8')
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in (390,1440):
        page=browser.new_page(viewport={'width':width,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.set_content('<main>'+markup+markup+'</main>')
        page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'))
        page.evaluate("""() => {
            location.hash='#streaming';
            window.pending=[];
            window.api=url=>url.endsWith('temporary-usage')?Promise.resolve({path:'/mnt/media',current_rss_bytes:100}):new Promise((resolve,reject)=>pending.push({resolve,reject}));
            window.size=n=>String(n)+' B';
            window.setInterval=callback=>{window.poll=callback;};
        }""")
        page.add_script_tag(content=script)
        card=page.locator('[data-storage-usage]').first
        expect(card.locator('[data-usage-status]')).to_be_visible()
        data={'path':'/mnt/media','total_bytes':1000,'used_bytes':750,'free_bytes':250}
        page.evaluate('data=>pending.shift().resolve(data)',data)
        expect(card.locator('[data-usage-percent]')).to_have_text('75 % brugt')
        page.evaluate("""() => {
            window.mutations=[];
            window.observer=new MutationObserver(rows=>mutations.push(...rows));
            observer.observe(document.querySelector('main'),{subtree:true,childList:true,attributes:true,characterData:true});
            const selection=getSelection(),range=document.createRange();
            range.selectNodeContents(document.querySelector('[data-usage-used]'));
            selection.removeAllRanges();selection.addRange(range);
            poll();
        }""")
        before=card.bounding_box()
        expect(card.locator('[data-usage-details]')).to_be_visible()
        expect(card.locator('[data-usage-status]')).not_to_be_visible()
        assert page.evaluate('getSelection().toString()')=='750 B'
        page.evaluate('data=>pending.shift().resolve(data)',data)
        assert page.evaluate('mutations.length')==0
        assert card.bounding_box()==before
        assert page.evaluate('getSelection().toString()')=='750 B'
        page.evaluate('poll()')
        page.evaluate('data=>pending.shift().resolve(data)',{**data,'used_bytes':800,'free_bytes':200})
        expect(card.locator('[data-usage-percent]')).to_have_text('80 % brugt')
        expect(page.locator('[data-usage-free]').last).to_have_text('200 B')
        assert card.bounding_box()==before
        page.evaluate('poll();pending.shift().reject(new Error("offline"))')
        expect(card.locator('[data-usage-status]')).to_contain_text('Viser senest hentede tal')
        expect(card.locator('[data-usage-details]')).to_be_visible()
        expect(card.locator('[data-usage-used]')).to_have_text('800 B')
        page.evaluate('poll()')
        page.evaluate('data=>pending.shift().resolve(data)',data)
        expect(card.locator('[data-usage-status]')).not_to_be_visible()
        assert card.bounding_box()==before
        page.evaluate('poll()')
        page.evaluate('data=>pending.shift().resolve(data)',{
            'path':'/mnt/media','total_bytes':1967846068224,
            'used_bytes':736002654208,'free_bytes':1131806744576})
        expect(card.locator('[data-usage-used]')).to_have_text('685,46 GiB')
        expect(card.locator('[data-usage-free]')).to_have_text('1.054,08 GiB')
        expect(card.locator('[data-usage-total]')).to_have_text('1.832,70 GiB')
        expect(card.locator('[data-usage-reserved-note]')).to_contain_text('93,17 GiB')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.evaluate("dispatchEvent(new Event('storage-changed'))")
        expect(card.locator('[data-usage-details]')).not_to_be_visible()
        page.evaluate('pending.shift().reject(new Error("offline"))')
        expect(card.locator('[data-usage-status]')).to_contain_text('Lagerplads kunne ikke hentes')
        assert not errors,errors
        page.close()
    browser.close()
print('PASS quiet polling, unchanged DOM and selection, updated values, failure/recovery and location changes')
