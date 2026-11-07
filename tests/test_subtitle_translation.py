import json
import struct
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import download_storage as storage
import library_conversion as library
import subtitle_media as media
from subtitle_auth import ChatGPT
from subtitle_pgs import read_pgs, rle
from subtitle_text import parse_srt, render_srt, translated
from subtitle_translation import Translations

SRT='1\r\n00:00:01,023 --> 00:00:02,947\r\n<i>Hello!</i>\r\n\r\n2\r\n00:00:02,500 --> 00:00:04,001\r\n- How are you?\r\n- Fine.\r\n'


def test_model_only_changes_text_preserves_overlapping_timing():
    cues=parse_srt(SRT)
    output=translated(cues,{'cues':[{'id':1,'text':'<i>Hej!</i>'},{'id':2,'text':'- Hvordan går det?\n- Godt.'}]})
    result=parse_srt(render_srt(output))
    assert [c['timing'] for c in result]==[c['timing'] for c in cues]
    assert result[1]['text']=='- Hvordan går det?\n- Godt.'


@pytest.mark.parametrize('rows',[[{'id':1,'text':'Hej'}],[{'id':2,'text':'Hej'},{'id':1,'text':'Hej'}],
    [{'id':1,'text':''},{'id':2,'text':'Hej'}],[{'id':True,'text':'Hej'},{'id':2,'text':'Hej'}]])
def test_reject_missing_reordered_empty_cues(rows):
    with pytest.raises(ValueError): translated(parse_srt(SRT),{'cues':rows})


def segment(kind,data,ms): return b'PG'+struct.pack('>IIBH',ms*90,0,kind,len(data))+data


def pgs_fixture():
    # One 2x1 glyph followed by an explicit clear; epoch, palette, object, END.
    pcs=struct.pack('>HHBHBBBB',1920,1080,0,0,0x80,0,0,1)+struct.pack('>HBBHH',0,0,0,100,900)
    ods=b'\x00\x00\x00\xc0'+(8).to_bytes(3,'big')+struct.pack('>HH',2,1)+b'\x01\x01\x00\x00'
    clear=struct.pack('>HHBHBBBB',1920,1080,0,1,0,0,0,0)
    return (segment(0x16,pcs,1234)+segment(0x14,b'\x00\x00\x01\xeb\x80\x80\xff',1234)
        +segment(0x15,ods,1234)+segment(0x80,b'',1234)+segment(0x16,clear,4567)+segment(0x80,b'',4567))


def test_pgs_ocr_retains_exact_presentation_times(tmp_path):
    path=tmp_path/'sample.sup'; path.write_bytes(pgs_fixture()); seen=[]
    def ocr(image,lang): seen.append((image.size,lang,image.getpixel((0,0)))); return 'Hello!'
    cues=read_pgs(path,'en',ocr)
    assert seen==[((2,1),'en',20)]
    assert cues==[{'id':1,'timing':'00:00:01,234 --> 00:00:04,567','text':'Hello!'}]


def test_pgs_rejects_missing_end_and_broken_rle(tmp_path):
    path=tmp_path/'sample.sup'; path.write_bytes(pgs_fixture()[:-37])
    with pytest.raises(ValueError): read_pgs(path,'en',lambda *_:'Hello')
    with pytest.raises(ValueError): rle(b'\x00\x83\x01',2,1)


@pytest.fixture
def film(tmp_path,monkeypatch):
    root=tmp_path/'downloads'; root.mkdir(); path=root/'Movie.mkv'; path.write_bytes(b'video')
    (root/'Movie.en.srt').write_bytes(SRT.encode('utf-8'))
    (root/'Movie2.da.srt').write_bytes(SRT.encode('utf-8'))
    item={'id':library.key(path),'name':path.name,'_path':str(path),'_row':None,'size':5,'job':None}
    monkeypatch.setattr(media,'candidates',lambda _: {'items':[item],'truncated':False})
    monkeypatch.setattr(media.workflow,'media_info',lambda _: {'streams':[{'index':2,'codec_type':'subtitle',
        'codec_name':'hdmv_pgs_subtitle','tags':{'language':'dan'},'disposition':{}}]})
    return path,item


