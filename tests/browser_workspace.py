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
          window.data={devices:[{id:'pc',name:'PC',online:true,conversion_version:1}],conversion_target:'pc'};
          window.api=async(url,options)=>{
            if(url.endsWith('/bitrates'))return {media_folder:data.devices[0].media_folder,pending:false,files:(data.devices[0].files||[]).map(f=>({...f,state:'ready',video_bps:f.name.includes('E01')?65000000:30000000,total_bps:68000000}))};
            if(url.endsWith('/skip')){
              const rule=JSON.parse(options.body),d=data.devices[0];
              d.skip_rules=(d.skip_rules||[]).filter(r=>r.kind!==rule.kind||r.path!==rule.path);
              if(rule.skip)d.skip_rules.push({path:rule.path,kind:rule.kind,skip:true});
              return {media_folder:d.media_folder,skip_rules:d.skip_rules};
            }
            if(url.endsWith('/select')){
              window.sent=JSON.parse(options.body);
              data.devices[0].selection={...sent,id:'selection',state:'queued',action:'convert'};
              return {selection:data.devices[0].selection};
            }
            return data;
          };
          window.toast=()=>{};window.error=(s,e)=>{throw e;};
          window.setInterval=cb=>{window.poll=cb;};
        }""")
        page.add_script_tag(content=(root/'static/conversion-settings.js').read_text(encoding='utf-8'))
        expect(page.locator('#conversion-devices')).to_contain_text('Afventer valgt lokaltion i programmet')
        expect(page.locator('.workspace-search')).to_have_count(0)
        page.evaluate("""() => {
          Object.assign(data.devices[0],{media_folder:'M:\\\\Bibliotek',files_updated_at:1700000000,
            files:[{name:'Show/Season 1/E01.mkv',size:123,series_key:'show'},{name:'Show/Season 1/E02.mkv',size:456,series_key:'show'},{name:'Film.mkv',size:789},{name:'Done/Converted.mkv',size:10,converted:true,bitrate:30}]});poll();
        }""")
        expect(page.locator('.workspace-folder-name').first).to_contain_text('Show')
        expect(page.get_by_text('Converted.mkv',exact=True)).to_have_count(0)
        expect(page.locator('.workspace-summary')).to_contain_text('3 mangler · 1 konverterede skjult')
        expect(page.locator('.workspace-folder-name').first).to_contain_text('65 Mbps')
        page.locator('.workspace-folder-name').first.click()
        page.locator('.workspace-folder-name').nth(1).click()
        expect(page.get_by_text('E01.mkv',exact=True)).to_be_visible()
        page.locator('[data-skip-kind="file"][data-skip-path="Show/Season 1/E01.mkv"]').click()
        expect(page.get_by_text('E01.mkv',exact=True)).to_have_count(0)
        expect(page.locator('.workspace-summary')).to_contain_text('2 mangler')
        page.get_by_label('Vis sprunget over',exact=True).check()
        expect(page.get_by_text('E01.mkv',exact=True)).to_have_count(1)
        page.locator('[data-skip-kind="file"][data-skip-path="Show/Season 1/E01.mkv"]').click()
        page.get_by_label('Vis sprunget over',exact=True).uncheck()
        page.locator('[data-skip-kind="series"][data-skip-path="show"]').first.click()
        expect(page.locator('.workspace-folder')).to_have_count(0)
        expect(page.locator('.workspace-summary')).to_contain_text('1 mangler')
        page.get_by_label('Vis sprunget over',exact=True).check()
        page.locator('[data-skip-kind="series"][data-skip-path="show"]').first.click()
        page.get_by_label('Vis sprunget over',exact=True).uncheck()
        page.locator('[data-skip-kind="folder"][data-skip-path="Show"]').click()
        expect(page.get_by_text('E01.mkv',exact=True)).to_have_count(0)
        page.get_by_label('Vis sprunget over',exact=True).check()
        page.locator('[data-skip-kind="folder"][data-skip-path="Show"]').click()
        page.get_by_label('Vis sprunget over',exact=True).uncheck()
        page.locator('.workspace-search').fill('E02')
        expect(page.get_by_text('E02.mkv',exact=True)).to_be_visible()
        expect(page.get_by_text('E01.mkv',exact=True)).to_have_count(0)
        page.evaluate('poll()')
        expect(page.locator('.workspace-search')).to_have_value('E02')
        expect(page.locator('.workspace-search')).to_be_focused()
        page.get_by_role('button',name='Send til pc',exact=True).click()
        expect(page.get_by_role('button',name='Afventer pc…',exact=True)).to_be_disabled()
        assert page.evaluate('sent.name')=='Show/Season 1/E02.mkv'
        page.evaluate("() => {data.devices[0].selection.state='converting';poll();}")
        expect(page.get_by_role('button',name='Konvertering i gang',exact=True)).to_be_disabled()
        page.evaluate("() => {data.devices[0].selection.state='completed';poll();}")
        expect(page.get_by_text('E02.mkv',exact=True)).to_have_count(0)
        for mobile_width in (width,320):
            page.set_viewport_size({'width':mobile_width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.evaluate("() => {data.devices[0].media_folder='';poll();}")
        expect(page.locator('.workspace-files')).to_have_count(0)
        expect(page.locator('#conversion-devices')).to_contain_text('Afventer valgt lokaltion i programmet')
        assert not errors,errors
        page.close()
    browser.close()
print('Workspace UI: waiting, grouping, search and polling passed at mobile and desktop sizes')
