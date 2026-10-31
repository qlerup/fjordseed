"""Real picker/drop events, per-file previews, bounded concurrency and partial retry."""
from pathlib import Path
import collections, logging, sys, tempfile, threading, time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flask import request, jsonify
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

logging.getLogger('werkzeug').setLevel(logging.ERROR)
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
 runtime=app.extensions['runtime'];original_status=runtime.status
 runtime.status=lambda:dict(original_status(),ready=True)
 calls=[];previews=collections.Counter();lock=threading.Lock();active=0;maximum=0
 def preview():
  global active,maximum
  file=request.files['torrent'];name=file.filename
  with lock:active+=1;maximum=max(maximum,active);previews[name]+=1;attempt=previews[name]
  try:
   time.sleep(.08)
   if name.startswith('Invalid'):return jsonify(error='Torrentfilen er ugyldig.'),400
   if name.startswith('Alpha') and attempt==1:return jsonify(status='pending',matches=[])
   free=50 if request.form.get('tracker_id') else 100 if name.startswith('Alpha') else 0
   return jsonify(status='matched',matches=[{'tracker_name':'Fixture tracker','freeleech':free,'double_upload':free==100}],
    ratio_estimates=[{'status':'ok','tracker_name':'Fixture tracker','projected_ratio':2 if free else .4,'current_ratio':2,
      'torrent_size':1000,'charged_download':0 if free else 1000,'updated_at':time.time(),'warning':free==0}])
  finally:
   with lock:active-=1
 def add():
  name=request.files['torrent'].filename
  calls.append((name,dict(request.form)))
  if name=='Retry.torrent' and sum(n==name for n,_ in calls)==1:return jsonify(error='Midlertidig fejl. Prøv igen.'),503
  return jsonify(ok=True)
 app.view_functions['preview_torrent']=preview;app.view_functions['add']=add
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/streaming',lambda route:route.fulfill(json={'conversion_enabled':False}))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
   page.get_by_role('button',name='Log ind',exact=True).click()
   for theme in ('fjord','viking','nordic'):
    calls.clear();previews.clear()
    page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
    page.locator(f'[name=theme][value={theme}]').check();page.locator('#appearance-save').click()
    expect(page.locator('html')).to_have_attribute('data-theme',theme)
    page.goto(f'http://127.0.0.1:{server.server_port}/#torrents')
    page.locator('#new-torrent').click()
    alpha={'name':'Alpha.torrent','mimeType':'application/x-bittorrent','buffer':b'dalphae'}
    beta={'name':'Beta.'+'Long.Name.'*15+'torrent','mimeType':'application/x-bittorrent','buffer':b'dbetae'}
    page.locator('#torrent-file').set_input_files([alpha,beta])
    expect(page.locator('#torrent-selection-list li')).to_have_count(2)
    drop=page.evaluate_handle('''() => {
     const data=new DataTransfer();
     data.items.add(new File(['dretrye'],'Retry.torrent'));
     data.items.add(new File(['dalphae'],'Duplicate.torrent'));
     data.items.add(new File(['oops'],'Invalid.torrent'));
     data.items.add(new File(['text'],'Wrong.txt'));return data;
    }''')
    page.locator('#torrent-dropzone').dispatch_event('drop',{'dataTransfer':drop})
    expect(page.locator('#torrent-selection-list li')).to_have_count(4)
    expect(page.locator('#torrent-selection-error')).to_contain_text('allerede valgt')
    expect(page.locator('#torrent-selection-error')).to_contain_text('Wrong.txt')
    bounds=page.locator('#add-dialog').bounding_box();button=page.locator('#add-save').bounding_box()
    assert button['y']+button['height']<=bounds['y']+bounds['height']
    page.screenshot(path=str(root/f'test-results/batch-picker-{theme}.png'))
    page.evaluate("trackerData=[{id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',name:'Anden tracker'}]")
    page.locator('#add-save').click()
    expect(page.locator('.torrent-batch-item')).to_have_count(4)
    alpha_row=page.locator('.torrent-batch-item').filter(has=page.get_by_role('heading',name='Alpha.torrent',exact=True))
    beta_row=page.locator('.torrent-batch-item').filter(has=page.get_by_role('heading',name=beta['name'],exact=True))
    invalid=page.locator('.torrent-batch-item').filter(has=page.get_by_role('heading',name='Invalid.torrent',exact=True))
    expect(alpha_row).to_contain_text('100 % Freeleech')
    expect(alpha_row).to_contain_text('Dobbelt upload')
    expect(alpha_row.locator('summary')).to_contain_text('forventet ratio 2')
    expect(beta_row).to_contain_text('Ingen freeleech')
    expect(beta_row.locator('summary')).to_contain_text('forventet ratio 0,4')
    beta_row.locator('summary').click();expect(beta_row.locator('.ratio-warning-text')).to_be_visible()
    expect(invalid).to_contain_text('Torrentfilen er ugyldig')
    expect(page.locator('#ratio-save')).to_have_text('Start 3 downloads')
    invalid.get_by_role('button',name='Fjern Invalid.torrent',exact=True).click()
    page.locator('#ratio-action').select_option('delete_time');page.locator('#ratio-seed-minutes').fill('60')
    for width in (1440,390,320):
     page.set_viewport_size({'width':width,'height':1000})
     assert page.locator('#ratio-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
     page.locator('#ratio-dialog .dialog-body').evaluate('e=>e.scrollTop=0')
     page.screenshot(path=str(root/f'test-results/batch-review-{theme}-{width}.png'))
    beta_row.locator('select').select_option('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
    expect(beta_row).to_contain_text('50 % Freeleech')
    expect(alpha_row).to_contain_text('100 % Freeleech')
    page.locator('#ratio-save').click()
    expect(page.locator('#ratio-error')).to_contain_text('2 torrents er tilføjet')
    expect(page.locator('#ratio-save')).to_have_text('Prøv 1 igen')
    assert len(calls)==3
    retry=page.locator('.torrent-batch-item').filter(has=page.get_by_role('heading',name='Retry.torrent',exact=True))
    before=previews['Retry.torrent'];retry.get_by_role('button',name='Hent oplysninger igen').click()
    page.wait_for_timeout(200);assert previews['Retry.torrent']>before
    page.locator('#ratio-save').click();expect(page.locator('#ratio-dialog')).not_to_be_visible()
    assert [name for name,_ in calls].count('Alpha.torrent')==1
    assert [name for name,_ in calls].count('Retry.torrent')==2
    assert all(form['ratio_action']=='delete_time' and form['seed_minutes']=='60' for _,form in calls)
    # A new single-file flow retains the original preview UI.
    page.locator('#new-torrent').click();page.locator('#torrent-file').set_input_files(alpha)
    expect(page.locator('#torrent-selection-list li')).to_have_count(1)
    page.locator('#add-save').click();expect(page.locator('#torrent-batch-review')).to_be_hidden()
    expect(page.locator('#preview-benefits')).to_contain_text('100 % Freeleech')
    page.locator('#ratio-dialog .close').click()
   # Closing a still-pending review cancels its rendering and polling.
   page.locator('#new-torrent').click();page.locator('#torrent-file').set_input_files([alpha,beta])
   expect(page.locator('#torrent-selection-list li')).to_have_count(2)
   page.locator('#add-save').click();page.locator('#ratio-back').click()
   page.wait_for_timeout(250);snapshot=dict(previews);page.wait_for_timeout(1000)
   assert dict(previews)==snapshot
   page.locator('#torrent-selection-clear').click()
   page.locator('#torrent-file').set_input_files([
    {'name':'Invalid.torrent','mimeType':'application/x-bittorrent','buffer':b'invalid-one'},
    {'name':'Invalid2.torrent','mimeType':'application/x-bittorrent','buffer':b'invalid-two'}])
   expect(page.locator('#torrent-selection-list li')).to_have_count(2)
   page.locator('#add-save').click()
   expect(page.locator('.torrent-batch-item.has-error')).to_have_count(2)
   expect(page.locator('#ratio-save')).to_be_disabled()
   page.keyboard.press('Escape');expect(page.locator('#ratio-dialog')).not_to_be_visible()
   assert 2<=maximum<=3,maximum
   assert not errors,errors
   browser.close()
 finally:server.shutdown()
print('PASS batch picker/drop, exact file deduplication, individual badges/ratios, invalid files, partial retry, cancellation, single-file flow and all three themes')
