"""Media-side RPCs. Paths are resolved from the retained library, never the client."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import conversion_workflow as workflow
import download_storage as storage
import library_conversion as library
from state import atomic
from subtitle_text import language, LANGUAGES, parse_srt, render_srt

TEXT = {'subrip','srt','ass','ssa','webvtt','mov_text','text'}


def candidates(api):
    return library.inventory(api)


def sidecars(path):
    result=[]
    for candidate in sorted(path.parent.iterdir()):
        if candidate.suffix.lower() not in ('.srt','.sup') or candidate.is_symlink() or not candidate.is_file(): continue
        stem=candidate.stem
        if stem!=path.stem and not stem.startswith(path.stem+'.'): continue
        tags=stem[len(path.stem):].strip('.').lower().split('.')
        lang=next((language(t) for t in tags if language(t) in LANGUAGES),'und')
        result.append({'id':'file:'+candidate.name,'language':lang,'codec':'srt' if candidate.suffix.lower()=='.srt' else 'hdmv_pgs_subtitle',
            'kind':'sidecar','label':candidate.name,'forced':'forced' in tags,'supported':True,
            'fingerprint':workflow.browser_fingerprint(library.fingerprint(candidate))})
    return result


def tracks(path, media):
    result=[]
    for stream in media.get('streams',[]):
        if stream.get('codec_type')!='subtitle': continue
        codec=stream.get('codec_name','unknown')
        result.append({'id':'stream:'+str(stream['index']),'language':language(stream.get('tags',{}).get('language')),
            'codec':codec,'kind':'embedded','label':stream.get('tags',{}).get('title',''),
            'forced':bool(stream.get('disposition',{}).get('forced')),'supported':codec in TEXT or codec=='hdmv_pgs_subtitle'})
    return result+sidecars(path)


def public(item, probe=False):
    path=Path(item['_path']); row=item.get('_row') or {}
    media=workflow.media_info(path) if probe else storage.read(storage.CONFIG/'conversion-media'/(item['id']+'.json'),{} )
    if not probe: media=media.get('media',{}) if media.get('fingerprint')==library.fingerprint(path) else {}
    sources=tracks(path,media)
    eligible=not item.get('job') and (not row or row.get('progress')==1 and row.get('state') in library.STABLE)
    stamp=workflow.browser_fingerprint(library.fingerprint(path))
    signature=hashlib.sha256(json.dumps([stamp,sources],sort_keys=True).encode()).hexdigest()
    supported=sorted((s for s in sources if s['supported']),key=lambda s:(s['forced'],s['language']!='en',s['codec']=='hdmv_pgs_subtitle',s['id']))
    return {'id':item['id'],'name':item['name'],'title':row.get('name') or path.stem,'size':item['size'],
        'eligible':eligible,'reason':'' if eligible else 'Vent til download eller konvertering er færdig.',
        'tracks':sources,'probed':bool(media),'fingerprint':stamp,'snapshot':signature,
        'preferred':supported[0]['id'] if supported else None}


def resolve(api, ident):
    item=next((i for i in candidates(api)['items'] if i['id']==ident),None)
    if not item: raise ValueError('Filmen findes ikke længere i biblioteket.')
    return item


def validate(api, data):
    item=resolve(api,data.get('id')); detail=public(item,True)
    if not detail['eligible']: raise ValueError(detail['reason'])
    if data.get('snapshot')!=detail['snapshot']: raise ValueError('Filmen eller underteksterne er ændret. Genåbn filmvalget.')
    source=next((s for s in detail['tracks'] if s['id']==data.get('source') and s['supported']),None)
    if not source: raise ValueError('Vælg et understøttet undertekstspor.')
    return item,detail,source


def extract(api,data):
    item,detail,source=validate(api,data); path=library.checked(Path(item['_path']))
    # Work outside /tmp: large PGS streams can exceed the container's tmpfs.
    directory=storage.CONFIG/'subtitle-work'; directory.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        if source['kind']=='sidecar': src=library.checked(path.parent/source['id'][5:])
        else:
            pgs=source['codec']=='hdmv_pgs_subtitle'; src=Path(temporary)/('source.sup' if pgs else 'source.srt')
            command=['ffmpeg','-nostdin','-v','error','-copyts','-i',str(path),'-map','0:'+source['id'][7:],
                     '-c:s','copy' if pgs else 'srt',str(src)]
            result=subprocess.run(command,capture_output=True,timeout=1800)
            if result.returncode: raise ValueError('Undertekstsporet kunne ikke udtrækkes.')
        if source['codec']=='hdmv_pgs_subtitle':
            from subtitle_pgs import read_pgs
            cues=read_pgs(src,source['language'])
        else:
            if src.stat().st_size>8*1024*1024: raise ValueError('SRT-filen er for stor.')
            raw=src.read_bytes()
            try: text=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('utf-8-sig')
            except UnicodeError: text=raw.decode('cp1252')
            cues=parse_srt(text)
        # Check source again after a potentially long extraction/OCR.
        validate(api,data)
        return {'cues':cues,'language':source['language'],'forced':source['forced']}


def publish(api,data):
    item=resolve(api,data.get('id')); path=library.checked(Path(item['_path']))
    if not workflow.fingerprint_matches(data.get('fingerprint'),library.fingerprint(path)):
        raise ValueError('Filmen er ændret. Underteksten er ikke gemt.')
    if not public(item)['eligible']: raise ValueError('Filmen behandles af et andet job. Prøv igen senere.')
    lang=data.get('language'); job=data.get('job')
    if lang not in LANGUAGES or not isinstance(job,str) or not __import__('re').fullmatch('[a-f0-9]{32}',job):
        raise ValueError('Ugyldigt undertekstjob.')
    text=data.get('text')
    if not isinstance(text,str): raise ValueError('Underteksten mangler.')
    parse_srt(text)
    suffix='.forced' if data.get('forced') is True else ''
    target=library.checked(path.with_name(path.stem+'.'+lang+suffix+'.srt'))
    digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
    receipt=storage.CONFIG/'subtitle-work'/(job+'-'+lang+'.json')
    receipt.parent.mkdir(parents=True,exist_ok=True)
    with storage.transaction():
        # Recheck after acquiring the same lock used to enqueue media changes.
        if not workflow.fingerprint_matches(data.get('fingerprint'),library.fingerprint(library.checked(path))):
            raise ValueError('Filmen er ændret. Underteksten er ikke gemt.')
        if not public(resolve(api,data.get('id')))['eligible']:
            raise ValueError('Filmen behandles af et andet job. Prøv igen senere.')
        saved=storage.read(receipt,{})
        if target.exists():
            if saved=={'path':str(target),'digest':digest} and hashlib.sha256(target.read_bytes()).hexdigest()==digest:
                return {'name':target.name}
            raise ValueError('En undertekst findes allerede. Ingen filer overskrives.')
        fd,temporary=tempfile.mkstemp(prefix='.fjordseed-subtitle-',dir=target.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as handle:
                handle.write(text); handle.flush(); os.fsync(handle.fileno())
            os.chmod(temporary,0o644)
            atomic(receipt,json.dumps({'path':str(target),'digest':digest}))
            os.link(temporary,target)  # atomic create-if-absent; never replace a sidecar
        finally: Path(temporary).unlink(missing_ok=True)
    return {'name':target.name}


def dispatch(api, action, data):
    if action=='list':
        result=candidates(api); return {'items':[public(i) for i in result['items']],'truncated':result['truncated']}
    if action=='details': return public(resolve(api,data.get('id')),True)
    if action=='validate':
        _,detail,source=validate(api,data)
        targets=data.get('targets')
        if not isinstance(targets,list) or not 1<=len(targets)<=len(LANGUAGES) or any(not isinstance(t,str) or t not in LANGUAGES for t in targets) or len(set(targets))!=len(targets):
            raise ValueError('Vælg ét eller flere forskellige målsprog.')
        existing={s['language'] for s in detail['tracks']}
        if any(t in existing for t in targets): raise ValueError('Et valgt sprog findes allerede. Opdater filmvalget.')
        return detail
    if action=='extract': return extract(api,data)
    if action=='publish': return publish(api,data)
    raise ValueError('Ukendt underteksthandling.')