def test_inventory_includes_internal_pgs_external_srt_and_prefers_english(film):
    path,item=film; detail=media.public(item,True)
    assert [(s['language'],s['codec']) for s in detail['tracks']]==[('da','hdmv_pgs_subtitle'),('en','srt')]
    assert detail['preferred']=='file:Movie.en.srt'
    assert detail['eligible']


def test_extract_snapshot_and_target_validation(film):
    path,item=film; detail=media.public(item,True)
    choice={'id':item['id'],'snapshot':detail['snapshot'],'source':detail['preferred'],'targets':['sv','de']}
    assert media.dispatch(None,'validate',choice)['id']==item['id']
    assert media.extract(None,choice)['cues']==parse_srt(SRT)
    with pytest.raises(ValueError,match='allerede'): media.dispatch(None,'validate',{**choice,'targets':['da']})
    path.with_suffix('.en.srt').write_text(SRT+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='ændret'): media.extract(None,choice)


def test_publish_idempotent_without_overwriting_and_movie_unchanged(film):
    path,item=film; detail=media.public(item,True)
    data={'id':item['id'],'fingerprint':detail['fingerprint'],'language':'sv','job':'a'*32,'text':render_srt(parse_srt(SRT))}
    assert media.publish(None,data)=={'name':'Movie.sv.srt','relative':'Movie.mkv'}
    assert media.publish(None,data)=={'name':'Movie.sv.srt','relative':'Movie.mkv'}
    with pytest.raises(ValueError,match='allerede'): media.publish(None,{**data,'job':'b'*32})
    assert path.read_bytes()==b'video'
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='ændret'): media.publish(None,{**data,'language':'de'})


def test_oauth_state_nonce_client_scopes_and_user_isolation(tmp_path,monkeypatch):
    auth=ChatGPT(tmp_path); pair=auth.begin('alice')['pair']; prepared=auth.prepare(pair,'http://127.0.0.1:54321/auth/callback')
    assert 'code_challenge_method=S256' in prepared['url']
    assert 'dynamic_agent_client' in prepared['url']
    with pytest.raises(ValueError): auth.complete(pair,{'state':'wrong','client_id':'oaiapp_a','code':'code'})
    verify=Mock(return_value={'sub':'subject','email':'alice@example.test'})
    monkeypatch.setattr(auth,'verify',verify)
    monkeypatch.setattr(auth,'token_request',lambda _: {'access_token':'access','refresh_token':'refresh','id_token':'identity','scope':'openid chatgpt.tokens.use.direct','token_type':'Bearer'})
    auth.complete(pair,{'state':prepared['state'],'client_id':'oaiapp_a','code':'code'})
    assert verify.call_args.args[1]=='oaiapp_a' and verify.call_args.args[2]
    assert auth.status('alice')['enabled'] and not auth.status('bob')['connected']
    assert 'access' not in json.dumps(auth.status('alice'))
    with pytest.raises(ValueError): auth.complete(pair,{'state':prepared['state'],'client_id':'oaiapp_a','code':'code'})
    pair=auth.begin('alice','oaiapp_a')['pair']; prepared=auth.prepare(pair,'http://127.0.0.1:54321/auth/callback')
    assert 'dynamic_agent_client' not in prepared['url']
    with pytest.raises(ValueError,match='matcher'): auth.complete(pair,{'state':prepared['state'],'client_id':'oaiapp_b','code':'code'})


def test_oauth_declined_plan_access_cannot_infer(tmp_path,monkeypatch):
    auth=ChatGPT(tmp_path); pair=auth.begin('alice')['pair']; prepared=auth.prepare(pair,'http://127.0.0.1:54321/auth/callback')
    monkeypatch.setattr(auth,'verify',lambda *_:{'sub':'subject'})
    monkeypatch.setattr(auth,'token_request',lambda _: {'access_token':'access','id_token':'identity','scope':'openid','token_type':'Bearer'})
    auth.complete(pair,{'state':prepared['state'],'client_id':'oaiapp_a','code':'code'})
    assert auth.status('alice')['connected'] and not auth.status('alice')['enabled']
    with pytest.raises(ValueError,match='abonnement'): auth.bearer('alice','oaiapp_a')


