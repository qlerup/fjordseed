"""Approve RSS identities before adding torrents. Fetch metadata only inside VPN."""
import base64
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
from urllib.parse import urlencode, urljoin, urlsplit

import requests

from rss import PREFIX, validate_feed, folder_path, tracker_required
from state import atomic
from torrent_meta import magnet_meta, torrent_meta
from qbit_rpc import seed_ratio, SEEDING_MINUTES
from green_credit import CreditLedger, policy_from_result


def fingerprint(feed):
    return hashlib.sha256(json.dumps(feed,sort_keys=True).encode()).hexdigest()


def badges_match(result, feed, now=None):
    now=time.time() if now is None else now
    stamp=result.get('checked_at',0)
    if (result.get('status')!='matched' or not isinstance(stamp,(int,float))
            or not 0<=now-stamp<(30 if feed.get('min_leechers',0)>0 else 300) or not tracker_required(feed)):
        return False
    minimum=feed.get('min_leechers',0)
    return any(m.get('tracker_id')==feed['tracker_id']
        and (minimum==0 or (type(m.get('leechers')) is int and m['leechers']>=minimum)) and all(
        m.get('freeleech')==100 if badge=='freeleech' else m.get(badge) is True
        for badge in feed.get('required_badges',[])) for m in result.get('matches',[]))


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def fetch_metadata(url):
    """Only metadata, never torrent payload. Runs in the VPN container."""
    with requests.Session() as client:
        client.trust_env=False
        for _ in range(5):
            if url.startswith('magnet:?'):
                return magnet_meta(url), {'magnet':url}
            validate_feed(dict(name='metadata',url=url,enabled=False,ratio_limit=1))
            parsed=urlsplit(url)
            addresses=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError('Torrent metadata must be public')
            with client.get(url,timeout=(3,5),allow_redirects=False,stream=True) as response:
                if response.is_redirect:
                    url=urljoin(url,response.headers['Location'])
                    continue
                response.raise_for_status()
                chunks=[]
                total=0
                for chunk in response.iter_content(65536):
                    total+=len(chunk)
                    if total>4*1024*1024:
                        raise ValueError('Torrent metadata too large')
                    chunks.append(chunk)
                raw=b''.join(chunks)
                return torrent_meta(raw), {'torrent':base64.b64encode(raw).decode()}
    raise ValueError('Too many metadata redirects')


def gate_rpc(action,data,api,root=Path('/config')):
    ident=data.get('feed_id','')
    if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):
        raise ValueError('Invalid feed')
    source=next((e for e in read_json(root/'fjord-rss.json',[]) if e['id']==ident),None)
    if not source or fingerprint(source)!=data.get('revision'):
        raise ValueError('Feed changed')
    feed={**validate_feed(source),'id':ident}
    if not feed['enabled'] or not tracker_required(feed):
        raise ValueError('Badge gate inactive')
    name=PREFIX+ident
    rule=api('rss/rules').json().get(name)
    if not rule or rule.get('enabled') is not False or rule.get('mustContain')!=feed['include'] or rule.get('affectedFeeds')!=[feed['url']]:
        raise ValueError('RSS rules not synchronized')
    pending_path=root/('rss-pending-'+ident+'.json')
    history_path=root/('rss-history-'+ident+'.json')
    history=read_json(history_path,{'done':[], 'retry':{}})
    pending=read_json(pending_path,{})
    now=time.time()
    if pending and (pending['revision']!=data['revision'] or not 0<=now-pending['created_at']<600):
        pending_path.unlink(missing_ok=True)
        pending={}
    if action=='rss_prepare':
        if not pending:
            item=api('rss/items?withData=true').json().get(name,{})
            if item.get('url')!=feed['url'] or item.get('hasError'):
                raise ValueError('RSS feed unavailable')
            matches=api('rss/matchingArticles?'+urlencode({'ruleName':name})).json().get(name,[])
            titles=set(matches)
            articles=item.get('articles',[])
            candidates=[]
            for article in articles:
                url=article.get('torrentURL') or article.get('link','')
                if article.get('title') not in titles or not isinstance(url,str) or not url:
                    continue
                token=hashlib.sha256((str(article.get('id',''))+'\n'+url).encode()).hexdigest()
                candidates.append((history['retry'].get(token,0),token,url,article))
            # Oldest attempts first: busy feeds must not starve later entries.
            for _,token,url,article in sorted(candidates,key=lambda c:c[0]):
                if token in history['done'] or history['retry'].get(token,0)>now:
                    continue
                # A broken item must not starve later articles.
                history['retry'][token]=now+300
                active_tokens={c[1] for c in candidates}
                history['retry']={k:v for k,v in history['retry'].items() if k in active_tokens}
                atomic(history_path,json.dumps(history))
                meta,payload=fetch_metadata(url)
                if not meta.get('name'):
                    meta['name']=str(article.get('title',''))[:200]
                pending={'token':token,'meta':meta,'payload':payload,'revision':data['revision'],'created_at':now}
                atomic(pending_path,json.dumps(pending))
                break
        return {k:pending[k] for k in ('token','meta') if k in pending}
    if action!='rss_resolve' or not pending or pending['token']!=data.get('token'):
        raise ValueError('Candidate expired')
    if data.get('approved') is True:
        if not badges_match(data.get('benefits',{}),feed):
            raise ValueError('Badges not verified')
        hashes=pending['meta']['hashes']
        if sorted(hashes)!=sorted(data.get('hashes',[])):
            raise ValueError('Torrent identity changed')
        keys=[pending['token'],*hashes]
        existing=api('torrents/info?'+urlencode({'hashes':'|'.join(hashes)})).json()
        already_added=existing or any(h in history['done'] for h in hashes)
        # Record intent before POST: an ambiguous timeout must not start it twice.
        history['done']=list(dict.fromkeys([*history['done'],*keys]))
        atomic(history_path,json.dumps(history))
        if not already_added:
            green_policy=policy_from_result(data['benefits'])
            with CreditLedger().transaction() as ledger:
                ledger.register(hashes,seed_ratio(feed['ratio_limit']),green_policy)
            path=folder_path(feed['folder'])
            path.mkdir(parents=True,exist_ok=True)
            options={'savepath':str(path),'stopped':'false','autoTMM':'false',
                     'tags':'FjordSeed-RSS-'+ident,'ratioLimit':seed_ratio(feed['ratio_limit']),
                     'seedingTimeLimit':SEEDING_MINUTES,'inactiveSeedingTimeLimit':-1,
                     'shareLimitAction':'RemoveWithContent' if feed['ratio_action']=='delete' else 'Stop'}
            if (green_policy.get('until') or 0)>now or not green_policy.get('known') or not green_policy.get('has_date'):
                options['ratioLimit']*=2
            payload=pending['payload']
            if payload.get('magnet'):
                response=api('torrents/add',{**options,'urls':payload['magnet']})
            else:
                raw=base64.b64decode(payload['torrent'],validate=True)
                response=api('torrents/add',options,{'torrents':('rss.torrent',io.BytesIO(raw),'application/x-bittorrent')})
            if response.text.strip()!='Ok.':
                result=response.json()
                if result.get('failure_count',0) or result.get('success_count',0)+result.get('pending_count',0)<1:
                    history['done']=[k for k in history['done'] if k not in keys]
                    atomic(history_path,json.dumps(history))
                    raise ValueError('Torrent rejected')
    else:
        history['retry'][pending['token']]=now+300
        atomic(history_path,json.dumps(history))
    pending_path.unlink(missing_ok=True)
    return {'ok':True}


