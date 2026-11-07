"""Durable, per-user translation queue; one film at a time, resumable batches."""
import hashlib
import json
import logging
import threading
import time
import uuid
from pathlib import Path

from flask import jsonify, request, send_file, session
from state import atomic
from subtitle_device_auth import ChatGPT
from subtitle_text import LANGUAGES, render_srt
from subtitle_progress import present, summary
from subtitle_library_refresh import LibraryRefresh

LOG=logging.getLogger(__name__)


class Translations:
    def __init__(self, state, runtime):
        self.root=state.root/'subtitle-translations'; self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.path=self.root/'jobs.json'; self.lock=threading.RLock(); self.runtime=runtime
        self.auth=ChatGPT(state.root)
        self.library_refresh=LibraryRefresh(state.root)
        with self.lock:
            jobs=self.read()
            for job in jobs:
                if job['state']=='running': job.update(state='error',detail='Serveren blev genstartet. Fortsæt for at genoptage gemte blokke.')
            self.save(jobs)

    def read(self): return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else []
    def save(self,jobs): atomic(self.path,json.dumps(jobs,ensure_ascii=False))
    def rpc(self,action,data): return self.runtime.rpc('library-subtitle-'+action,data)

    def listing(self,owner):
        with self.lock:
            rows=[j for j in self.read() if j['owner']==owner]
            rows=[j for j in rows if j['state'] not in ('done','cancelled')]+[j for j in rows if j['state'] in ('done','cancelled')][-30:]
            return [{k:j.get(k) for k in ('job','title','state','detail','progress','stage','stage_progress','elapsed_seconds','targets','outputs','created_at','batch','refresh')}
                    for j in [present(row,self.root.parent/'qbit') for row in rows]]

    def summary(self,owner):
        with self.lock:
            return summary([present(j,self.root.parent/'qbit') for j in self.read() if j['owner']==owner])

    def enqueue(self,owner,data):
        choices=data.get('items'); account=data.get('account'); model=data.get('model')
        if not isinstance(account,str) or not isinstance(model,str): raise ValueError('Vælg en ChatGPT-konto og model.')
        if not isinstance(choices,list) or not 1<=len(choices)<=100: raise ValueError('Vælg mellem 1 og 100 film.')
        if model not in {m['id'] for m in self.auth.models(owner,account)}: raise ValueError('Vælg en model fra din ChatGPT-konto.')
        prepared=[]; batch_id=uuid.uuid4().hex
        for choice in choices:
            if not isinstance(choice,dict): raise ValueError('Ugyldigt filmvalg.')
            detail=self.rpc('validate',choice)
            prepared.append({'job':uuid.uuid4().hex,'owner':owner,'account':account,'model':model,
                'id':detail['id'],'title':detail['title'],'snapshot':detail['snapshot'],'fingerprint':detail['fingerprint'],
                'source':choice['source'],'targets':choice['targets'],'state':'queued','detail':'Venter på oversættelse',
                'created_at':time.time(),'progress':0,'stage':'queued','batch':batch_id,'outputs':[]})
        with self.lock:
            jobs=self.read(); active=[j for j in jobs if j['state'] not in ('done','cancelled')]
            if len(active)+len(prepared)>500: raise ValueError('Køen er fuld (maks. 500 film).')
            # Cross-user deduplication prevents simultaneous writes to the same film.
            seen={j['id'] for j in active}
            for job in prepared:
                if job['id'] in seen: raise ValueError('En valgt film er allerede i kø.')
                seen.add(job['id'])
            jobs.extend(prepared); self.save(jobs)
        return {'ok':True}

    def change(self,owner,ident,action):
        with self.lock:
            jobs=self.read(); job=next((j for j in jobs if j['job']==ident and j['owner']==owner),None)
            if not job: raise ValueError('Oversættelsen findes ikke.')
            if action=='retry' and job['state']=='error': job.update(state='queued',detail='Genoptager gemte blokke')
            elif action=='cancel' and job['state'] in ('queued','error','running'):
                job.update(state='cancelled',finished_at=time.time(),detail='Annulleret. Allerede gemte undertekstfiler bevares.')
            else: raise ValueError('Handlingen er ikke mulig for dette job.')
            self.save(jobs)
        return {'ok':True}

    def update(self,ident,**fields):
        with self.lock:
            jobs=self.read(); job=next(j for j in jobs if j['job']==ident)
            if job['state']=='cancelled': return False
            if fields.get('state') in ('done','error','cancelled'): fields.setdefault('finished_at',time.time())
            job.update(fields); self.save(jobs); return True

    def active(self,ident):
        with self.lock: return next(j for j in self.read() if j['job']==ident)['state']=='running'

    @staticmethod
    def batches(cues):
        batch=[]; size=0
        for cue in cues:
            if batch and (len(batch)>=40 or size+len(cue['text'])>10000):
                yield batch; batch=[]; size=0
            batch.append(cue); size+=len(cue['text'])
        if batch: yield batch

    def process(self,job):
        folder=self.root/job['job']; folder.mkdir(mode=0o700,exist_ok=True)
        source=folder/'source.json'
        attempt=uuid.uuid4().hex
        if not self.update(job['job'],state='running',stage='extract',stage_progress=None,progress_id=attempt,
                started_at=time.time(),finished_at=None,detail='Udtrækker undertekst'): return
        if not source.exists():
            extracted=self.rpc('extract',{**job,'progress_id':attempt})
            atomic(source,json.dumps(extracted,ensure_ascii=False))
        extracted=json.loads(source.read_text(encoding='utf-8'))
        batches=list(self.batches(extracted['cues'])); total=len(batches)*len(job['targets']); count=0
        self.update(job['job'],stage='translate',stage_progress=0,progress=35)
        outputs=list(job['outputs'])
        for target in job['targets']:
            translated=[]
            for index,batch in enumerate(batches):
                if not self.active(job['job']): return
                checkpoint=folder/f'{target}-{index}.json'
                if checkpoint.exists(): result=json.loads(checkpoint.read_text(encoding='utf-8'))
                else:
                    self.update(job['job'],stage='translate',detail=f'Oversætter til {LANGUAGES[target]} · blok {index+1} af {len(batches)}')
                    result=self.auth.translate(job['owner'],job['account'],job['model'],target,batch)
                    atomic(checkpoint,json.dumps(result,ensure_ascii=False))
                translated.extend(result); count+=1
                self.update(job['job'],stage_progress=count/total,progress=35+round(count/total*55))
            text=render_srt(translated)
            with self.lock:
                # Cancellation and publication are serialized. Completed languages
                # survive retries, and publication RPCs are idempotent by job ID.
                if not self.active(job['job']): return
                self.update(job['job'],stage='save',stage_progress=None,detail='Gemmer SRT ved filmen')
                result=self.rpc('publish',{**job,'language':target,'forced':extracted['forced'],'text':text})
                if result['name'] not in outputs: outputs.append(result['name'])
                self.update(job['job'],outputs=outputs,detail='Gemt: '+result['name'])
        if result.get('relative'):
            self.update(job['job'],stage='refresh',stage_progress=None,progress=95,detail='Opdaterer Plex og Fjordflix')
            refreshed=self.library_refresh.refresh(result['relative'],outputs,job['targets'],
                lambda detail:self.update(job['job'],detail=detail))
            if not self.active(job['job']): return
            self.update(job['job'],refresh=refreshed)
        self.update(job['job'],state='done',stage='done',stage_progress=1,progress=100,detail='Færdig · underteksterne ligger ved filmen')

    def run_once(self):
        with self.lock:
            jobs=self.read()
            # A failed film does not block unrelated films or another user's queue.
            job=next((j for j in jobs if j['state']=='queued'),None)
        if job:
            try: self.process(job)
            except ValueError as exc: self.update(job['job'],state='error',detail=str(exc))
            except Exception:
                LOG.error('Subtitle translation failed for job %s',job['job'])
                self.update(job['job'],state='error',detail='Oversættelsen blev afbrudt. Gemte blokke kan genoptages.')

    def run(self,stop):
        while not stop.wait(2): self.run_once()


