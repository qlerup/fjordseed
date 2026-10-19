"""Refresh existing torrent metadata from the details panel without torrent actions."""
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[1]
source=(root/'static/app.js').read_text(encoding='utf-8')
code=source[source.index('function node('):source.index('function toast(')]
code+=source[source.index('function benefitView('):source.index('function renderRatioPreview(')]
code+=source[source.index('function torrentDetails('):source.index('function torrentProgress(')]
code+='''
const calls=[];let refreshes=0;
async function api(url,options){calls.push({url,method:options.method});return {ok:true};}
function toast(text){}
async function refresh(){refreshes++;}
'''
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in (390,1100):
        page=browser.new_page(viewport={'width':width,'height':650})
        page.set_content('<meta charset="utf-8"><div id="details"></div>')
        page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'))
        page.add_script_tag(content=code)
        page.evaluate("""() => document.querySelector('#details').append(torrentDetails({
            hash:'a'.repeat(40),name:'Example release',seeding_unlimited:true,
            benefits:{status:'unavailable',message:'Tracker unavailable'}}))""")
        button=page.get_by_role('button',name='Hent trackerdata igen for Example release')
        expect(button).to_be_enabled()
        button.click()
        expect(button).to_be_enabled()
        assert page.evaluate('calls')==[{'url':'/api/torrents/'+'a'*40+'/refresh-metadata','method':'POST'}]
        assert page.evaluate('refreshes')==1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.evaluate("""() => document.querySelector('#details').replaceChildren(torrentDetails({
            hash:'a'.repeat(40),name:'Example release',seeding_unlimited:true,
            benefits:{status:'pending'}}))""")
        expect(page.locator('.torrent-metadata-refresh')).to_be_disabled()
        print('PASS metadata refresh action and pending state, width',width)
        page.close()
    browser.close()