def test_resume_only_missing_batches_and_other_user_cannot_cancel(tmp_path,monkeypatch):
    calls=[]; published=[]; extracted=parse_srt(SRT)
    def rpc(action,data):
        if action.endswith('validate'): return {'id':data['id'],'title':'Film','snapshot':'stamp','fingerprint':['5','1']}
        if action.endswith('extract'): return {'cues':extracted,'language':'en','forced':False}
        if action.endswith('publish'): published.append(data); return {'name':'Film.'+data['language']+'.srt'}
    manager=Translations(SimpleNamespace(root=tmp_path),SimpleNamespace(rpc=rpc))
    monkeypatch.setattr(manager.auth,'models',lambda *_:[{'id':'test-model'}])
    def translate(owner,account,model,lang,batch):
        calls.append(lang)
        if lang=='de' and calls.count('de')==1: raise ValueError('Temporary failure')
        return [{**c,'text':lang+' text'} for c in batch]
    monkeypatch.setattr(manager.auth,'translate',translate)
    data={'account':'test-account','model':'test-model','items':[{'id':'film','snapshot':'stamp','source':'stream:2','targets':['sv','de']}]}
    manager.enqueue('alice',data); job=manager.listing('alice')[0]['job']
    assert manager.listing('bob')==[]
    with pytest.raises(ValueError): manager.change('bob',job,'cancel')
    manager.run_once(); assert manager.listing('alice')[0]['state']=='error'
    manager.change('alice',job,'retry'); manager.run_once()
    assert manager.listing('alice')[0]['state']=='done'
    assert calls==['sv','de','de']
    assert all([c['timing'] for c in parse_srt(p['text'])]==[c['timing'] for c in extracted] for p in published)


def test_routes_require_auth_csrf_and_pairing_bearer(tmp_path):
    from app import create_app
    from test_app import FakeRuntime,login
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime); client=app.test_client()
    assert client.get('/api/subtitles/jobs').status_code==401
    assert client.post('/api/subtitles/auth/prepare',json={'redirect_uri':'http://127.0.0.1:54321/auth/callback'}).status_code==400
    client,headers=login(app)
    assert client.post('/api/subtitles/auth/begin',json={}).status_code==403
    pair=client.post('/api/subtitles/auth/begin',json={},headers=headers).json['pair']
    assert client.post('/api/subtitles/auth/prepare',json={'redirect_uri':'http://evil.test/callback'},headers={'Authorization':'Bearer '+pair}).status_code==400
    assert client.post('/api/subtitles/auth/prepare',json={'redirect_uri':'http://127.0.0.1:54321/auth/callback'},headers={'Authorization':'Bearer '+pair}).status_code==200


@pytest.mark.parametrize('ending',['response.completed','response.incomplete','response.failed',None])
def test_stream_requires_completed_event_before_accepting_text(tmp_path,monkeypatch,ending):
    import subtitle_auth
    auth=ChatGPT(tmp_path); monkeypatch.setattr(auth,'bearer',lambda *_:'test-token')
    reply=json.dumps({'cues':[{'id':c['id'],'text':'Oversat'} for c in parse_srt(SRT)]})
    events=[{'type':'response.output_text.delta','delta':reply}]
    if ending: events.append({'type':ending})
    response=Mock(status_code=200); response.iter_lines.return_value=[b'data: '+json.dumps(e).encode() for e in events]
    context=Mock(); context.__enter__=Mock(return_value=response); context.__exit__=Mock(return_value=False)
    post=Mock(return_value=context); monkeypatch.setattr(subtitle_auth.requests,'post',post)
    if ending=='response.completed': assert len(auth.translate('alice','account','model','da',parse_srt(SRT)))==2
    else:
        with pytest.raises(ValueError): auth.translate('alice','account','model','da',parse_srt(SRT))
    payload=post.call_args.kwargs['json']
    assert payload['store'] is False and payload['stream'] is True
    assert '00:00:' not in json.dumps(payload)


