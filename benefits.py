"""Bounded asynchronous tracker lookups with exact hash verification."""
import hashlib
import copy
import json
import itertools
import math
import queue
import re
import threading
import time
from datetime import datetime
from state import atomic
from green_credit import policy_from_result, created_timestamp
from covers import poster_url
from tracker_providers import PROVIDERS


def event_timestamp(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Event timezone missing')
    return parsed.timestamp()


def effective_freeleech(match,now=None):
    if match.get('global_freeleech') is not True:
        return match.get('freeleech')
    try:
        if event_timestamp(match['global_freeleech_ends_at'])>(time.time() if now is None else now):
            return 100
    except (KeyError,TypeError,ValueError,OverflowError,AttributeError):
        pass
    return match.get('torrent_freeleech')


def byte_size(value):
    if isinstance(value,str) and re.fullmatch('[0-9]{1,19}',value):
        value=int(value)
    return value if type(value) is int and 0<=value<=2**63-1 else None


def ratio_estimate(match,account,size,now=None):
    """Full download, no assumed future upload; never treat unknown discounts as free."""
    result={'tracker_id':match.get('tracker_id'),'tracker_name':match.get('tracker_name'),
            'status':'unknown','warning':False}
    size=byte_size(size)
    if size is None:
        return {**result,'message':'Ratio kan ikke beregnes: torrentens størrelse er ukendt.'}
    if not account or account.get('status')!='ok':
        return {**result,'status':'pending' if account and account.get('status')=='pending' else 'unknown',
                'message':'Ratio kan ikke beregnes: aktuelle kontotal mangler.'}
    stamp=account.get('updated_at')
    now=time.time() if now is None else now
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=now-stamp<=600:
        return {**result,'message':'Ratio kan ikke beregnes: kontotallene er for gamle.'}
    stats=account.get('stats',{})
    uploaded,downloaded=stats.get('uploaded'),stats.get('downloaded')
    if any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=2**63-1 for n in (uploaded,downloaded)):
        return {**result,'message':'Ratio kan ikke beregnes: upload/download-tal mangler.'}
    free=effective_freeleech(match,now)
    known=type(free) in (int,float) and free in (0,25,50,75,100)
    charged=size*(1-(free if known else 0)/100)
    denominator=downloaded+charged
    projected=uploaded/denominator if denominator>0 else None
    return {**result,'status':'ok','torrent_size':size,'charged_download':charged,
            'current_ratio':uploaded/downloaded if downloaded>0 else None,
            'projected_ratio':projected,'infinite':denominator==0 and uploaded>0,
            'warning':projected is not None and projected<=.5,'assumed_no_freeleech':not known,
            'updated_at':stamp}


