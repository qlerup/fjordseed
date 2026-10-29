from pathlib import Path
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser=p.chromium.launch(timeout=20000)
    for width in (390,1440):
        page=browser.new_page(viewport={'width':width,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content((root/'templates/conversion_settings.html').read_text().replace('id="conversion-view" hidden','id="conversion-view"'))
        for file in ('style.css','library-conversion.css'):page.add_style_tag(content=(root/'static'/file).read_text())
        page.evaluate('''() => {
          location.hash='#conversion';
          window.items=[{id:'a',name:'Serie/S01/E01.mkv',state:'available',detail:'HDR10 · Dolby Vision er gemt'},
                        {id:'b',name:'Film.mkv',state:'restored',detail:'Dolby Vision gendannet'}];
          window.api=async(url,options)=>{
            if(options){window.requested=url;items[0].state='queued';items[0].detail='Venter på gendannelse';return {};}
            return {items};
          };
        }''')
        page.add_script_tag(content=(root/'static/dolby-vision.js').read_text())
        expect(page.locator('#dolby-vision-status')).to_contain_text('2 af 2')
        page.locator('#dolby-vision-search').fill('E01')
        expect(page.locator('#dolby-vision-status')).to_contain_text('1 af 2')
        page.get_by_role('button',name='Gendan Dolby Vision',exact=True).click()
        expect(page.get_by_role('button',name='Arbejder …')).to_be_disabled()
        assert page.evaluate('requested')=='/api/conversion/dolby-vision/a/restore'
        page.evaluate("items[0].state='restored';items[0].detail='Gendannet og kontrolleret'")
        page.get_by_role('button',name='Opdater liste').click()
        expect(page.locator('#dolby-vision-list')).to_contain_text('Gendannet og kontrolleret')
        page.locator('#dolby-vision-search').fill('')
        expect(page.get_by_role('button',name='Gendannet',exact=True)).to_have_count(2)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        page.close()
    browser.close()
print('Dolby Vision list, search, restore and polling passed on mobile/desktop')
