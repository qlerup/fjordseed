"""Thirty seconds of observed zero traffic before moving manual/RSS cards."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]
source=(root/'static/app.js').read_text(encoding='utf-8')
code="""const $=s=>document.querySelector(s);
function node(tag,cls,text){const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;}
function card(t){return node('article','torrent',t.name);}
function size(n){return String(n);}
window.activityClock=0;performance.now=()=>activityClock;
window.sample=(rows,at,extra={})=>{activityClock=at;renderDownloadLists({id:'seed',profile_id:'vpn',torrents:rows,...extra});};
"""+source[source.index('function renderDownloadLists('):source.index('function renderFlow(')]
rows=[dict(hash=kind+str(i),name=kind+str(i),rss_feed='Feed' if kind=='RSS' else None,
           dlspeed=100 if kind=='Manual' else 0,upspeed=100 if kind=='RSS' else 0,added_on=i)
      for kind in ('Manual','RSS') for i in range(6)]
idle=[{**row,'dlspeed':0,'upspeed':0} for row in rows]
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in (390,1440):
        page=browser.new_page(viewport={'width':width,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.set_content('<main><div id="torrent-list"></div><p id="empty"></p><div id="rss-torrent-list"></div><p id="rss-empty"></p><span id="rss-count"></span><span id="dl"></span><span id="ul"></span><span id="rss-dl"></span><span id="rss-ul"></span></main>')
        page.evaluate("""() => {for(const id of ['count','shared-download-count','shared-queue-count','shared-queue-breakdown']){
            const span=document.createElement('span');span.id=id;document.querySelector('main').append(span);
        }}""")
        page.add_script_tag(content=code)
        page.evaluate('rows=>sample(rows,0)',rows)
        page.evaluate('rows=>sample(rows,1000)',idle)
        page.evaluate('rows=>sample(rows,30999)',idle)
        for prefix in ('manual','rss'):
            expect(page.locator('#'+prefix+'-active-heading')).to_have_text('Aktive torrents (6)')
            expect(page.locator('#'+prefix+'-inactive')).not_to_be_visible()
        expect(page.locator('#torrent-list .torrent')).to_have_count(5)
        expect(page.locator('#rss-torrent-list .torrent')).to_have_count(5)
        # Page navigation with old data cannot manufacture another status sample.
        page.evaluate('activityClock=31000')
        page.locator('#manual-pagination button').last.click()
        expect(page.locator('#manual-active-heading')).to_have_text('Aktive torrents (6)')
        # A short recovery resets the buffer independently for each torrent.
        resume=[{**row,'upspeed':100} if row['hash']=='RSS0' else row for row in idle]
        page.evaluate('rows=>sample(rows,31000)',resume)
        expect(page.locator('#manual-active-empty')).to_be_visible()
        expect(page.locator('#manual-inactive-summary')).to_have_text('Inaktive torrents (6)')
        expect(page.locator('#rss-active-heading')).to_have_text('Aktive torrents (1)')
        page.evaluate('rows=>sample(rows,32000)',idle)
        page.evaluate('rows=>sample(rows,61999)',idle)
        expect(page.locator('#rss-active-heading')).to_have_text('Aktive torrents (1)')
        page.evaluate('rows=>sample(rows,62000)',idle)
        expect(page.locator('#rss-active-empty')).to_be_visible()
        expect(page.locator('#rss-inactive-summary')).to_have_text('Inaktive torrents (6)')
        page.locator('#rss-inactive-summary').click()
        expect(page.locator('#rss-inactive-list .torrent')).to_have_count(5)
        # Starting upload/download returns to the top immediately.
        page.evaluate('rows=>sample(rows,63000)',rows)
        expect(page.locator('#rss-active-heading')).to_have_text('Aktive torrents (6)')
        expect(page.locator('#manual-active-heading')).to_have_text('Aktive torrents (6)')
        page.evaluate('rows=>sample(rows,64000)',idle)
        page.evaluate('rows=>sample(rows,90000,{torrents_available:false})',idle)
        page.evaluate('rows=>sample(rows,120000,{torrents_available:false})',idle)
        expect(page.locator('#manual-active-heading')).to_have_text('Aktive torrents (6)')
        page.evaluate('rows=>sample(rows,121000)',idle)
        page.evaluate('rows=>sample(rows,150999)',idle)
        expect(page.locator('#manual-active-heading')).to_have_text('Aktive torrents (6)')
        page.evaluate('rows=>sample(rows,151000)',idle)
        expect(page.locator('#manual-active-empty')).to_be_visible()
        # Removing/re-adding a torrent cannot reuse a previous active timer.
        page.evaluate('rows=>sample(rows,152000)',rows)
        page.evaluate('sample([],153000)')
        page.evaluate('rows=>sample(rows,154000)',idle)
        expect(page.locator('#manual-active-empty')).to_be_visible()
        page.evaluate('rows=>sample(rows,155000)',rows)
        page.evaluate('rows=>sample(rows,156000,{profile_id:"different-vpn"})',idle)
        expect(page.locator('#rss-active-empty')).to_be_visible()
        assert not errors,errors
        page.close()
    browser.close()
print('PASS 30-second idle threshold, short recovery, immediate activation, per-torrent state, pagination, unavailable status and cleanup')