def register(app,state,runtime,stop,testing=False):
    manager=Translations(state,runtime); app.extensions['subtitles']=manager
    def owner(): return 'hub:'+str(session['hub_uid']) if 'hub_uid' in session else 'local'
    def body():
        data=request.get_json(silent=True)
        if not isinstance(data,dict): raise ValueError('Forventede et JSON-objekt.')
        return data
    def response(fn):
        try: return jsonify(fn())
        except ValueError as exc: return jsonify(error=str(exc)),400
    def pair(): return request.headers.get('Authorization','').removeprefix('Bearer ')

    @app.get('/api/subtitles/library')
    def subtitle_library(): return response(lambda:manager.rpc('list',{}))

    @app.get('/api/subtitles/library/<ident>')
    def subtitle_details(ident): return response(lambda:manager.rpc('details',{'id':ident}))

    @app.get('/api/subtitles/jobs')
    def subtitle_jobs(): return jsonify(jobs=manager.listing(owner()),summary=manager.summary(owner()),languages=LANGUAGES,auth=manager.auth.status(owner()))

    @app.post('/api/subtitles/queue')
    def subtitle_queue(): return response(lambda:manager.enqueue(owner(),body()))

    @app.post('/api/subtitles/jobs/<ident>/<action>')
    def subtitle_job_action(ident,action): return response(lambda:manager.change(owner(),ident,action))

    @app.get('/api/subtitles/models')
    def subtitle_models(): return response(lambda:{'models':manager.auth.models(owner(),request.args.get('account'))})

    @app.post('/api/subtitles/auth/begin')
    def subtitle_auth_begin(): return response(lambda:manager.auth.begin(owner(),body().get('account')))

    @app.post('/api/subtitles/auth/device')
    def subtitle_auth_device(): return response(lambda:manager.auth.device_begin(owner(),body().get('account')))

    @app.post('/api/subtitles/auth/cancel')
    def subtitle_auth_cancel(): return response(lambda:manager.auth.device_cancel(owner()))

    @app.post('/api/subtitles/auth/prepare')
    def subtitle_auth_prepare(): return response(lambda:manager.auth.prepare(pair(),body().get('redirect_uri')))

    @app.post('/api/subtitles/auth/complete')
    def subtitle_auth_complete(): return response(lambda:manager.auth.complete(pair(),body()))

    @app.post('/api/subtitles/auth/select')
    def subtitle_auth_select(): return response(lambda:manager.auth.select(owner(),body().get('account')))

    @app.post('/api/subtitles/auth/disconnect')
    def subtitle_auth_disconnect(): return response(lambda:manager.auth.disconnect(owner()))

    @app.get('/api/subtitles/login-helper')
    def subtitle_login_helper(): return send_file(Path(__file__).parent/'tools'/'chatgpt_login.py',as_attachment=True,download_name='fjordseed-chatgpt-login.py')

    if not testing: threading.Thread(target=manager.run,args=(stop,),name='subtitle-translations',daemon=True).start()
