"""Exercise the per-film wizard without modifying torrents or library files."""
from pathlib import Path, PurePosixPath
import argparse, copy, json, sys, tempfile, threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--theme',choices=('fjord','nordic'),default='nordic')
theme=parser.parse_args().theme
artifacts=Path(__file__).resolve().parents[1]/'test-results'/'conversion-workflow'
artifacts.mkdir(parents=True,exist_ok=True)

media={'format':{'duration':'7200'},'streams':[
 {'index':0,'codec_type':'video','codec_name':'hevc','width':3840,'height':2160},
 {'index':1,'codec_type':'audio','codec_name':'truehd','channels':6,'channel_layout':'5.1','bit_rate':'4000000','tags':{'language':'eng'}},
 {'index':2,'codec_type':'audio','codec_name':'aac','channels':2,'bit_rate':'192000','tags':{'language':'dan'}},
 {'index':3,'codec_type':'subtitle','codec_name':'subrip','tags':{'language':'dan'}}]}
items=[{'id':str(i),'name':f'Film-{i}.mkv','title':f'Film {i} · En rejse gennem fjorden','size':50*1024**3,'eligible':True,'skipped_modes':[],'cover':None} for i in range(1,4)]
items[2]['size']=512*1024**2
items[1]['size']=1024**3  # Conversion grows this file; the first film saves space.
items.reverse()  # Deliberately unsorted: largest saving must be shown first.
class Demo(FakeRuntime):
 host_downloads=PurePosixPath('/downloads')
 def status(self):return {**super().status(),'enabled':True,'ready':True}

