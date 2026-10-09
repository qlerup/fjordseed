"""Private tracker credentials and cached, read-only account statistics."""
import json
import math
import re
import threading
import time
import uuid

import requests

from state import atomic
from benefits import Benefits

PROVIDERS = {'nordicbytes': {'name':'NordicBytes', 'url':'https://nordicbytes.org/api/user'}}
STAT_FIELDS = ('uploaded','downloaded','ratio','buffer','seeding','leeching','seedbonus',
               'hit_and_runs','seeding_size','total_uploads')


class TrackerError(ValueError):
    pass


class Trackers:
    def __init__(self, root):
        self.path = root / 'trackers.json'
        self.lock = threading.RLock()
        self.cache = {}
        self.wake = threading.Event()
        self.benefits = Benefits(self)
        if not self.path.exists():
            atomic(self.path, '[]')
        self.path.chmod(0o600)

    def entries(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def badge_ready(self,ident):
        with self.lock:
            status=self.cache.get(ident,{})
            return (status.get('status')=='ok' and 0<=time.time()-status.get('updated_at',0)<600
                    and any(e['id']==ident and e['provider']=='nordicbytes' and e.get('api_key') for e in self.entries()))

    def public(self):
        with self.lock:
            return {'providers':[{'id':key,'name':value['name']} for key,value in PROVIDERS.items()],
                    'trackers':[{'id':entry['id'],'provider':entry['provider'],'name':entry['name'],
                                 'has_key':True, **self.cache.get(entry['id'], {'status':'pending'}),
                                 'badge_ready':self.badge_ready(entry['id'])}
                                for entry in self.entries()]}

    def save(self, data):
        if not isinstance(data, dict):
            raise ValueError('Ugyldig trackeropsætning.')
        provider = data.get('provider')
        name = data.get('name', '')
        key = data.get('api_key', '')
        ident = data.get('id', '')
        if (not isinstance(provider,str) or provider not in PROVIDERS or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                or not isinstance(key, str) or not isinstance(ident, str)):
            raise ValueError('Vælg en understøttet tracker og et navn.')
        key = key.strip()
        if key and not re.fullmatch(r'[A-Za-z0-9_-]{16,512}', key):
            raise ValueError('API-nøglen har et ugyldigt format.')
        with self.lock:
            entries = self.entries()
            existing = next((entry for entry in entries if entry['id'] == ident), None)
            if ident and existing is None:
                raise ValueError('Trackeren findes ikke længere.')
            if not existing and len(entries) >= 10:
                raise ValueError('Du kan tilføje op til 10 trackerkonti.')
            if not key:
                if not existing or existing['provider'] != provider:
                    raise ValueError('Indtast en API-nøgle.')
                key = existing['api_key']
            entry = {'id':ident or uuid.uuid4().hex,'provider':provider,'name':name.strip(),'api_key':key}
            changed = not existing or existing['api_key'] != key or existing['provider'] != provider
            entries = [entry if item['id'] == ident else item for item in entries] if existing else entries+[entry]
            atomic(self.path, json.dumps(entries))
            if changed:
                self.cache.pop(entry['id'], None)
            self.wake.set()
        return entry['id']

    def remove(self, ident):
        with self.lock:
            entries = self.entries()
            if not any(entry['id'] == ident for entry in entries):
                raise ValueError('Trackeren findes ikke længere.')
            atomic(self.path, json.dumps([entry for entry in entries if entry['id'] != ident]))
            self.cache.pop(ident, None)

    @staticmethod
    def read_json(entry, url, params=None):
        with requests.Session() as client:
            client.trust_env = False
            with client.get(url, params=params,
                    headers={'Authorization':'Bearer '+entry['api_key'], 'Accept':'application/json'},
                    timeout=(3,5), allow_redirects=False, stream=True) as response:
                if response.status_code in (401,403):
                    raise TrackerError('API-nøglen mangler adgang til kontodata. Kontrollér dens rettigheder.')
                if response.status_code == 429:
                    raise TrackerError('Trackeren begrænser API-kald. Prøver igen automatisk.')
                if response.status_code != 200:
                    raise TrackerError('Trackeren kunne ikke levere kontodata. Prøver igen automatisk.')
                raw = bytearray()
                for chunk in response.iter_content(8192):
                    raw.extend(chunk)
                    if len(raw) > 1024*1024:
                        raise TrackerError('Trackeren returnerede et for stort svar.')
                data = json.loads(raw)
        return data

    @staticmethod
    def fetch(entry):
        data = Trackers.read_json(entry, PROVIDERS[entry['provider']]['url'])
        if not isinstance(data,dict) or not isinstance(data.get('stats'),dict):
            raise TrackerError('Trackeren returnerede et ukendt dataformat.')
        stats = {}
        for field in STAT_FIELDS:
            value = data['stats'].get(field)
            stats[field] = value if type(value) in (int,float) and math.isfinite(value) else None
        warnings = data['stats'].get('warnings', {})
        if not isinstance(warnings,dict):
            warnings = {}
        stats['warnings'] = sum(v for k,v in warnings.items() if k in ('hnr','manual') and type(v) is int and v >= 0)
        events = data.get('events', {})
        events = events.get('global', []) if isinstance(events,dict) else []
        return {'username':str(data.get('username',''))[:80], 'stats':stats,
                'events':[{'title':str(event.get('title',''))[:200], 'ends_at':str(event.get('ends_at',''))[:40]}
                          for event in events[:20] if isinstance(event,dict)] if isinstance(events,list) else []}

    def refresh(self):
        with self.lock:
            entries = self.entries()
        for entry in entries:
            try:
                result = {**self.fetch(entry), 'status':'ok','error':None,'updated_at':time.time()}
            except Exception as exc:
                # Never expose remote response bodies, headers or exception URLs.
                result = {'status':'error', 'error':str(exc) if isinstance(exc,TrackerError)
                          else 'Trackeren er ikke tilgængelig. Prøver igen automatisk.'}
            with self.lock:
                if entry not in self.entries():
                    continue
                self.cache[entry['id']] = {**self.cache.get(entry['id'], {}), **result}

    def run(self, stop):
        while not stop.is_set():
            self.wake.clear()
            self.refresh()
            self.wake.wait(300)
