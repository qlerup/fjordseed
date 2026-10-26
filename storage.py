"""Host-folder selection for future torrents; previous mounts remain available."""
import json
from pathlib import Path, PurePosixPath
import uuid

from docker.types import Mount
from state import atomic
from storage_browser import ROOTS


def buffer_enabled(streaming):
    return streaming.get('enabled',True) or streaming.get('buffer_enabled',False)


class Storage:
    def __init__(self, runtime):
        self.runtime = runtime

    def settings(self):
        return self.runtime.state.get().get('storage', {'selected':'', 'locations':[]})

    def public(self):
        settings = self.settings()
        selected = next((p for p in settings['locations'] if p['id'] == settings['selected']), None)
        path = selected['path'] if selected else str(self.runtime.host_downloads)
        enabled=buffer_enabled(self.runtime.state.get().get('streaming',{}))
        return {**settings, 'path':path, 'buffer':path.rstrip('/')+'/.incomplete' if enabled else None,
                'streaming_enabled':enabled,
                'fjordflix_enabled':self.runtime.state.get().get('streaming',{}).get('enabled',True)}

    def helper(self, action, value='', source='/'):
        r = self.runtime
        script = Path(__file__).with_name('storage_browser.py').read_text(encoding='utf-8')
        writable = action == 'writable'
        scoped = writable or action == 'usage'
        mounts=([Mount('/folder/'+str(i),path,type='bind',read_only=True) for i,path in enumerate(source)]
                if action=='temporary_usage' else
                [Mount('/folder' if scoped else '/host',source,type='bind',read_only=not writable)])
        worker = r.client.containers.create(r.image, entrypoint=['python','-c',script], command=[action,value],
            mounts=mounts,
            user=f'{r.uid}:{r.gid}' if writable else '0:0', network_disabled=True, read_only=True,
            cap_drop=['ALL'], security_opt=['no-new-privileges:true'])
        try:
            worker.start()
            status = worker.wait(timeout=30)
            result = json.loads(worker.logs().decode('utf-8').strip().splitlines()[-1])
            if status.get('StatusCode') or result.get('error'):
                raise ValueError(result.get('error') or 'Mappen kunne ikke åbnes.')
            return result
        finally:
            worker.remove(force=True)

    def temporary_usage(self, paths):
        root=self.runtime.state.root/'qbit'
        def read(name):
            path=root/name
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        entries=read('download-storage.json')
        ledger=read('green-credit.json')
        hashes={key for key,value in ledger.items() if isinstance(value,dict) and value.get('rss_feed_id')}
        for feed in ledger.get('_rss_upload',{}).get('feeds',{}).values():
            hashes.update(feed.get('downloads',{}))
        mappings={'/downloads':str(self.runtime.host_downloads)}
        mappings.update({v['bind']:k for k,v in self.mounts().items()})
        stages=[[] for _ in paths]
        for key,entry in entries.items():
            if key not in hashes:continue
            stage=PurePosixPath(entry.get('stage',''))
            for worker,host in mappings.items():
                try:relative=stage.relative_to(worker)
                except ValueError:continue
                if relative.parts and relative.parts[0] in ('.incomplete','.fjordseed-buffer') and '..' not in relative.parts:
                    stages[paths.index(host)].append(str(relative))
        return self.helper('temporary_usage',json.dumps({'rss_stages':stages,
            'selected':paths.index(self.public()['path']),
            'rss_known':bool(ledger) or not entries}),source=paths)

    def select(self, path):
        if (not isinstance(path,str) or len(path)>1024 or any(ord(c)<32 for c in path)
                or any(p in ('..','.incomplete','.fjordseed-buffer') for p in PurePosixPath(path).parts)
                or not any(path.startswith(p+'/') for p in ROOTS)):
            raise ValueError('Vælg en mediemappe under /mnt, /media eller /srv.')
        path = str(PurePosixPath(path))
        self.helper('browse',path)  # Existing directory; reject symlinks before binding.
        mount = self.helper('mount',path)
        if not mount['ready']:
            raise ValueError('Lageret skal først monteres i FjordHubs LXC.')
        self.helper('writable',source=path)  # Actual worker UID; no chmod/chown of shared media.
        r = self.runtime
        with r.state.lock:
            data = r.state.get()
            settings = self.settings()
            entry = next((p for p in settings['locations'] if p['path']==path), None)
            if entry and entry['id'] == settings['selected']:
                return self.public()
            if entry is None:
                if len(settings['locations'])>=32:
                    raise ValueError('Maksimum 32 downloadplaceringer er nået.')
                entry = {'id':uuid.uuid4().hex,'path':path}
                settings['locations'].append(entry)
            settings['selected'] = entry['id']
            data['storage'] = settings
            # Stop first, then persist: no torrent can start with stale mounts.
            r.stop(remove=True)
            atomic(r.state.path,json.dumps(data))
        return self.public()

    def mounts(self):
        return {p['path']:{'bind':'/download-locations/'+p['id'],'mode':'rw'} for p in self.settings()['locations']}

    def publish(self):
        settings = self.settings()
        path = '/download-locations/'+settings['selected'] if settings['selected'] else '/downloads'
        (self.runtime.state.root/'rpc').mkdir(exist_ok=True)
        streaming=self.runtime.state.get().get('streaming',{})
        config={'path':path,'streaming_enabled':buffer_enabled(streaming),
                'conversion_enabled':streaming.get('conversion_enabled',False),
                'conversion_bitrate':streaming.get('conversion_bitrate',20),
                'conversion_target':streaming.get('conversion_target','server')}
        if (streaming.get('enabled',True) and streaming.get('move_retained') is True
                and streaming.get('library_path') and streaming.get('host_path')==self.public()['path']):
            config['retained_library_path']=path
        atomic(self.runtime.state.root/'rpc/download-settings.json',json.dumps(config),mode=0o644)
