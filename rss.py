"""Persist RSS rules and apply them inside qBittorrent's VPN namespace."""
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time
from urllib.parse import urlsplit
import uuid

from qbit_rpc import share_policy, call
from state import atomic

PREFIX='FjordSeed-'


def folder_path(folder, root=Path('/downloads')):
    if (not isinstance(folder,str) or len(folder)>240 or folder.startswith('/') or '\\' in folder
            or any(part in ('.','..') for part in folder.split('/')) or any(ord(c)<32 for c in folder)):
        raise ValueError('Vælg en undermappe i din downloadmappe, fx serier eller film/freeleech.')
    folder=folder.strip().strip('/')
    path=root / PurePosixPath(folder)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Mappen ligger uden for downloadplaceringen.')
    return path


def validate_feed(data):
    if not isinstance(data,dict):
        raise ValueError('Ugyldigt RSS-feed.')
    name=data.get('name','')
    url=data.get('url','')
    include=data.get('include','')
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
    if type(data.get('enabled')) is not bool or not isinstance(include,str) or len(include)>200:
        raise ValueError('Vælg automatisk download og et gyldigt titelfilter.')
    folder=data.get('folder','')
    folder_path(folder)
    policy=share_policy(data)
    if policy['ratio_limit']<0:
        raise ValueError('Vælg en stop-ratio fra 0 til 10000.')
    return {'name':name.strip(),'url':url,'folder':folder.strip().strip('/'),
            'enabled':data['enabled'],'include':include.strip(),**policy}


class Rss:
    def __init__(self,root,downloads=Path('/downloads')):
        self.root=root
        self.path=root/'rss.json'
        self.downloads=downloads
        self.lock=threading.RLock()
        if not self.path.exists():
            atomic(self.path,'[]')
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
            if not data.get('url') and existing:
                data['url']=existing['url']
            feed=validate_feed(data)
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
        return {'feeds':[{k:v for k,v in e.items() if k!='url'} | {
                'host':urlsplit(e['url']).hostname,'has_url':True,
                'status':('paused' if not e['enabled'] else 'pending' if not state else
                          'error' if state.get('rss_error') or reports.get(e['id'],{}).get('has_error') else
                          'active' if e['id'] in reports else 'pending'),
                'articles':reports.get(e['id'],{}).get('articles',0)} for e in entries]}


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
        rule={**rules.get(name,{}),'enabled':entry['enabled'],'mustContain':entry['include'],
              'mustNotContain':'','useRegex':False,'smartFilter':False,'affectedFeeds':[entry['url']],
              'torrentParams':{'save_path':str(path),'use_auto_tmm':False,'stopped':False,
                  'tags':['FjordSeed-RSS-'+entry['id']], 'ratio_limit':entry['ratio_limit'],
                  'seeding_time_limit':-1,'inactive_seeding_time_limit':-1,
                  'share_limit_action':'RemoveWithContent' if entry['ratio_action']=='delete' else 'Stop'}}
        api('rss/setRule',{'ruleName':name,'ruleDef':json.dumps(rule)})
    active=any(e['enabled'] for e in entries)
    api('app/setPreferences',{'json':json.dumps({'rss_processing_enabled':active,'rss_auto_downloading_enabled':active,
        'rss_refresh_interval':10})})


def rss_report(api=call):
    items=api('rss/items?withData=true').json()
    return [{'id':name[len(PREFIX):],'has_error':item.get('hasError',False) is True,
             'articles':len(item.get('articles',[]))} for name,item in items.items()
            if name.startswith(PREFIX) and isinstance(item,dict)]
