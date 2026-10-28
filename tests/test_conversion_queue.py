import copy
import time
from unittest.mock import Mock

import pytest

from remote_conversion import RemoteConversion
from test_remote_conversion import setup


def prepare(setup,monkeypatch,online=True,server=True):
    app,manager,client,headers=setup
    pc=manager.create('PC');folder=r'M:\Bibliotek'
    manager.workspace(pc,folder,[{'name':f'{name}.mkv','size':100} for name in ('a','b','c')],conversion_version=1)
    devices=manager.devices();devices[0]['last_seen']=time.time() if online else 0;manager.write(devices)
    if server:monkeypatch.setenv('FJORDSEED_CONVERTER_CONTAINER','test-converter')
    else:monkeypatch.delenv('FJORDSEED_CONVERTER_CONTAINER',raising=False)
    jobs={}
    def rpc(action,data):
        if action=='library-shared-capacity':return {'ready':True}
        if action=='library-shared-queue':
            ident=f'{len(jobs)+1:032x}'
            jobs[ident]={**data,'id':ident,'action':'convert','phase':'queued','state':'queued','progress':0,'attempt':'a'*32}
            return copy.deepcopy(jobs[ident])
        if action=='library-shared-status':return copy.deepcopy(jobs[data['id']])
        if action=='library-shared-fallback':jobs[data['id']]['executor']='server';return copy.deepcopy(jobs[data['id']])
        if action=='library-shared-complete':jobs[data['id']]['state']='ready';return copy.deepcopy(jobs[data['id']])
        raise AssertionError(action)
    manager.runtime.rpc=Mock(side_effect=rpc)
    def add(name):return manager.select_file(pc['id'],folder,name+'.mkv',30)
    return manager,pc,jobs,add


def test_fifo_is_durable_and_does_not_replace_running_job(setup,monkeypatch):
    manager,pc,jobs,add=prepare(setup,monkeypatch)
    first=add('a');add('b');add('c')
    assert len(jobs)==1
    assert manager.devices()[0]['selection']['id']==first['id']
    manager=RemoteConversion(manager.state,manager.runtime)
    jobs[first['id']].update(state='completed',phase='published')
    manager.tick()
    assert manager.devices()[0]['selection']['name']=='b.mkv'
    assert [q['name'] for q in manager.public()[0]['queue']]==['b.mkv','c.mkv']


def test_offline_requests_wait_without_gpu_and_start_when_pc_returns(setup,monkeypatch):
    manager,pc,jobs,add=prepare(setup,monkeypatch,online=False,server=False)
    task=add('a');manager.tick()
    assert task['state']=='queued' and not jobs
    reply=manager.workspace(pc,r'M:\Bibliotek',conversion_version=1)
    assert reply['selection']['name']=='a.mkv'
    assert reply['selection']['executor']=='pc'


def test_server_fallback_is_not_sent_to_returning_pc_and_next_job_prefers_pc(setup,monkeypatch):
    manager,pc,jobs,add=prepare(setup,monkeypatch,online=False)
    add('a');add('b');manager.tick()
    selected=manager.devices()[0]['selection'];ident=selected['id']
    assert selected['executor']=='server'
    assert manager.workspace(pc,r'M:\Bibliotek',conversion_version=1)['selection'] is None
    with pytest.raises(ValueError,match='serverens GPU'):manager.shared_result(pc,ident)
    jobs[ident]['state']='encoded';manager.tick()
    assert jobs[ident]['state']=='ready' and len(jobs)==1
    jobs[ident].update(state='completed',phase='published');manager.tick()
    assert manager.devices()[0]['selection']['executor']=='pc'
    assert manager.devices()[0]['selection']['name']=='b.mkv'


def test_duplicate_cancellation_and_csrf_scope(setup,monkeypatch):
    manager,pc,jobs,add=prepare(setup,monkeypatch,online=False,server=False)
    task=add('a')
    with pytest.raises(ValueError,match='allerede'):add('a')
    client=setup[2];url=f'/api/conversion/devices/{pc["id"]}/queue/{task["id"]}/cancel'
    assert client.post(url).status_code==403
    with pytest.raises(ValueError):manager.cancel_queued('other',task['id'])
    assert client.post(url,headers=setup[3]).status_code==200
    manager.workspace(pc,r'M:\Bibliotek',conversion_version=1)
    assert not jobs


def test_pc_disappearing_before_claim_allows_server_takeover(setup,monkeypatch):
    manager,pc,jobs,add=prepare(setup,monkeypatch)
    selected=add('a')
    devices=manager.devices();devices[0]['last_seen']=0;manager.write(devices)
    manager.tick()
    assert manager.devices()[0]['selection']['executor']=='server'
    assert len(jobs)==1  # Reuse this job, never encode a second copy.


def test_started_pc_job_is_not_handed_over_when_pc_goes_offline(setup,monkeypatch):
    manager,pc,jobs,add=prepare(setup,monkeypatch)
    selected=add('a');jobs[selected['id']]['claimed']=True
    devices=manager.devices();devices[0]['last_seen']=0;manager.write(devices)
    manager.tick()
    assert manager.devices()[0]['selection']['executor']=='pc'
    manager.runtime.rpc.assert_any_call('library-shared-status',{'device':pc['id'],'id':selected['id']})
    assert not any(c.args[0]=='library-shared-fallback' for c in manager.runtime.rpc.call_args_list)


def test_browser_can_queue_multiple_files_while_one_is_running(setup,monkeypatch):
    import threading
    from werkzeug.serving import make_server
    playwright_api=pytest.importorskip('playwright.sync_api')
    sync_playwright,expect=playwright_api.sync_playwright,playwright_api.expect
    manager,pc,jobs,add=prepare(setup,monkeypatch,server=False)
    app=setup[0];server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
            page.route('**/bitrates',lambda r:r.fulfill(json={'media_folder':r'M:\Bibliotek','files':[],'pending':False}))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((manager.state.root/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind',exact=True).click()
            page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
            page.locator('.workspace-file').nth(0).get_by_role('button',name='Sæt i kø',exact=True).click()
            expect(page.locator('.workspace-job-name')).to_have_text('a.mkv')
            page.locator('.workspace-file').nth(1).get_by_role('button',name='Sæt i kø',exact=True).click()
            expect(page.locator('.workspace-queue-row')).to_have_count(1)
            page.locator('.workspace-file').nth(2).get_by_role('button',name='Sæt i kø',exact=True).click()
            expect(page.locator('.workspace-queue-row')).to_have_count(2)
            assert len(jobs)==1
            page.locator('.workspace-queue-row').first.get_by_role('button').click()
            expect(page.locator('.workspace-queue-row')).to_have_count(1)
            expect(page.locator('.workspace-queue-row')).to_contain_text('c.mkv')
            browser.close()
    finally:server.shutdown()
