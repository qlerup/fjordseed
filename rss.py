"""Persist RSS rules and apply them inside qBittorrent's VPN namespace."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time
from urllib.parse import urlsplit
import uuid
import unicodedata

from qbit_rpc import share_policy, call, seed_ratio
from state import atomic

PREFIX='FjordSeed-'
BADGES=('freeleech','double_upload','featured','internal','refundable')


def title_key(value):
    return re.sub(r'[\W_]+',' ',unicodedata.normalize('NFKC',value).casefold()).strip()


def validate_title_filters(value):
    if not isinstance(value,list) or len(value)>50:
        raise ValueError('Hver titelliste må indeholde op til 50 titler.')
    result=[];seen=set()
    for title in value:
        if (not isinstance(title,str) or not 1<=len(title.strip())<=120
                or any(ord(c)<32 for c in title) or not title_key(title)):
            raise ValueError('Indtast en titel på 1–120 tegn.')
        key=title_key(title)
        if key not in seen:
            seen.add(key);result.append(title.strip())
    return result


def title_matches(article,feed):
    """Plain title fragments: any include, no exclude; separators are equivalent."""
    include=feed.get('title_include',[]);exclude=feed.get('title_exclude',[])
    if not include and not exclude:
        return True
    title=article.get('title')
    if not isinstance(title,str) or not title_key(title):
        return False
    key=title_key(title)
    return not any(title_key(t) in key for t in exclude) and (not include or any(title_key(t) in key for t in include))


def size_matches(meta,feed):
    """An optional inclusive total-size cap; unknown metadata fails closed."""
    limit=feed.get('max_size_bytes')
    if limit is None:
        return True
    size=meta.get('size')
    return type(size) is int and 0<=size<=limit


def article_timestamp(value):
    """qBittorrent exposes ISO dates; also accept RFC dates from RSS fixtures."""
    if not isinstance(value, str) or not value or len(value) > 100:
        return None
    try:
        try:
            date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            date = parsedate_to_datetime(value)
        return date.timestamp() if date.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def date_matches(article, feed):
    if not feed.get('download_from'):
        return True
    stamp = article_timestamp(article.get('date'))
    cutoff = article_timestamp(feed['download_from'])
    return stamp is not None and cutoff is not None and stamp >= cutoff


def folder_path(folder, root=Path('/downloads')):
    if (not isinstance(folder,str) or len(folder)>240 or folder.startswith('/') or '\\' in folder
            or any(part in ('.','..','.incomplete','.fjordseed-buffer') for part in folder.split('/')) or any(ord(c)<32 for c in folder)):
        raise ValueError('Vælg en undermappe i din downloadmappe, fx serier eller film/freeleech.')
    folder=folder.strip().strip('/')
    path=root / PurePosixPath(folder)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Mappen ligger uden for downloadplaceringen.')
    return path


def validate_feed(data):
    if not isinstance(data,dict):
        raise ValueError('Ugyldigt RSS-feed.')
    from conversion import choice
    convert=choice(data.get('convert',False))
    name=data.get('name','')
    url=data.get('url','')
    if not isinstance(name,str) or not 1<=len(name.strip())<=80 or not isinstance(url,str):
        raise ValueError('Indtast et navn og en RSS-adresse.')
    try:
        parsed=urlsplit(url)
        port=parsed.port
    except ValueError:
        raise ValueError('Indtast en gyldig RSS-adresse.') from None
    if (len(url)>4096 or parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or any(ord(c)<33 for c in url) or port not in (None,80,443)):
        raise ValueError('Brug en HTTP- eller HTTPS-adresse uden loginoplysninger.')
    host=parsed.hostname.lower()
    try:
        public=ipaddress.ip_address(host).is_global
    except ValueError:
        public='.' in host and not host.endswith(('.local','.localhost','.internal'))
    if not public:
        raise ValueError('RSS-adressen skal pege på en offentlig tracker.')
    if type(data.get('enabled')) is not bool:
        raise ValueError('Vælg automatisk download.')
    start=data.get('download_from')
    if start not in (None, ''):
        if not isinstance(start,str) or len(start)>100:
            raise ValueError('Vælg en gyldig startdato med tidszone.')
        try:
            date=datetime.fromisoformat(start.replace('Z','+00:00'))
            if date.tzinfo is None:
                raise ValueError()
            start=date.astimezone(timezone.utc).isoformat()
        except (ValueError,OverflowError):
            raise ValueError('Vælg en gyldig startdato med tidszone.') from None
    else:
        start=None
    folder=data.get('folder','')
    folder_path(folder)
    max_size=data.get('max_size_bytes')
    if max_size is not None and (type(max_size) is not int or not 1<=max_size<=2**53-1):
        raise ValueError('Vælg en gyldig maksimal størrelse større end nul, eller lad feltet være tomt.')
    badges=data.get('required_badges',[])
    tracker=data.get('tracker_id','')
    if not isinstance(badges,list) or any(not isinstance(b,str) or b not in BADGES for b in badges) or len(badges)>len(BADGES):
        raise ValueError('Vælg gyldige badges til feedet.')
    if not isinstance(tracker,str) or (tracker and not re.fullmatch('[a-f0-9]{32}',tracker)) or (badges and not tracker):
        raise ValueError('Vælg den tracker, der skal bekræfte de valgte badges.')
    policy=share_policy(data)
    sources=data.get('history_sources',[])
    if (not isinstance(sources,list) or len(sources)>20 or
            any(not isinstance(s,str) or not re.fullmatch('[a-f0-9]{32}',s) for s in sources)):
        raise ValueError('Vælg gyldige feeds til historikken.')
    if policy['ratio_limit']<0:
        raise ValueError('Vælg en stop-ratio fra 0 til 10000.')
    policy['ratio_limit']=seed_ratio(policy['ratio_limit'])
    return {'name':name.strip(),'url':url,'folder':folder.strip().strip('/'), 'history_sources':list(dict.fromkeys(sources)),
            'title_include':validate_title_filters(data.get('title_include',[])),
            'title_exclude':validate_title_filters(data.get('title_exclude',[])),
            'max_size_bytes':max_size,'convert':convert,
            'enabled':data['enabled'],'download_from':start,'required_badges':list(dict.fromkeys(badges)),
            'tracker_id':tracker if badges else '',**policy}


class Rss:
    def __init__(self,root,downloads=Path('/downloads')):
        self.root=root
        self.path=root/'rss.json'
        self.downloads=downloads
        self.lock=threading.RLock()
        if not self.path.exists():
            atomic(self.path,'[]')
        # Retire legacy filters; preserve current title lists and badge requirements.
        saved=json.loads(self.path.read_text(encoding='utf-8'))
        migrated=[{**validate_feed(e),'id':e['id']} for e in saved]
        preset_path=self.root/'rss-history-presets.json'
        if preset_path.exists():
            presets=json.loads(preset_path.read_text(encoding='utf-8'))
            for old,feed in zip(saved,migrated):
                if 'history_sources' not in old:
                    preset=next((p for p in presets if title_key(p.get('name',''))==title_key(feed['name'])),None)
                    if preset:
                        feed.update(history_sources=preset['sources'])
                        validate_feed(feed)
        if saved != migrated:
            atomic(self.path,json.dumps(migrated))
        self.path.chmod(0o600)

    def entries(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def save(self,data):
        if not isinstance(data,dict):
            raise ValueError('Ugyldigt RSS-feed.')
        ident=data.get('id','')
        if not isinstance(ident,str):
            raise ValueError('Ugyldigt RSS-feed.')
        with self.lock:
            entries=self.entries()
            existing=next((e for e in entries if e['id']==ident),None)
            if ident and not existing:
                raise ValueError('Feedet findes ikke længere.')
            data={**data}
            if existing and 'max_size_bytes' not in data:
                data['max_size_bytes']=existing.get('max_size_bytes')
            if existing and 'required_badges' not in data:
                data['required_badges']=existing.get('required_badges',[])
                data['tracker_id']=existing.get('tracker_id','')
            if not data.get('url') and existing:
                data['url']=existing['url']
            # Optional administrator-provided history preset for a planned new
            # feed. It links immutable source IDs, never guesses from RSS URLs.
            preset={}
            preset_path=self.root/'rss-history-presets.json'
            if not existing and preset_path.exists():
                presets=json.loads(preset_path.read_text(encoding='utf-8'))
                preset=next((p for p in presets if title_key(p.get('name',''))==title_key(data.get('name',''))),{})
                if preset:data={**data,'history_sources':preset['sources']}
            feed=validate_feed(data)
            if ident in feed['history_sources']:
                raise ValueError('Et feed kan ikke medtage sig selv som historikkilde.')
            allowed={e['id'] for e in entries}|set((existing or {}).get('history_sources',[]))|set(preset.get('sources',[]))
            if any(s not in allowed for s in feed['history_sources']):
                raise ValueError('Et valgt historikfeed findes ikke længere.')
            folder_path(feed['folder'],self.downloads)
            if not existing and len(entries)>=20:
                raise ValueError('Du kan tilføje op til 20 RSS-feeds.')
            if any(e['url']==feed['url'] and e['id']!=ident for e in entries):
                raise ValueError('RSS-adressen er allerede tilføjet.')
            feed['id']=ident or uuid.uuid4().hex
            entries=[feed if e['id']==ident else e for e in entries] if existing else entries+[feed]
            atomic(self.path,json.dumps(entries))
            return feed['id']

    def remove(self,ident):
        with self.lock:
            entries=self.entries()
            if not any(e['id']==ident for e in entries):
                raise ValueError('Feedet findes ikke længere.')
            atomic(self.path,json.dumps([e for e in entries if e['id']!=ident]))

    def download_history(self, ident):
        with self.lock:
            feed=next((e for e in self.entries() if e['id']==ident),None)
            if not feed:
                raise ValueError('Feedet findes ikke længere.')
        path = self.root/'qbit/green-credit.json'
        if not path.exists():
            return []
        ledger = json.loads(path.read_text(encoding='utf-8'))
        archived=ledger.get('_rss_upload',{}).get('feeds',{})
        items={}
        for source in dict.fromkeys([ident,*feed.get('history_sources',[])]):
            for hash_id,record in archived.get(source,{}).get('downloads',{}).items():
                if hash_id not in items:items[hash_id]={**record,'source_feeds':[source]}
                else:
                    merged=items[hash_id];merged['source_feeds'].append(source)
                    merged['credited_uploaded']=merged.get('credited_uploaded',0)+record.get('credited_uploaded',0)
                    for field in ('uploaded','downloaded','credited_downloaded'):
                        if field in record and field in merged:merged[field]+=record[field]
                        else:merged.pop(field,None)
                    merged['added_at']=min(merged['added_at'],record['added_at'])
                    for flag in ('estimated','download_credit_incomplete'):
                        merged[flag]=merged.get(flag,False) or record.get(flag,False)
        result=[]
        for ident,item in items.items():
            item={**item, 'hash':ident}
            # Recover physical totals from the existing per-torrent ledger when
            # available. Do not invent measurements for already removed torrents.
            entry=ledger.get(ident,{})
            traffic=entry.get('physical_traffic',{})
            for field in ('uploaded','downloaded'):
                if field not in item and field in traffic and len(item['source_feeds'])==1 and entry.get('rss_feed_id') in item['source_feeds']:item[field]=traffic[field]
            result.append(item)
        return sorted(result, key=lambda item: item['added_at'], reverse=True)

    def public(self):
        with self.lock:
            entries=self.entries()
        state={}
        try:
            status=json.loads((self.root/'qbit/worker-status.json').read_text())
            if status.get('ready') and 0<=time.time()-status['checked_at']<10:
                state=status
        except (OSError,ValueError,KeyError):
            pass
        reports={e['id']:e for e in state.get('rss',[])}
        # The worker commits feed totals together with torrent credit samples.
        # This stays available while the VPN is offline or the feed is paused.
        upload_history=None
        try:
            ledger=json.loads((self.root/'qbit/green-credit.json').read_text(encoding='utf-8'))
            history=ledger.get('_rss_upload')
            if isinstance(history,dict) and isinstance(history.get('feeds'),dict):
                upload_history=history
        except (OSError,ValueError,AttributeError):
            pass
        def upload_total(ident):
            if upload_history is None:
                return {'credited_uploaded':None,'credit_estimated':False,'credit_started_at':None}
            total=upload_history['feeds'].get(ident,{})
            feed=next(e for e in entries if e['id']==ident)
            related=[upload_history['feeds'].get(s,{}) for s in set(feed.get('history_sources',[]))-{ident}]
            value=total.get('credited_uploaded',0) if isinstance(total,dict) else None
            own=value
            if value is not None:value+=sum(t.get('credited_uploaded',0) for t in related)
            valid=type(value) in (int,float) and math.isfinite(value) and value>=0
            return {'credited_uploaded':value if valid else None,'own_credited_uploaded':own,
                    'credit_estimated':bool(isinstance(total,dict) and total.get('estimated')),
                    'credit_started_at':upload_history.get('started_at')}
        source_ids={source for e in entries for source in [e['id'],*e.get('history_sources',[])]}
        total_credit=(sum(upload_history['feeds'].get(s,{}).get('credited_uploaded',0) for s in source_ids) if upload_history is not None else None)
        return {'credited_uploaded_total':total_credit,'feeds':[{k:v for k,v in e.items() if k!='url'} | {
                'ratio_limit':seed_ratio(e['ratio_limit']),
                'host':urlsplit(e['url']).hostname,'has_url':True,
                'status':('paused' if not e['enabled'] else 'pending' if not state else
                          'error' if state.get('rss_error') or reports.get(e['id'],{}).get('has_error') else
                          'active' if e['id'] in reports else 'pending'),
                'articles':reports.get(e['id'],{}).get('articles',0)} | upload_total(e['id']) for e in entries]}


def write_snapshot(root,uid,gid):
    source=root/'rss.json'
    feeds=json.loads(source.read_text()) if source.exists() else []
    data=json.dumps(feeds,sort_keys=True)
    path=root/'qbit/fjord-rss.json'
    if not path.exists() or path.read_text()!=data:
        atomic(path,data)
        if hasattr(os,'chown'):
            os.chown(path,uid,gid)


def sync_rss(feeds,api=call):
    # No feed may start before its own ratio, file action and folder are set.
    api('app/setPreferences',{'json':json.dumps({'rss_auto_downloading_enabled':False,'rss_processing_enabled':False})})
    entries=[]
    for entry in feeds:
        if not re.fullmatch('[a-f0-9]{32}',entry.get('id','')):
            raise ValueError('Invalid RSS identifier')
        validated=validate_feed(entry)
        validated['id']=entry['id']
        entries.append(validated)
    rules=api('rss/rules').json()
    items=api('rss/items?withData=false').json()
    wanted={PREFIX+e['id'] for e in entries}
    for name in list(rules):
        if name.startswith(PREFIX) and name not in wanted:
            api('rss/removeRule',{'ruleName':name})
    for name in list(items):
        if name.startswith(PREFIX) and name not in wanted:
            api('rss/removeItem',{'path':name})
    for entry in entries:
        name=PREFIX+entry['id']
        current=items.get(name)
        if current and current.get('url')!=entry['url']:
            api('rss/removeItem',{'path':name})
            current=None
        if not current:
            api('rss/addFeed',{'url':entry['url'],'path':name,'refreshInterval':600})
        path=folder_path(entry['folder'])
        path.mkdir(parents=True,exist_ok=True)
        rule={**rules.get(name,{}),'enabled':False,'mustContain':'',
              'mustNotContain':'','useRegex':False,'smartFilter':False,'ignoreDays':0,'episodeFilter':'',
              'affectedFeeds':[entry['url']],
              'torrentParams':{'save_path':str(path),'use_auto_tmm':False,'stopped':False,'force_start':False,
                  'tags':['FjordSeed-RSS-'+entry['id']], 'ratio_limit':-1,
                  'seeding_time_limit':-1,'inactive_seeding_time_limit':-1,
                  'share_limit_action':'RemoveWithContent' if entry['ratio_action'] not in ('keep','stop_keep') else 'Stop'}}
        api('rss/setRule',{'ruleName':name,'ruleDef':json.dumps(rule)})
    active=any(e['enabled'] for e in entries)
    # All RSS additions pass through the same startup policy as manual torrents.
    api('app/setPreferences',{'json':json.dumps({'rss_processing_enabled':active,'rss_auto_downloading_enabled':False,
        'rss_refresh_interval':10})})


def sync_snapshot(root=Path('/config')):
    import fcntl
    with (root/'rss-sync.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=root/'fjord-rss.json'
        content=path.read_text() if path.exists() else '[]'
        sync_rss(json.loads(content))
        return content


def rss_report(api=call):
    items=api('rss/items?withData=true').json()
    return [{'id':name[len(PREFIX):],'has_error':item.get('hasError',False) is True,
             'articles':len(item.get('articles',[]))} for name,item in items.items()
            if name.startswith(PREFIX) and isinstance(item,dict)]
