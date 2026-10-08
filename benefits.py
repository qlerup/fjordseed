"""Bounded asynchronous tracker lookups with exact hash verification."""
import hashlib
import itertools
import queue
import re
import threading
import time


class Benefits:
    def __init__(self, trackers):
        self.trackers=trackers
        self.lock=threading.RLock()
        self.cache={}
        self.jobs=queue.PriorityQueue(maxsize=200)
        self.sequence=itertools.count()
        self.stop=None
        self.last_request=0

    def request(self, meta, selected='', priority=0):
        hashes=tuple(sorted({h.lower() for h in meta.get('hashes',[]) if isinstance(h,str) and re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}',h)}))
        if not hashes:
            return {'status':'unknown','message':'Trackerfordele ukendte — ingen info-hash.'}
        name=str(meta.get('name',''))[:200]
        with self.trackers.lock:
            entries=[e for e in self.trackers.entries() if not selected or e['id']==selected]
        if not entries:
            return {'status':'unknown','message':'Tilføj en tracker under Trackere for at se fordelene.'}
        signature=tuple((e['id'],e['name'],hashlib.sha256(e['api_key'].encode()).hexdigest()) for e in entries)
        key=(hashes,name,signature)
        with self.lock:
            cached=self.cache.get(key)
            promote=cached and cached['result']['status']=='pending' and priority<cached['priority']
            if cached and not promote and (cached['result']['status']=='pending' or time.time()-cached['at']<300):
                return cached['result']
            result={'status':'pending','message':'Slår trackerfordele op…'}
            if priority>0 and self.jobs.qsize()>=150:
                return result
            try:
                self.jobs.put_nowait((priority,next(self.sequence),key,hashes,name,entries))
            except queue.Full:
                return {'status':'unknown','message':'Trackerfordele ukendte — flere opslag afventer.'}
            if len(self.cache)>=1000:
                oldest=next((k for k,v in self.cache.items() if v['result']['status']!='pending'),None)
                if oldest is not None:
                    del self.cache[oldest]
            self.cache[key]={'at':time.time(),'result':result,'priority':priority}
            return result

    @staticmethod
    def flags(attributes):
        free=attributes.get('freeleech')
        try:
            free=float(str(free).rstrip('%'))
        except (TypeError,ValueError):
            free=None
        if free not in (0,25,50,75,100):
            free=None
        featured=attributes.get('featured') is True
        return {'freeleech':100 if featured else free,
                'double_upload':True if featured else attributes.get('double_upload') if type(attributes.get('double_upload')) is bool else None,
                'featured':featured,'internal':attributes.get('internal') is True,
                'refundable':attributes.get('refundable') is True}

    def lookup(self, hashes, name, entries):
        if not name:
            return {'status':'unknown','message':'Trackerfordele ukendte — navnet kan slås op, når torrentens metadata er hentet.'}
        matches=[]
        failed=False
        candidates=list(dict.fromkeys([name,re.sub(r'[._]+',' ',name).strip()]))
        for entry in entries:
            match=None
            try:
                for candidate in candidates:
                    cursor=None
                    for _ in range(3):
                        params={'name':candidate,'perPage':50}
                        if cursor:
                            params['cursor']=cursor
                        if self.stop is not None:
                            # Rate-limit actual HTTP requests, including pagination.
                            if self.stop.wait(max(0,1-(time.monotonic()-self.last_request))):
                                raise RuntimeError('Stopping')
                            self.last_request=time.monotonic()
                        data=self.trackers.read_json(entry,'https://nordicbytes.org/api/torrents/filter',params)
                        rows=data.get('data',[]) if isinstance(data,dict) else []
                        if not isinstance(rows,list):
                            raise ValueError('Unknown tracker response')
                        for row in rows[:50]:
                            a=row.get('attributes',{}) if isinstance(row,dict) else {}
                            if not isinstance(a,dict):
                                continue
                            ident=a.get('info_hash','')
                            if isinstance(ident,str) and ident.lower() in hashes:
                                match={'tracker_id':entry['id'],'tracker_name':entry['name'],**self.flags(a)}
                                break
                        metadata=data.get('meta',{}) if isinstance(data,dict) else {}
                        cursor=metadata.get('next_cursor') if isinstance(metadata,dict) else None
                        if match or not isinstance(cursor,str) or not cursor or len(cursor)>1024:
                            break
                    if match:
                        break
            except Exception:
                failed=True
            if match:
                matches.append(match)
        return {'status':'matched' if matches else 'unavailable' if failed else 'unknown',
                'matches':matches,'checked_at':time.time(),
                'message':'Trackerfordele fundet.' if matches else 'Trackerfordele ukendte — trackeren kunne ikke kontaktes.' if failed
                          else 'Trackerfordele ukendte — ingen torrent med samme info-hash fundet.'}

    def run(self, stop):
        self.stop=stop
        while not stop.is_set():
            try:
                priority,_,key,hashes,name,entries=self.jobs.get(timeout=1)
            except queue.Empty:
                continue
            with self.trackers.lock:
                still_current=all(e in self.trackers.entries() for e in entries)
            with self.lock:
                cached=self.cache.get(key)
                finished=cached and cached['result']['status']!='pending' and time.time()-cached['at']<300
            if not still_current or finished:
                if not still_current:
                    with self.lock:
                        self.cache.pop(key,None)
                self.jobs.task_done()
                continue
            try:
                result=self.lookup(hashes,name,entries)
            except Exception:
                result={'status':'unavailable','message':'Trackerfordele ukendte — opslaget kunne ikke gennemføres.'}
            with self.trackers.lock:
                still_current=all(e in self.trackers.entries() for e in entries)
            with self.lock:
                if still_current:
                    self.cache[key]={'at':time.time(),'result':result,'priority':priority}
                else:
                    self.cache.pop(key,None)
            self.jobs.task_done()
            # Keep automatic torrent lookups at most one job per second.
            stop.wait(1)
