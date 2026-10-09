"""Tracker account shards: missing values are distinct from actual zero."""
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
source=(root/'static/trackers.js').read_text(encoding='utf-8')
code="function node(tag,cls,text){const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;}"+source[:source.index('function resetTrackerForm')]
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content('<main></main>')
    page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'))
    page.add_script_tag(content=code)
    for width in (390,1440):
        page.set_viewport_size({'width':width,'height':900})
        for value,expected in [(None,'Ikke oplyst'),(0,'0'),(12.5,'12,5')]:
            page.evaluate("value=>document.querySelector('main').replaceChildren(trackerCard({name:'NordicBytes',status:'ok',stats:{shards:value}}))",value)
            metric=page.locator('.tracker-stats > div').filter(has=page.get_by_text('SHARDS',exact=True))
            assert metric.locator('strong').inner_text()==expected
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert not errors,errors
    browser.close()
    print('PASS shards missing/zero/fractional values at mobile and desktop widths')
