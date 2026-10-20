"""Independent five-item pages survive refreshes, deletion and narrow layouts."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1]
source = (root/'static/app.js').read_text(encoding='utf-8')
code = "const $=s=>document.querySelector(s);function node(tag,cls,text){const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;}function card(t){return node('article','torrent',t.name);}function size(n){return String(n);}"
code += source[source.index('function renderDownloadLists('):source.index('function renderFlow(')]
rows = [dict(name=f'{kind} {i:02}', hash=f'{kind}{i}', added_on=i, rss_feed='Feed' if kind=='RSS' else None,
             dlspeed=1, upspeed=2) for kind in ['Manual','RSS'] for i in range(13)]

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in [390, 1440]:
        page = browser.new_page(viewport={'width':width,'height':1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_content('<main><div id="torrent-list"></div><p id="empty">Ingen downloads</p><div id="rss-torrent-list"></div><p id="rss-empty">Ingen RSS</p><span id="rss-count"></span><span id="dl"></span><span id="ul"></span><span id="rss-dl"></span><span id="rss-ul"></span></main>')
        page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'))
        page.add_script_tag(content=code)
        page.evaluate('torrents=>renderDownloadLists({torrents})', rows)
        expect(page.locator('#torrent-list .torrent')).to_have_count(5)
        expect(page.locator('#rss-torrent-list .torrent')).to_have_count(5)
        expect(page.locator('#manual-pagination')).to_contain_text('1–5 af 13')
        page.locator('#manual-pagination button').last.click()
        expect(page.locator('#torrent-list')).to_contain_text('Manual 07')
        expect(page.locator('#rss-torrent-list')).to_contain_text('RSS 12')
        page.evaluate('torrents=>renderDownloadLists({torrents})', rows)
        expect(page.locator('#manual-pagination')).to_contain_text('Side 2 af 3')
        expect(page.locator('#dl')).to_have_text('13/s')
        page.locator('#rss-pagination button').last.click()
        page.locator('#rss-pagination button').last.click()
        expect(page.locator('#rss-torrent-list .torrent')).to_have_count(3)
        expect(page.locator('#rss-pagination button').last).to_be_disabled()
        # Remaining rows reduce the page count; RSS clamps without resetting Manual.
        reduced = [r for r in rows if not r['rss_feed'] or r['added_on'] < 7]
        page.evaluate('torrents=>renderDownloadLists({torrents})', reduced)
        expect(page.locator('#rss-pagination')).to_contain_text('Side 2 af 2')
        expect(page.locator('#manual-pagination')).to_contain_text('Side 2 af 3')
        page.evaluate('renderDownloadLists({torrents:[]})')
        expect(page.locator('#rss-pagination')).to_be_hidden()
        expect(page.locator('#manual-pagination')).to_be_hidden()
        expect(page.locator('#empty')).to_be_visible()
        page.evaluate('torrents=>renderDownloadLists({torrents})', rows)
        # Activity is measured by transfer rates, including idle seeding states.
        idle = [{**r,'hash':'idle-'+r['hash'],'name':'Idle '+r['name'],
                 'dlspeed':0,'upspeed':0,'state':'uploading','added_on':r['added_on']+20} for r in rows]
        grouped=rows+idle
        page.evaluate('torrents=>renderDownloadLists({torrents})', grouped)
        expect(page.locator('#manual-inactive')).not_to_have_attribute('open','')
        expect(page.locator('#manual-inactive-summary')).to_have_text('Inaktive torrents (13)')
        expect(page.locator('#manual-inactive-list .torrent')).to_have_count(5)
        expect(page.locator('#torrent-list')).not_to_contain_text('Idle')
        page.locator('#manual-inactive-summary').focus()
        page.keyboard.press('Enter')
        expect(page.locator('#manual-inactive-list')).to_be_visible()
        page.locator('#manual-inactive-pagination button').last.click()
        expect(page.locator('#manual-inactive-pagination')).to_contain_text('Side 2 af 3')
        expect(page.locator('#manual-pagination')).to_contain_text('Side 1 af 3')
        page.locator('#rss-inactive-summary').click()
        page.locator('#rss-inactive-pagination button').last.click()
        page.locator('#rss-inactive-pagination button').last.click()
        expect(page.locator('#rss-inactive-list .torrent')).to_have_count(3)
        page.evaluate('torrents=>renderDownloadLists({torrents})', grouped)
        expect(page.locator('#manual-inactive-list')).to_be_visible()
        expect(page.locator('#manual-inactive-pagination')).to_contain_text('Side 2 af 3')
        # Only uploading, only downloading and no transfer all move automatically.
        changed=[{**r,'dlspeed':0,'upspeed':0} for r in rows]+[
            {**r,'upspeed':1 if i==0 else 0,'dlspeed':1 if i==1 else 0} for i,r in enumerate(idle)]
        page.evaluate('torrents=>renderDownloadLists({torrents})', changed)
        expect(page.locator('#torrent-list .torrent')).to_have_count(2)
        expect(page.locator('#torrent-list')).to_contain_text('Idle Manual')
        expect(page.locator('#manual-inactive-summary')).to_have_text('Inaktive torrents (24)')
        expect(page.locator('#manual-pagination')).to_be_hidden()
        page.evaluate('torrents=>renderDownloadLists({torrents})', idle)
        expect(page.locator('#manual-active-empty')).to_be_visible()
        expect(page.locator('#empty')).not_to_be_visible()
        page.evaluate('renderDownloadLists({torrents:[]})')
        expect(page.locator('#manual-inactive')).to_be_hidden()
        expect(page.locator('#rss-inactive')).to_be_hidden()
        page.evaluate('torrents=>renderDownloadLists({torrents})', grouped)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        assert not errors, errors
        page.screenshot(path=str(root/'test-results'/f'pagination-{width}.png'), full_page=True)
        page.close()
    browser.close()
print('PASS five per page, independent lists, refresh, shrinking lists, empty state and responsive layout')