class RssGate:
    def __init__(self,rss,runtime,trackers,state):
        self.rss,self.runtime,self.trackers,self.state=rss,runtime,trackers,state
        self.reports={}

    def tick(self):
        with self.rss.lock:
            entries=self.rss.entries()
        for feed in entries:
            if not feed['enabled'] or not tracker_required(feed):
                continue
            try:
                with self.trackers.lock:
                    tracker=next((t for t in self.trackers.entries() if t['id']==feed['tracker_id']),None)
                if not tracker:
                    self.reports[feed['id']]='Tilføj eller vælg trackeren igen. Download er blokeret.'
                    continue
                if not self.trackers.badge_ready(feed['tracker_id']):
                    self.reports[feed['id']]='Trackerens API-adgang er ikke bekræftet aktiv. Download er blokeret.'
                    continue
                if not self.state.get()['enabled']:
                    continue
                candidate=self.runtime.rpc('rss_prepare',{'feed_id':feed['id'],'revision':fingerprint(feed)})
                if not candidate:
                    self.reports[feed['id']]='Afventer feedposter, der opfylder alle downloadkrav.'
                    continue
                result=self.trackers.benefits.request(candidate['meta'],feed['tracker_id'],priority=1,
                    max_age=30 if feed.get('min_leechers',0)>0 else 300)
                if result.get('status')=='pending':
                    self.reports[feed['id']]='Kontrollerer downloadkrav hos trackeren før download…'
                    continue
                approved=badges_match(result,feed)
                # Serialize with edits and connection changes. Recheck immediately before add.
                with self.state.lock, self.rss.lock, self.trackers.lock:
                    current=next((e for e in self.rss.entries() if e['id']==feed['id']),None)
                    if (current!=feed or not self.state.get()['enabled'] or tracker not in self.trackers.entries()
                            or not self.trackers.badge_ready(feed['tracker_id'])):
                        continue
                    self.runtime.rpc('rss_resolve',{'feed_id':feed['id'],'revision':fingerprint(feed),
                        'token':candidate['token'],'hashes':candidate['meta']['hashes'],
                        'approved':approved,'benefits':result})
                    if approved:
                        self.trackers.benefits.remember(candidate['meta'],result)
                self.reports[feed['id']]='Alle downloadkrav bekræftet.' if approved else 'Feedposter, der ikke opfylder downloadkravene, springes over og kontrolleres igen senere.'
            except Exception:
                self.reports[feed['id']]='Afventer VPN, feedsynkronisering eller trackeropslag. Ingen ubekræftede downloads.'

    def run(self,stop):
        while not stop.is_set():
            self.tick()
            stop.wait(10)
