"""Verify independent torrent disclosure through status refreshes and mobile layout."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
root=Path(__file__).resolve().parents[1]
source=(root/'static/app.js').read_text(encoding='utf-8')
start=source.index('function torrentStatus(')
end=source.index('function renderFlow(')
code="const current={ready:true}; const $=s=>document.querySelector(s); function node(tag,cls,text){const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;} function benefitView(){return node('div');}"+source[start:end]
code+=source[source.index('function size(n)'):source.index('function benefitView(')]
torrents=[{'hash':str(i)*40,'name':('Very.long.torrent.name.'*8 if i==1 else 'Linux ISO '+str(i)),
           'state':'stalledUP','progress':1,'size':1024**3,'uploaded':1024**2,
           'ratio':.25,'ratio_limit':1,'seeding_time':3600,'seeding_time_limit':2940,
           'rss_feed':'Feed' if i==3 else None,'added_on':i} for i in [1,2,3]]
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in [390,1440]:
  page=browser.new_page(viewport={'width':width,'height':1000});errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.set_content('<main><div id="torrent-list"></div><p id="empty"></p><div id="rss-torrent-list"></div><p id="rss-empty"></p><span id="rss-count"></span><span id="dl"></span><span id="ul"></span><span id="rss-dl"></span><span id="rss-ul"></span></main>')
  page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'));page.add_script_tag(content=code)
  page.evaluate('torrents=>renderDownloadLists({torrents})',torrents)
  expect(page.locator('.torrent-extra:visible')).to_have_count(0)
  expect(page.locator('.torrent-progress:visible')).to_have_count(3)
  button=page.locator('#torrent-list .torrent-toggle').first
  collapsed=page.locator('#torrent-list .torrent').first.bounding_box()['height']
  button.focus();page.keyboard.press('Enter')
  expect(button).to_have_attribute('aria-expanded','true')
  expect(page.locator('.torrent-extra:visible')).to_have_count(1)
  assert page.locator('#torrent-list .torrent').first.bounding_box()['height']>collapsed
  page.evaluate('torrents=>renderDownloadLists({torrents:[...torrents].reverse()})',torrents)
  expect(button).to_have_attribute('aria-expanded','true');expect(button).to_be_focused()
  rss=page.locator('#rss-torrent-list .torrent-toggle');rss.click()
  expect(page.locator('.torrent-extra:visible')).to_have_count(2)
  button.click();expect(page.locator('.torrent-extra:visible')).to_have_count(1)
  expect(rss).to_have_attribute('aria-expanded','true')
  page.evaluate('torrents=>renderDownloadLists({torrents})',torrents)
  expect(rss).to_have_attribute('aria-expanded','true')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert page.locator('.torrent').evaluate_all('rows=>rows.every(e=>e.scrollWidth<=e.clientWidth+1)')
  assert not errors,errors
  folder=root/'test-results';folder.mkdir(exist_ok=True)
  page.screenshot(path=str(folder/f'torrent-details-{width}.png'),full_page=True)
  page.close()
 browser.close()
print('PASS collapsed defaults, independent manual/RSS disclosure, refresh persistence, keyboard/focus, and mobile/desktop layout')
