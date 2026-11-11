"""Refresh published remuxes from the web container, outside the VPN worker."""
import json
from pathlib import PurePosixPath
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import requests


FLIX_REFRESH = r'''
import http.client,json,os,sys
key=os.environ.get('FJORDHUB_API_KEY','')
if not key:raise SystemExit(1)
client=http.client.HTTPConnection('127.0.0.1',8080,timeout=15)
client.request('POST','/api/hub/seed-library/refresh',body=json.dumps({'relative':sys.argv[1]}),
               headers={'X-Hub-Key':key,'Content-Type':'application/json'})
r=client.getresponse();body=r.read(65537)
if r.status!=200 or len(body)>65536:raise SystemExit(1)
print(json.dumps(json.loads(body)))
'''


class LibraryRefresh:
    def __init__(self, runtime, rpc_prefix="library-merge"):
        self.rpc_prefix = rpc_prefix
        self.runtime = runtime
        self.config = runtime.state.root/'subtitle-library.json'
        self.next_at = {}

    def flix(self, config, relative):
        result = self.runtime.client.containers.get(config.get('fjordflix_container','fjordflix')).exec_run(
            ['python','-c',FLIX_REFRESH,relative])
        if result.exit_code:
            raise ValueError('FjordFlix kunne ikke starte scanningen. Kontrollér forbindelsen og opdatér FjordFlix.')
        try: data = json.loads(result.output)
        except (ValueError,TypeError): raise ValueError('FjordFlix returnerede en ukendt scanningsstatus.') from None
        if data.get('ok') is not True: raise ValueError('FjordFlix kunne ikke bekræfte scanningen.')
        return data.get('indexed') is True

    def plex(self, config, relative):
        path = str(PurePosixPath(config['plex_root'])/relative)
        with requests.Session() as session:
            session.trust_env = False
            if config.get('plex_link_url'):
                # The existing bridge resolves the link after its regular sync has
                # picked up FjordFlix's new index entry. It never fabricates a path.
                response = session.post(config['plex_link_url'], json={'relative':relative,'outputs':[]},
                    headers={'Authorization':'Bearer '+config['plex_link_secret']},
                    timeout=(5,20), allow_redirects=False)
                if response.status_code==409: return False
                response.raise_for_status()
                data = response.json(); path = data.get('path','')
                view = PurePosixPath(config['plex_view_root'])
                if (data.get('ok') is not True or not PurePosixPath(path).is_relative_to(view)
                        or '..' in PurePosixPath(path).parts or not PurePosixPath(path).suffix):
                    raise ValueError('Plex-linkets placering kunne ikke bekræftes.')
            session.headers['X-Plex-Token'] = config['plex_token']
            base = config['plex_url'].rstrip('/')
            def get(endpoint, **params):
                response = session.get(base+endpoint, params=params, timeout=(5,20), allow_redirects=False)
                response.raise_for_status()
                return ET.fromstring(response.content)
            sections = get('/library/sections')
            keys = []
            for section in sections.findall('Directory'):
                if section.get('type') not in ('movie','show') or not section.get('key','').isdigit(): continue
                if any(path.startswith(loc.get('path','').rstrip('/')+'/') for loc in section.findall('Location')):
                    keys.append(section.get('key'))
            if len(keys)!=1: raise ValueError('Den nye fil matcher ikke ét entydigt Plex-bibliotek.')
            # Scan the parent folder: a new filename is not an existing metadata item.
            response = session.get(base+'/library/sections/'+keys[0]+'/refresh',
                params={'path':str(PurePosixPath(path).parent)}, timeout=(5,20), allow_redirects=False)
            response.raise_for_status()
            return True

    def tick(self):
        jobs = self.runtime.rpc(self.rpc_prefix+'-refresh-pending', {}).get('jobs', [])
        for job in jobs[:10]:
            ident = job['id']
            if time.time() < self.next_at.get(ident, 0): continue
            self.next_at[ident] = time.time()+30
            status = dict(job.get('refresh') or {})
            try:
                relative = job['relative']; path = PurePosixPath(relative)
                if path.is_absolute() or '..' in path.parts or not path.name: raise ValueError('Ugyldig bibliotekssti.')
                if not self.config.exists():
                    raise ValueError('Automatisk Plex/FjordFlix-opdatering er ikke konfigureret.')
                config = json.loads(self.config.read_text(encoding='utf-8'))
                for key in ('plex_url',):
                    if urlsplit(config[key]).scheme not in ('http','https'): raise ValueError('Ugyldig Plex-forbindelse.')
                if not status.get('fjordflix'):
                    if not self.flix(config, relative):
                        self.record(job, status, 'FjordFlix scanner den nye film'); continue
                    status['fjordflix'] = True
                    self.record(job, status, 'FjordFlix er opdateret · venter på Plex')
                if not status.get('plex'):
                    if not self.plex(config, relative):
                        self.record(job, status, 'Afventer linket til den nye film i Plex'); continue
                    status['plex'] = True
                self.record(job, status, 'Færdig · FjordFlix er opdateret, og Plex-scanning er startet')
            except Exception:
                # Credentials and HTTP request URLs must not appear in job errors.
                self.runtime.rpc(self.rpc_prefix+'-refresh-update', {'id':ident,'refresh':status,
                    'error':True,'detail':'Filen er gemt · biblioteksopdateringen fejlede. Kontrollér Plex/FjordFlix-forbindelsen og prøv igen.'})

    def record(self, job, status, detail):
        if not all(status.get(k) for k in ('fjordflix','plex')) and time.time()-job['started_at']>1800:
            raise ValueError('Biblioteket kunne ikke registrere filmen inden for 30 minutter.')
        self.runtime.rpc(self.rpc_prefix+'-refresh-update', {'id':job['id'],'refresh':status,'detail':detail})
