"""PC workspace selection, grouping, search and polling without real media jobs."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in (390,1440):
        page=browser.new_page(viewport={'width':width,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        markup=(root/'templates/conversion_settings.html').read_text(encoding='utf-8').replace('id="conversion-view" hidden','id="conversion-view"')
        page.set_content(markup)
        page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'))
        page.add_style_tag(content=(root/'static/library-conversion.css').read_text(encoding='utf-8'))
        page.evaluate("""() => {
          location.hash='#conversion';
          window.$=s=>document.querySelector(s);
          window.node=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
          window.data={devices:[{id:'pc',name:'PC',online:true}],conversion_target:'pc'};
          window.api=async()=>data;
          window.setInterval=cb=>{window.poll=cb;};
        }""")
        page.add_script_tag(content=(root/'static/conversion-settings.js').read_text(encoding='utf-8'))
        expect(page.locator('#conversion-devices')).to_contain_text('Afventer valgt lokaltion i programmet')
        expect(page.locator('.workspace-search')).to_have_count(0)
        page.evaluate("""() => {
          Object.assign(data.devices[0],{media_folder:'M:\\\\Bibliotek',files_updated_at:1700000000,
            files:[{name:'Show/Season 1/E01.mkv',size:123},{name:'Show/Season 1/E02.mkv',size:456},{name:'Film.mkv',size:789}]});poll();
        }""")
        expect(page.locator('.workspace-folder>summary').first).to_have_text('Show')
        page.locator('.workspace-folder>summary').first.click()
        page.locator('.workspace-folder>summary').nth(1).click()
        expect(page.get_by_text('E01.mkv',exact=True)).to_be_visible()
        page.locator('.workspace-search').fill('E02')
        expect(page.get_by_text('E02.mkv',exact=True)).to_be_visible()
        expect(page.get_by_text('E01.mkv',exact=True)).to_have_count(0)
        page.evaluate('poll()')
        expect(page.locator('.workspace-search')).to_have_value('E02')
        expect(page.locator('.workspace-search')).to_be_focused()
        page.evaluate("() => {data.devices[0].media_folder='';poll();}")
        expect(page.locator('.workspace-files')).to_have_count(0)
        expect(page.locator('#conversion-devices')).to_contain_text('Afventer valgt lokaltion i programmet')
        assert not errors,errors
        page.close()
    browser.close()
print('Workspace UI: waiting, grouping, search and polling passed at mobile and desktop sizes')