with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=Demo)
 # These mocked requests are short; serialize them to keep the browser check
 # usable in CI containers with a small process/thread allowance.
 server=make_server('127.0.0.1',0,app,threaded=False)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];submitted=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/conversion/workflow',lambda r:r.fulfill(json={'items':copy.deepcopy(items),'jobs':[]}))
   page.route('**/api/conversion/workflow/*/media',lambda r:r.fulfill(json={'media':media,'fingerprint':[50*1024**3,1]}))
   def queue(route):submitted.append(route.request.post_data_json);route.fulfill(json={'ok':True})
   page.route('**/api/conversion/workflow/queue',queue)
   def skip(route):
    data=route.request.post_data_json
    for item in items:
     if item['id'] in data.get('ids',[data.get('id')]):item['skipped_modes']=[data['mode']] if data['skip'] else []
    route.fulfill(json={'ok':True})
   page.route('**/api/conversion/workflow/skip',skip)
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip());page.get_by_role('button',name='Log ind',exact=True).click()
   page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
   page.locator(f'[name=theme][value={theme}]').check()
   page.locator('#appearance-save').click()
   expect(page.locator('#appearance-status')).to_contain_text('er gemt')
   page.reload()
   expect(page.locator('html')).to_have_attribute('data-theme',theme)
   page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000});expect(page.locator('#cw-cards')).to_be_visible()
    assert page.locator('.cw-card').count()==4
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(artifacts/f'{theme}-cards-{width}.png'),full_page=True)
   page.locator('[data-mode=full]').click();expect(page.locator('.cw-film')).to_have_count(3)
   expect(page.locator('.cw-film').first).to_contain_text('20 Mbps')
   expect(page.locator('.cw-film').first.locator('.cw-estimate')).to_have_count(3)
   expect(page.locator('.cw-film').first.locator('.cw-estimate').first).to_contain_text('Forventet slutstørrelse')
   expect(page.locator('.cw-film').first.locator('.cw-estimate').first).to_contain_text('Spar ')
   expect(page.locator('.cw-film').nth(1).locator('.cw-estimate').first).to_contain_text('Ekstra plads: ')
   for width in (1920,1440,1024,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    for card in page.locator('.cw-estimate').all():
     assert card.evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    if width<=600:
     assert page.locator('.cw-estimates').first.bounding_box()['width']>=width-100
    if width>=1200:
     info=page.locator('.cw-film-info').first.bounding_box(); estimates=page.locator('.cw-film-estimates').first.bounding_box()
     assert estimates['x']>=info['x']+info['width'], 'desktop estimates must use the space beside metadata'
     assert page.locator('.cw-film').first.bounding_box()['height']<220, 'film rows should remain compact'
    page.screenshot(path=str(artifacts/f'{theme}-estimates-{width}.png'),full_page=True)
    # Focused captures keep the sticky selection toolbar outside each film,
    # making every estimate readable in the saved review evidence.
    for index,kind in ((0,'saving'),(1,'growth')):
     film=page.locator('.cw-film').nth(index)
     film.evaluate("e=>e.scrollIntoView({block:'start'})")
     film.screenshot(path=str(artifacts/f'{theme}-{kind}-{width}.png'))
    print(f'PASS {theme} {width}px: savings + growth estimates, no page/card overflow',flush=True)
   page.set_viewport_size({'width':1920,'height':1000})
   expect(page.locator('#cw-selection')).to_be_hidden()
   expect(page.locator('.cw-film').first).to_have_attribute('data-file-id','1')
   def film_layout():
    return page.locator('.cw-film').evaluate_all('(films)=>films.map(f=>[f,...f.children].map(e=>{const r=e.getBoundingClientRect();return [r.x+scrollX,r.y+scrollY,r.width,r.height]}))')
   before_selection=film_layout()
   page.locator('.cw-film input[type=checkbox]').nth(0).check()
   # The overlay may cover part of a row; keyboard selection stays available.
   page.locator('.cw-film input[type=checkbox]').nth(1).focus()
   page.locator('.cw-film input[type=checkbox]').nth(1).press('Space')
   expect(page.locator('#cw-selection')).to_be_visible()
   page.wait_for_function("()=>document.querySelector('#cw-selection').getAnimations().every(a=>a.playState==='finished')")
   assert film_layout()==before_selection, 'Selecting films must not move or resize rows or their contents'
   assert page.locator('#cw-selection').bounding_box()['x']==0
   for width in (1440,2560):
    page.set_viewport_size({'width':width,'height':1000})
    selected_layout=film_layout()
    page.locator('#cw-clear-selected').click()
    expect(page.locator('#cw-selection')).to_be_hidden()
    assert film_layout()==selected_layout, f'Clearing selection moved the layout at {width}px'
    page.locator('.cw-film input[type=checkbox]').nth(0).check()
    page.locator('.cw-film input[type=checkbox]').nth(1).focus()
    page.locator('.cw-film input[type=checkbox]').nth(1).press('Space')
    assert film_layout()==selected_layout, f'Selecting films moved the layout at {width}px'
   page.set_viewport_size({'width':1920,'height':1000})
   page.wait_for_function("()=>document.querySelector('#cw-selection').getAnimations().every(a=>a.playState==='finished')")
   expect(page.locator('.cw-selection-chain').first).to_be_visible()
   page.emulate_media(reduced_motion='reduce')
   assert page.locator('#cw-selection').evaluate("e=>getComputedStyle(e).animationName")=='none'
   page.emulate_media(reduced_motion='no-preference')
   page.wait_for_function("()=>document.querySelector('#cw-selection').getAnimations().every(a=>a.playState==='finished')")
   page.screenshot(path=str(artifacts/f'{theme}-selection-desktop.png'))
   for width in (1440,1280,1024,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), f'selection overflow at {width}'
    assert page.locator('#cw-selection').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
   page.screenshot(path=str(artifacts/f'{theme}-selection-mobile.png'))

   page.locator('#cw-configure').click()
   expect(page.locator('#cw-step')).to_contain_text('FILM 1 AF 2')
   page.locator('#cw-fields select').first.select_option('20',force=True)
   expect(page.locator('.cw-live')).to_contain_text('GiB')
   expect(page.locator('.cw-live')).to_contain_text('Spar ')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000});assert page.locator('#cw-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    expect(page.locator('.cw-live .cw-estimate')).to_be_visible()
    assert page.locator('.cw-live').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    page.screenshot(path=str(artifacts/f'{theme}-modal-{width}.png'))
    print(f'PASS {theme} {width}px: conversion dialog + live savings, no overflow',flush=True)
   page.locator('#cw-next').click();expect(page.locator('#cw-step')).to_contain_text('FILM 2 AF 2')
   page.locator('#cw-fields select').first.select_option('40',force=True)
   expect(page.locator('.cw-live')).to_contain_text('Ekstra plads: ')
   page.locator('#cw-next').click();expect(page.locator('#cw-dialog-title')).to_have_text('Gennemse din konverteringskø')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    assert page.locator('#cw-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    expect(page.locator('#cw-fields')).to_contain_text('Spar ')
    expect(page.locator('#cw-fields')).to_contain_text('Ekstra plads: ')
    page.screenshot(path=str(artifacts/f'{theme}-review-{width}.png'))
    print(f'PASS {theme} {width}px: queue review savings + growth, no overflow',flush=True)
   page.locator('#cw-next').click();expect(page.locator('#cw-dialog')).not_to_be_visible()
   assert [i['options']['bitrate'] for i in submitted[0]['items']]==[20,40]
   page.locator('#cw-back').click();page.locator('[data-mode=audio]').click()
   expect(page.locator('.cw-film').first).not_to_contain_text('3840')
   page.locator('.cw-film').first.get_by_role('button',name='Spring over',exact=True).click();expect(page.locator('.cw-film')).to_have_count(2)
   page.locator('#cw-show-skipped').check();expect(page.locator('.cw-film')).to_have_count(3)
   page.locator('.cw-film').first.get_by_role('button',name='Gendan',exact=True).click()
   page.locator('.cw-film input[type=checkbox]').first.check();page.locator('#cw-configure').click()
   expect(page.locator('#cw-fields')).not_to_contain_text('Videobitrate');expect(page.locator('#cw-fields')).not_to_contain_text('Dolby Vision')
   expect(page.locator('#cw-fields')).to_contain_text('Behold lyd')
   page.locator('#cw-close').click();page.locator('#cw-back').click();page.locator('[data-mode=video]').click()
   expect(page.locator('.cw-film').first).not_to_contain_text('TRUEHD')
   page.locator('.cw-film input[type=checkbox]').first.check();page.locator('#cw-configure').click()
   expect(page.locator('#cw-fields')).not_to_contain_text('Behold lyd');expect(page.locator('#cw-fields')).to_contain_text('Videobitrate')
   page.locator('#cw-skip-film').click();expect(page.locator('#cw-next')).to_be_disabled()
   page.locator('#cw-close').click()
   # Wizard skip persists only in video; converted/manual films remain discoverable.
   page.locator('#cw-show-skipped').uncheck()
   expect(page.locator('.cw-film')).to_have_count(2)
   items.append({'id':'4','name':'Manual.mkv','title':'Manuel film','size':1000,'eligible':True,'source':'manual','skipped_modes':[]})
   items.append({'id':'5','name':'Converted.mkv','title':'Konverteret film','size':1000,'eligible':False,'converted':True,'completed_modes':['video'],'skipped_modes':[]})
   page.locator('#cw-refresh').click();expect(page.locator('.cw-film')).to_have_count(3)
   expect(page.locator('#cw-films')).to_contain_text('Manuelt tilføjet')
   page.locator('#cw-show-completed').check();expect(page.locator('.cw-film')).to_have_count(4)
   expect(page.locator('.cw-completed')).to_have_count(1)
   page.locator('#cw-show-completed').uncheck()
   page.locator('#cw-back').click();page.locator('[data-mode=audio]').click()
   expect(page.locator('.cw-film')).to_have_count(5)
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   manual=page.locator('.cw-film[data-file-id="4"] input[type=checkbox]')
   expect(manual).to_be_enabled();manual.check();page.locator('#cw-configure').click()
   expect(page.locator('#cw-fields select').last).to_have_value('keep')
   expect(page.locator('#cw-fields')).to_contain_text('Originals ved siden af Seeder')
   expect(page.locator('#cw-fields')).not_to_contain_text('Seeding og oprydning')
   page.locator('#cw-fields select').last.select_option('delete',force=True)
   page.locator('#cw-next').click()
   expect(page.locator('#cw-fields')).to_contain_text('Originalen slettes efter kontrol')
   page.locator('#cw-next').click();expect(page.locator('#cw-dialog')).not_to_be_visible()
   assert submitted[-1]['items'][0]['options']['delete_original'] is True
   expect(page.locator('#cw-selection')).to_be_hidden()
   for ident in ('1','2'):page.locator(f'.cw-film[data-file-id="{ident}"] input[type=checkbox]').check()
   page.locator('#cw-skip-selected').click();expect(page.locator('.cw-film')).to_have_count(3)
   page.locator('#cw-show-skipped').check();expect(page.locator('.cw-film')).to_have_count(5)
   assert not errors,errors
   print('PASS: cards, responsive 1440/390/320, per-film settings, estimates, queue submission, skip/restore, audio/video boundaries; no JS errors')
   browser.close()
 finally:server.shutdown()
