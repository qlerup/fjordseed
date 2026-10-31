"""Ships cross both banks despite card replacement and changing live rates."""
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
source = (root / 'static/app.js').read_text(encoding='utf-8')
code = """
const current={ready:true};
function node(tag,cls,text){const n=document.createElement(tag);n.className=cls||'';
 if(text!==undefined)n.textContent=text;return n;}
function eta(){return '';}
function size(n){return String(n);}
window.sampleClock=0;
performance.now=()=>sampleClock;
""" + source[source.index('function torrentStatus('):source.index('const expandedTorrents')]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width':1440,'height':900})
    page.set_content('<html data-theme="nordic"><main></main></html>')
    page.add_style_tag(content=(root/'static/nordic.css').read_text(encoding='utf-8'))
    page.add_style_tag(content='main{width:1000px}.nordic-voyage-ship{animation-play-state:paused!important}')
    page.add_script_tag(content=code)
    samples = []
    for clock in (0, 1000, 3000, 5000, 7000, 7999, 9000):
        page.evaluate('''clock=>{
            sampleClock=clock;
            document.querySelector('main').replaceChildren(torrentProgress({
                name:'Voyage fixture',state:'downloading',progress:.5,size:1000,
                dlspeed:100000+clock,upspeed:200000+clock}));
        }''', clock)
        samples.append(page.locator('.nordic-voyage-lane').evaluate_all('''lanes=>lanes.map(lane=>{
            const water=lane.querySelector('.nordic-voyage-water').getBoundingClientRect();
            const ship=lane.querySelector('.nordic-voyage-ship').getBoundingClientRect();
            return {left:(ship.left-water.left)/water.width,
                    right:(ship.right-water.left)/water.width};
        })'''))
    # Download enters from the right and exits fully on the left; upload does
    # the reverse. Rebuilding at intermediate polls must retain that journey.
    assert samples[0][0]['left'] >= .99, samples
    assert samples[5][0]['right'] <= .01, samples
    assert samples[0][1]['right'] <= .01, samples
    assert samples[5][1]['left'] >= .99, samples
    assert all(samples[i][0]['left'] > samples[i+1][0]['left'] for i in range(5)), samples
    assert all(samples[i][1]['left'] < samples[i+1][1]['left'] for i in range(5)), samples
    for direction in (0,1):
        assert abs(samples[1][direction]['left']-samples[6][direction]['left']) < .02, samples
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.nordic-voyage-ship').first.evaluate('e=>getComputedStyle(e).animationName') == 'none'
    browser.close()
print('PASS uninterrupted full-width download/upload crossings across polls, rate changes, wraparound and reduced motion')
