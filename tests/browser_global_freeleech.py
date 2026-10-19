"""Check global freeleech preview badges and expiry on mobile and desktop."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]
source=(root/'static/app.js').read_text(encoding='utf-8')
code=source[source.index('function node('):source.index('function toast(')]
code+=source[source.index('function benefitView('):source.index('function renderRatioPreview(')]

with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in (390,1100):
        page=browser.new_page(viewport={'width':width,'height':650})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content('<meta charset="utf-8"><div class="card" id="preview-benefits"></div>')
        page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'))
        page.add_script_tag(content=code)
        page.evaluate("""() => document.querySelector('#preview-benefits').append(benefitView({
            status:'matched',matches:[{tracker_name:'NordicBytes',freeleech:100,
            double_upload:false,global_freeleech:true,
            global_freeleech_ends_at:'2026-10-19T18:40:22Z'}]}))""")
        target=page.locator('#preview-benefits')
        expect(target).to_contain_text('100 % Freeleech')
        expect(target).to_contain_text('Global freeleech')
        expect(target).to_contain_text('Gælder indtil')
        assert 'Dobbelt upload' not in target.inner_text()
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        assert not errors,errors
        page.evaluate("""() => document.querySelector('#preview-benefits').replaceChildren(
            benefitView({status:'matched',matches:[{tracker_name:'NordicBytes',freeleech:0,
            double_upload:false,global_freeleech:false}]}))""")
        assert 'Global freeleech' not in target.inner_text()
        print('PASS global freeleech badge and expiry, width',width)
        page.close()
    browser.close()