def test_real_jwt_validation_rejects_wrong_nonce_issuer_and_audience(monkeypatch):
    import jwt,time
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    monkeypatch.setattr(jwt,'PyJWKClient',lambda *_args,**_kwargs:SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=key.public_key())))
    payload={'sub':'subject','iss':'https://auth.openai.com','aud':'oaiapp_a','exp':time.time()+300,'iat':time.time(),'nonce':'expected'}
    token=lambda p:jwt.encode(p,key,algorithm='RS256')
    assert ChatGPT.verify(token(payload),'oaiapp_a','expected')['sub']=='subject'
    for change in ({'nonce':'wrong'},{'iss':'https://evil.test'},{'aud':'oaiapp_b'},{'exp':1}):
        with pytest.raises(ValueError): ChatGPT.verify(token({**payload,**change}),'oaiapp_a','expected')


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg integration requires ffmpeg and ffprobe')
@pytest.mark.parametrize('pgs',[False,True])
def test_actual_mkv_extraction_preserves_srt_and_pgs_timestamps(tmp_path,monkeypatch,pgs):
    root=tmp_path/'downloads';root.mkdir();path=root/'Movie.mkv'
    original=tmp_path/('input.sup' if pgs else 'input.srt');original.write_bytes(pgs_fixture() if pgs else SRT.encode())
    subprocess.run(['ffmpeg','-nostdin','-v','error','-copyts','-f','lavfi','-i','color=size=32x32:rate=1:duration=5',
        '-i',str(original),'-map','0:v','-map','1:s','-c:v','ffv1','-c:s','copy','-metadata:s:s:0','language=eng',str(path)],check=True,timeout=30)
    item={'id':library.key(path),'name':path.name,'_path':str(path),'_row':None,'size':path.stat().st_size,'job':None}
    monkeypatch.setattr(media,'candidates',lambda _:{'items':[item],'truncated':False})
    if pgs:
        import subtitle_pgs
        decode=subtitle_pgs.read_pgs
        monkeypatch.setattr(subtitle_pgs,'read_pgs',lambda path,lang:decode(path,lang,lambda *_:'Hello!'))
    detail=media.public(item,True)
    result=media.extract(None,{'id':item['id'],'snapshot':detail['snapshot'],'source':detail['preferred']})
    expected=['00:00:01,234 --> 00:00:04,567'] if pgs else [c['timing'] for c in parse_srt(SRT)]
    assert [c['timing'] for c in result['cues']]==expected


@pytest.mark.skipif(not shutil.which('tesseract'),reason='Real OCR integration requires Tesseract with eng data')
def test_real_pgs_ocr_reads_rendered_text(tmp_path):
    from PIL import Image,ImageDraw,ImageFont
    from subtitle_pgs import recognize
    glyph=Image.new('L',(300,55),0)
    ImageDraw.Draw(glyph).text((4,3),'Hello world',font=ImageFont.load_default(size=38),fill=255)
    encoded=bytearray()
    for y in range(glyph.height):
        for x in range(glyph.width): encoded.extend(b'\x01' if glyph.getpixel((x,y))>128 else b'\x00\x01')
        encoded.extend(b'\x00\x00')
    pcs=struct.pack('>HHBHBBBB',1920,1080,0,0,0x80,0,0,1)+struct.pack('>HBBHH',0,0,0,100,900)
    ods=b'\x00\x00\x00\xc0'+(len(encoded)+4).to_bytes(3,'big')+struct.pack('>HH',300,55)+encoded
    clear=struct.pack('>HHBHBBBB',1920,1080,0,1,0,0,0,0)
    raw=(segment(0x16,pcs,1234)+segment(0x14,b'\x00\x00\x01\xeb\x80\x80\xff',1234)+segment(0x15,ods,1234)
        +segment(0x80,b'',1234)+segment(0x16,clear,4567)+segment(0x80,b'',4567))
    path=tmp_path/'real.sup';path.write_bytes(raw)
    cues=read_pgs(path,'en')
    assert cues[0]['text']=='Hello world'
    assert cues[0]['timing']=='00:00:01,234 --> 00:00:04,567'
