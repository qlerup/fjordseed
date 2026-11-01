"""Real browser rendering: water covers every tile edge without transparent gaps."""
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1400, 'height': 360})

    def serve(route):
        name = route.request.url.split('/static/', 1)[-1].split('?', 1)[0]
        path = root / 'static' / name
        if '/static/' in route.request.url and path.is_file():
            route.fulfill(path=str(path))
        else:
            route.fulfill(content_type='text/html', body='<!doctype html><html lang="da" data-theme="nordic"><head><link rel="stylesheet" href="/static/style.css"><link rel="stylesheet" href="/static/nordic.css"></head><body></body></html>')

    page.route('http://fjordseed.test/**', serve)
    page.goto('http://fjordseed.test/')
    page.evaluate('''() => {
        document.body.style.cssText="padding:30px;background:#21150f";
        const sample=document.createElement('section');
        sample.style.cssText="padding:60px 70px;background:radial-gradient(ellipse at 40% 30%,#a52d2d,#651a1c);height:240px";
        for(const direction of ['download','upload']){
            const lane=document.createElement('div');lane.className='nordic-voyage-lane';
            lane.dataset.direction=direction;lane.dataset.moving='true';
            lane.innerHTML='<span class="nordic-voyage-label">'+(direction==='download'?'HENTER':'DELER')+'</span><span class="nordic-voyage-water"><i class="nordic-voyage-ship"></i><i class="nordic-voyage-ship"></i></span>';
            lane.style.marginBottom='12px';sample.append(lane);
        }
        document.body.append(sample);
    }''')
    assert page.evaluate('''async () => {
        const image=new Image();image.src='/static/nordic-water.svg';await image.decode();
        const canvas=document.createElement('canvas');canvas.width=1152;canvas.height=38;
        const c=canvas.getContext('2d');
        for(let x=0;x<1152;x+=384)c.drawImage(image,x,0,384,38);
        const pixels=c.getImageData(0,20,1152,1).data;
        return Array.from({length:1152},(_,i)=>pixels[i*4+3]).every(alpha=>alpha>0);
    }''')
    page.locator('.nordic-voyage-ship').evaluate_all("els=>els.forEach((e,i)=>{e.style.animationDelay=(-2-i*2)+'s';e.style.animationPlayState='paused'})")
    page.screenshot(path=str(root / 'test-results/nordic-water-continuous.png'))
    browser.close()
print('PASS continuous water coverage across three SVG tiles at CSS display dimensions')
