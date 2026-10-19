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
        return {**settings, 'path':path, 'buffer':path.rstrip('/')+'/.fjordseed-buffer' if enabled else None,
                'streaming_enabled':enabled}

    def helper(self, action, value='', source='/'):
        r = self.runtime
        script = Path(__file__).with_name('storage_browser.py').read_text(encoding='utf-8')
        writable = action == 'writable'
        worker = r.client.containers.create(r.image, entrypoint=['python','-c',script], command=[action,value],
            mounts=[Mount('/folder' if writable else '/host', source, type='bind', read_only=not writable)],
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

    def select(self, path):
        if (not isinstance(path,str) or len(path)>1024 or any(ord(c)<32 for c in path)
                or '..' in PurePosixPath(path).parts or '.fjordseed-buffer' in PurePosixPath(path).parts
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
        config={'path':path,'streaming_enabled':buffer_enabled(streaming)}
        if (streaming.get('enabled',True) and streaming.get('move_retained') is True
                and streaming.get('library_path') and streaming.get('host_path')==self.public()['path']):
            config['retained_library_path']=path
        atomic(self.runtime.state.root/'rpc/download-settings.json',json.dumps(config),mode=0o644)