class Benefits:
    RETRY_INTERVAL=120
    MAX_RETRIES=3

    def __init__(self, trackers):
        self.trackers=trackers
        self.lock=threading.RLock()
        self.cache={}
        self.jobs=queue.PriorityQueue(maxsize=200)
        self.sequence=itertools.count()
        self.stop=None
        self.last_request=0
        self.snapshot_path=trackers.path.with_name('torrent-benefits.json')
        try:
            self.snapshots=json.loads(self.snapshot_path.read_text())
            if not isinstance(self.snapshots,dict):
                self.snapshots={}
        except (OSError,ValueError):
            self.snapshots={}
        self.snapshot_pending=set()
        self.retry_path=trackers.path.with_name('torrent-benefit-retries.json')
        try:
            retries=json.loads(self.retry_path.read_text())
            self.retries={h:{'count':v['count'],'next_at':v['next_at'],'in_flight':False}
                          for h,v in retries.items() if isinstance(h,str) and re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',h)
                          and isinstance(v,dict) and type(v.get('count')) is int
                          and 0<=v['count']<=self.MAX_RETRIES
                          and type(v.get('next_at')) in (int,float) and math.isfinite(v['next_at'])}
        except (OSError,ValueError,AttributeError,TypeError):
            self.retries={}

    def needs_retry(self,result):
        active={e['id'] for e in self.trackers.entries()}
        if not active:
            return False
        if result.get('status') in ('unknown','unavailable'):
            return True
        return any(m.get('tracker_id') in active and (
            (created_timestamp(m.get('created_at')) is None and not m.get('own_upload'))
            or type(m.get('freeleech')) not in (int,float) or m.get('freeleech') not in (0,25,50,75,100)
            or type(m.get('double_upload')) is not bool or not poster_url(m.get('poster')))
            for m in result.get('matches',[]))

    def save_retries(self):
        atomic(self.retry_path,json.dumps(self.retries),mode=0o600)

    def update_retry(self,ident,result,lookup_finished=False):
        previous=copy.deepcopy(self.retries.get(ident))
        if not self.needs_retry(result):
            self.retries.pop(ident,None)
        elif (ident in self.retries or result.get('status') in ('unknown','unavailable')
                or all('created_at' in m and 'poster' in m for m in result.get('matches',[]))):
            retry=self.retries.setdefault(ident,{'count':0,'next_at':time.time()+self.RETRY_INTERVAL,'in_flight':False})
            if lookup_finished and retry['in_flight']:
                retry.update(in_flight=False,next_at=time.time()+self.RETRY_INTERVAL)
        return previous!=self.retries.get(ident)

    @staticmethod
    def without_global(result):
        result=copy.deepcopy(result)
        for match in result.get('matches',[]):
            if 'torrent_freeleech' in match:
                match['freeleech']=match.pop('torrent_freeleech')
            match.pop('global_freeleech',None)
            match.pop('global_freeleech_ends_at',None)
        return result

    def with_global(self,result,now=None):
        """Overlay current account events without freezing them into torrent history."""
        result=self.without_global(result)
        now=time.time() if now is None else now
        with self.trackers.lock:
            accounts=copy.deepcopy(self.trackers.cache)
            providers={e['id']:e['provider'] for e in self.trackers.entries()}
        for match in result.get('matches',[]):
            if match.get('tracker_provider') and match['tracker_provider'] != providers.get(match.get('tracker_id')):
                continue
            account=accounts.get(match.get('tracker_id'),{})
            if 'events' not in account:
                continue
            stamp=account.get('updated_at')
            match['torrent_freeleech']=match.get('freeleech')
            match['global_freeleech']=None
            if (account.get('status')!='ok' or type(stamp) not in (int,float)
                    or not 0<=now-stamp<=120 or not isinstance(account.get('events'),list)):
                continue
            ends=[];invalid=False
            for event in account['events']:
                if not isinstance(event,dict) or event.get('type')!='global_freeleech':
                    continue
                try:
                    end=event_timestamp(event['ends_at'])
                    start=event_timestamp(event['starts_at']) if event.get('starts_at') else None
                    if start is not None and start>=end:
                        raise ValueError('Invalid event interval')
                    if end>now and (start is None or start<=now):
                        ends.append((end,event['ends_at']))
                except (KeyError,TypeError,ValueError,OverflowError,AttributeError):
                    invalid=True
            match['global_freeleech']=True if ends else None if invalid else False
            if ends:
                match['freeleech']=100
                match['global_freeleech_ends_at']=max(ends)[1]
        return result

    def publish_green(self):
        """Only verified dates and an enable flag cross into the VPN worker."""
        with self.lock:
            policies={h:policy_from_result(r) for h,r in self.snapshots.items()}
            policies['_enabled']=bool(self.trackers.entries())
            directory=self.snapshot_path.parent/'rpc'
            directory.mkdir(exist_ok=True)
            try:
                previous=json.loads((directory/'green-policy.json').read_text())
            except (OSError,ValueError):
                previous={}
            policies['_started_at']=previous.get('_started_at',time.time())
            atomic(directory/'green-policy.json',json.dumps(policies),mode=0o644)

    def needs_date(self,result):
        ids={entry['id'] for entry in self.trackers.entries()}
        if ids and result.get('status') in ('unknown','unavailable'):
            return True
        return any('created_at' not in m and (m.get('tracker_provider') in PROVIDERS or m.get('tracker_id') in ids)
                   for m in result.get('matches',[]))

    @staticmethod
    def hashes(meta):
        return tuple(sorted({h.lower() for h in meta.get('hashes',[]) if isinstance(h,str)
                             and re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}',h)}))

    def remember(self, meta, result, lookup_finished=False):
        """Freeze display data only; RSS approval keeps using fresh request()."""
        if result.get('status')=='pending':
            return
        result=self.without_global(result)
        hashes=self.hashes(meta)
        if not hashes:
            return
        with self.lock:
            changed=False
            retry_changed=False
            for ident in hashes:
                if ident not in self.snapshots or (self.snapshots[ident].get('status')!='matched' and self.snapshots[ident]!=result):
                    self.snapshots[ident]=copy.deepcopy(result)
                    changed=True
                elif result.get('status')=='matched':
                    # Fill missing verified fields; retain already known accounting data.
                    fresh={m['tracker_id']:m for m in result.get('matches',[])}
                    for match in self.snapshots[ident].get('matches',[]):
                        for key,value in fresh.get(match.get('tracker_id'),{}).items():
                            missing=(key not in match or match[key] is None
                                     or key=='created_at' and created_timestamp(match[key]) is None
                                     or key=='freeleech' and (type(match[key]) not in (int,float) or match[key] not in (0,25,50,75,100))
                                     or key=='double_upload' and type(match[key]) is not bool)
                            if (missing or key=='poster') and match.get(key,'missing')!=value:
                                match[key]=value
                                changed=True
                retry_changed=self.update_retry(ident,self.snapshots[ident],lookup_finished) or retry_changed
                self.snapshot_pending.discard(ident)
            if changed:
                atomic(self.snapshot_path,json.dumps(self.snapshots),mode=0o600)
                self.publish_green()
            if retry_changed:
                self.save_retries()

    def snapshot(self, meta):
        hashes=self.hashes(meta)
        with self.lock:
            saved=next((self.snapshots[h] for h in hashes if h in self.snapshots),None)
            if saved is not None:
                if not self.needs_retry(saved) and not self.needs_date(saved):
                    return self.with_global(saved)
                retries=[self.retries[h] for h in hashes if h in self.retries]
                retry=max(retries,key=lambda v:v['count']) if retries else None
                if retry and (retry['in_flight'] or retry['count']>=self.MAX_RETRIES or time.time()<retry['next_at']):
                    return self.with_global(saved)
                if retry:
                    if not str(meta.get('name','')).strip():
                        return self.with_global(saved)
                    self.snapshot_pending.update(hashes)
                    result=self.request(meta,priority=1,max_age=0)
                    if result.get('status')=='pending':
                        for h in hashes:
                            self.retries[h]={'count':retry['count']+1,'next_at':time.time()+self.RETRY_INTERVAL,'in_flight':True}
                        self.save_retries()
                    return self.with_global(saved)
        if not str(meta.get('name','')).strip():
            return {'status':'unknown','message':'Afventer torrentoplysninger.'}
        with self.lock:
            self.snapshot_pending.update(hashes)
        result=self.request(meta,priority=1)
        self.remember(meta,result)
        with self.lock:
            return self.with_global(next((self.snapshots[h] for h in hashes if h in self.snapshots),result))

    def request(self, meta, selected='', priority=0, max_age=300):
        hashes=tuple(sorted({h.lower() for h in meta.get('hashes',[]) if isinstance(h,str) and re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}',h)}))
        if not hashes:
            return {'status':'unknown','message':'Trackerfordele ukendte — ingen info-hash.'}
        name=str(meta.get('name',''))[:200]
        with self.trackers.lock:
            entries=[e for e in self.trackers.entries() if not selected or e['id']==selected]
        if not entries:
            return {'status':'unknown','message':'Tilføj en tracker under Trackere for at se fordelene.'}
        signature=tuple((e['id'],e['name'],e['provider'],hashlib.sha256(e['api_key'].encode()).hexdigest()) for e in entries)
        key=(hashes,name,signature)
        with self.lock:
            cached=self.cache.get(key)
            promote=cached and cached['result']['status']=='pending' and priority<cached['priority']
            if cached and not promote and (cached['result']['status']=='pending' or time.time()-cached['at']<max_age):
                return self.with_global(cached['result'])
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

    def refresh_snapshot(self,meta):
        """Queue a fresh exact-hash lookup, preserving saved accounting and metadata."""
        with self.lock:
            hashes=self.hashes(meta)
            self.snapshot_pending.update(hashes)
            if any(h in self.retries for h in hashes):
                for h in hashes:
                    self.retries.pop(h,None)
                self.save_retries()
        result=self.request(meta,priority=0,max_age=0)
        self.remember(meta,result)
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
        # A single-file torrent uses e.g. Release.mkv as its internal name,
        # while the tracker indexes Release. Still verify every hit by hash.
        release=re.sub(r'\.(?:mkv|mp4|m4v|avi|mov|wmv|webm|m2ts|ts|iso|flac|mp3|m4a|ogg|wav)$','',name,flags=re.I)
        candidates=list(dict.fromkeys([release,name,re.sub(r'[._]+',' ',release).strip(),
                                      re.sub(r'[._]+',' ',name).strip()]))
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
                        data=self.trackers.read_json(entry,PROVIDERS[entry['provider']]['torrents_url'],params)
                        rows=data.get('data',[]) if isinstance(data,dict) else []
                        if not isinstance(rows,list):
                            raise ValueError('Unknown tracker response')
                        for row in rows[:50]:
                            a=row.get('attributes',{}) if isinstance(row,dict) else {}
                            if not isinstance(a,dict):
                                continue
                            ident=a.get('info_hash','')
                            if isinstance(ident,str) and ident.lower() in hashes:
                                match={'tracker_id':entry['id'],'tracker_name':entry['name'],
                                       'tracker_provider':entry.get('provider','nordicbytes'),'created_at':a.get('created_at'),
                                       'poster':poster_url(a.get('meta',{}).get('poster')) if isinstance(a.get('meta'),dict) else None,
                                       'size':byte_size(a.get('size')),'leechers':byte_size(a.get('leechers')),**self.flags(a)}
                                with self.trackers.lock:
                                    username=self.trackers.cache.get(entry['id'],{}).get('username')
                                match['own_upload']=bool(username and a.get('uploader')==username)
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
                snapshot_needed=still_current and any(h in self.snapshot_pending for h in hashes)
            if snapshot_needed:
                self.remember({'hashes':hashes},result,lookup_finished=True)
            self.jobs.task_done()
            # Keep automatic torrent lookups at most one job per second.
            stop.wait(1)
