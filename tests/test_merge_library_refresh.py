import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from merge_library_refresh import LibraryRefresh
import merge_media as merge


@pytest.fixture
def worker(tmp_path):
    runtime=SimpleNamespace(state=SimpleNamespace(root=tmp_path),rpc=Mock(),client=Mock())
    service=LibraryRefresh(runtime)
    service.config.write_text(json.dumps({'fjordflix_container':'fjordflix','plex_url':'http://plex:32400',
        'plex_token':'private-test-token','plex_root':'/media'}))
    job={'id':'a'*32,'relative':'Film/new.merged-12345678.mkv','refresh':{},'started_at':10**12}
    runtime.rpc.return_value={'jobs':[job]}
    return service,runtime,job


def updates(runtime):
    return [c.args[1] for c in runtime.rpc.call_args_list if c.args[0]=='library-merge-refresh-update']


def test_refresh_waits_for_flix_index_then_plex_link_and_persists_services(worker):
    service,runtime,job=worker
    service.flix=Mock(return_value=False);service.plex=Mock(return_value=False)
    service.tick()
    assert updates(runtime)[-1]['refresh']=={} and not service.plex.called
    service.next_at.clear(); service.flix.return_value=True;service.tick()
    assert updates(runtime)[-1]['refresh']=={'fjordflix':True}
    job['refresh']={'fjordflix':True};service.next_at.clear();service.plex.return_value=True
    service.flix.reset_mock();service.tick()
    service.flix.assert_not_called()
    assert updates(runtime)[-1]['refresh']=={'fjordflix':True,'plex':True}
    assert 'error' not in updates(runtime)[-1]


def test_missing_config_is_retryable_without_remux_or_disclosing_credentials(worker):
    service,runtime,job=worker;service.config.unlink();service.tick()
    assert updates(runtime)[-1]['error'] is True
    assert 'private-test-token' not in str(updates(runtime))
    assert {c.args[0] for c in runtime.rpc.call_args_list}=={'library-merge-refresh-pending','library-merge-refresh-update'}


def test_no_scan_is_requested_before_media_worker_reports_publication(worker):
    service,runtime,job=worker;runtime.rpc.return_value={'jobs':[]};service.tick()
    runtime.client.containers.get.assert_not_called()
    assert not updates(runtime)


def test_plex_new_file_scans_parent_folder_without_existing_rating_key(worker,monkeypatch):
    service,runtime,job=worker
    import merge_library_refresh as module
    session=Mock();session.headers={}
    session.get.side_effect=[SimpleNamespace(raise_for_status=lambda:None,
        content=b'<MediaContainer><Directory key="4" type="movie"><Location path="/media" /></Directory></MediaContainer>'),
        SimpleNamespace(raise_for_status=lambda:None,content=b'')]
    context=Mock();context.__enter__=Mock(return_value=session);context.__exit__=Mock(return_value=False)
    monkeypatch.setattr(module.requests,'Session',lambda:context)
    assert service.plex(json.loads(service.config.read_text()),job['relative']) is True
    call=session.get.call_args
    assert call.args[0]=='http://plex:32400/library/sections/4/refresh'
    assert call.kwargs['params']=={'path':'/media/Film'}
    assert session.trust_env is False and session.headers['X-Plex-Token']=='private-test-token'


def test_flix_request_uses_container_credential_without_exposing_it(worker):
    service,runtime,job=worker
    runtime.client.containers.get.return_value.exec_run.return_value=SimpleNamespace(exit_code=0,output=b'{"ok":true,"indexed":true}')
    assert service.flix({},job['relative']) is True
    args=runtime.client.containers.get.return_value.exec_run.call_args.args[0]
    assert args[-1]==job['relative'] and 'private-test-token' not in str(args)


def test_failed_refresh_retries_without_resolving_moved_sources(tmp_path,monkeypatch):
    ident='a'*32
    merge.save([{'id':ident,'owner':'alice','state':'error','phase':'refresh','refresh':{'fjordflix':True}}])
    monkeypatch.setattr(merge,'validate',Mock(side_effect=AssertionError('Original moved')))
    merge.dispatch(None,'retry',{'id':ident,'owner':'alice'})
    row=merge.read()[0]
    assert row['state']=='running' and row['phase']=='refresh' and row['refresh']=={'fjordflix':True}
    merge.dispatch(None,'refresh-update',{'id':ident,'refresh':{'fjordflix':True,'plex':True},'detail':'Done'})
    assert merge.read()[0]['state']=='done'


@pytest.mark.skipif(__import__('os').name=='nt', reason='Plex link library runs on Linux')
def test_plex_bridge_can_resolve_a_new_video_without_subtitle_files(tmp_path,monkeypatch):
    from tools import plex_subtitle_links as bridge
    source=tmp_path/'media';view=tmp_path/'view';source.mkdir();view.mkdir()
    video=source/'merged.mkv';video.write_bytes(b'film')
    linked=view/'Movie.mkv';linked.symlink_to(video)
    ledger=tmp_path/'links.json';ledger.write_text(json.dumps({'Movie.mkv':str(video)}))
    monkeypatch.setattr(bridge,'SOURCE',source);monkeypatch.setattr(bridge,'VIEW',view);monkeypatch.setattr(bridge,'LEDGER',ledger)
    assert bridge.ensure_links('merged.mkv',[])==str(linked)
    assert list(source.iterdir())==[video] and linked.resolve()==video
