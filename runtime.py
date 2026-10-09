import json
import os
from pathlib import Path
import re
import time
import uuid

import docker

from state import atomic
from rss import write_snapshot

OWNER = 'dk.fjordseed.owner'
PROFILE = 'dk.fjordvpn.profile'
GLUETUN = 'qmcgaw/gluetun@sha256:fa19cc76b2af13d57a8d3dc3066f2ada061b1c761b8aecf989b3877c0486e027'


class Runtime:
    def __init__(self, state, client=None):
        self.state = state
        self.client = client or docker.from_env(timeout=12)
        self.parent = self.client.containers.get(os.environ['HOSTNAME'])
        self.project = self.parent.labels.get('com.docker.compose.project')
        if not self.project:
            raise RuntimeError('FjordSeed skal installeres med Docker Compose.')
        self.image = self.parent.attrs['Image']
        self.host_data = self.mount(self.parent, '/data')
        self.host_downloads = self.mount(self.parent, '/downloads')
        self.uid, self.gid = int(os.environ.get('PUID', '1000')), int(os.environ.get('PGID', '1000'))
        if self.uid < 1 or self.gid < 1:
            raise RuntimeError('qBittorrent skal køre som en almindelig bruger.')
        for name in ('qbit', 'rpc'):
            directory = state.root / name
            directory.mkdir(exist_ok=True, mode=0o700)
            os.chown(directory, self.uid, self.gid)
        atomic(state.root/'resolv.conf', 'nameserver 127.0.0.1\noptions timeout:2 attempts:2\n', mode=0o644)
        (state.root/'vpn').mkdir(exist_ok=True, mode=0o755)
        self.error = ''
        self.profiles = []

    @staticmethod
    def mount(container, destination):
        result = next((m['Source'] for m in container.attrs['Mounts']
                       if m['Destination'] == destination and m['Type'] == 'bind'), None)
        if not result or not result.startswith('/'):
            raise ValueError('Installationen mangler en gyldig datamappe.')
        return Path(result)

    @property
    def name(self):
        return 'fjordseed-' + self.state.get()['id'] + '-qbittorrent'

    def child(self):
        try:
            child = self.client.containers.get(self.name)
        except docker.errors.NotFound:
            return None
        if (child.labels.get(OWNER) != self.state.get()['id'] or
                child.labels.get('com.docker.compose.project') != self.project):
            raise ValueError('En anden installation bruger containerens navn.')
        return child

    def discover(self):
        manager = self.client.containers.get(os.environ.get('FJORDVPN_CONTAINER', 'fjordvpn'))
        if manager.status != 'running' or manager.labels.get('com.docker.compose.service') != 'app':
            raise ValueError('FjordVPN skal være startet.')
        response = manager.exec_run(['python','/app/seedbox_export.py'])
        if response.exit_code:
            raise ValueError('Opdatér FjordVPN for at bruge seedbox-integrationen.')
        result = json.loads(response.output)
        if result.get('version') != 1:
            raise ValueError('Opdatér FjordVPN.')
        profiles = result['profiles']
        if not isinstance(profiles, list) or len(profiles) > 20:
            raise ValueError('Ugyldig VPN-profilliste.')
        for p in profiles:
            if not re.fullmatch('[a-f0-9]{32}', p['id']):
                raise ValueError('Ugyldig VPN-profil.')
        self.profiles = profiles
        return manager, profiles

    def configure(self, data):
        if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
            raise ValueError('Vælg en VPN-profil og start/stop.')
        ident = data.get('profile_id', '')
        if not isinstance(ident, str) or (ident and not re.fullmatch('[a-f0-9]{32}', ident)):
            raise ValueError('Vælg en gyldig VPN-profil.')
        if data['enabled'] and not ident:
            raise ValueError('Vælg en VPN i FjordVPN først.')
        # Stopping remains possible even if FjordVPN is unavailable.
        if data['enabled']:
            _, profiles = self.discover()
            selected = next((p for p in profiles if p['id'] == ident), None)
            if not selected or selected['relay_enabled']:
                raise ValueError('Vælg en VPN-profil uden TCP-videresendelse; porten skal bruges af qBittorrent.')
        self.state.save(ident, data['enabled'])

    def stop(self, remove=False):
        child = self.child()
        if child:
            if child.status != 'exited':
                child.stop(timeout=15)
            if remove:
                child.remove()

    def reconcile(self):
        write_snapshot(self.state.root,self.uid,self.gid)
        settings = self.state.get()
        if not settings['enabled']:
            self.stop()
            self.discover()
            return
        manager, profiles = self.discover()
        p = next((p for p in profiles if p['id'] == settings['profile_id']), None)
        if not p or not p['desired'] or p['relay_enabled']:
            self.stop()
            raise ValueError('Start den valgte VPN i FjordVPN, og slå TCP-videresendelse fra.')
        vpn = self.client.containers.get('fjordvpn-' + p['id'] + '-vpn')
        if (vpn.status != 'running' or vpn.labels.get('dk.fjordvpn.managed') != '1'
                or vpn.labels.get(PROFILE) != p['id'] or
                vpn.labels.get('com.docker.compose.project') != manager.labels.get('com.docker.compose.project')):
            raise ValueError('VPN-containeren er ikke klar eller tilhører en anden installation.')
        env = dict(item.split('=',1) for item in vpn.attrs['Config']['Env'])
        if (vpn.attrs['Config']['Image'] != GLUETUN or env.get('FIREWALL','on') != 'on'
                or env.get('VPN_TYPE') != 'wireguard' or env.get('VPN_PORT_FORWARDING') != 'on'):
            raise ValueError('VPN-containeren har ikke den forventede firewall og WireGuard-opsætning.')
        # One torrent client per forwarded port. Never take over another seedbox.
        for other in self.client.containers.list(all=True, filters={'label':f'{PROFILE}={p["id"]}'}):
            if OWNER in other.labels and other.labels[OWNER] != settings['id']:
                raise ValueError('Denne VPN-profil bruges allerede af en anden seedbox.')
        child = self.child()
        generation = vpn.id + ':' + vpn.attrs['State']['StartedAt']
        atomic(self.state.root/'vpn/status.json', json.dumps({**p.get('status', {}), 'relay_enabled':p['relay_enabled']}), mode=0o644)
        if child and (child.labels.get('dk.fjordseed.vpn-generation') != generation or child.attrs['Image'] != self.image
                or self.mount(child, '/config') != self.host_data/'qbit'
                or self.mount(child, '/downloads') != self.host_downloads
                or child.attrs['Config'].get('User') != f'{self.uid}:{self.gid}'):
            self.stop(remove=True)
            child = None
        if child is None:
            labels = {OWNER:settings['id'], PROFILE:p['id'], 'dk.fjordseed.vpn-generation':generation,
                'com.docker.compose.project':self.project, 'com.docker.compose.service':'qbittorrent',
                'com.docker.compose.oneoff':'False', 'com.docker.compose.config-hash':'fjordseed-v1'}
            volumes = {str(self.host_data/'qbit'):{'bind':'/config','mode':'rw'},
                str(self.host_data/'rpc'):{'bind':'/rpc','mode':'ro'},
                str(self.host_data/'resolv.conf'):{'bind':'/etc/resolv.conf','mode':'ro'},
                str(self.host_downloads):{'bind':'/downloads','mode':'rw'},
                str(self.host_data/'vpn'):{'bind':'/vpn','mode':'ro'}}
            child = self.client.containers.create(self.image, name=self.name, labels=labels,
                command=['python','/app/qbit_worker.py'], network_mode='container:' + vpn.id,
                user=f'{self.uid}:{self.gid}', volumes=volumes, read_only=True,
                tmpfs={'/tmp':'rw,nosuid,noexec,size=32m'}, cap_drop=['ALL'],
                security_opt=['no-new-privileges:true'], init=True,
                environment={'HOME':'/config','PYTHONDONTWRITEBYTECODE':'1'},
                restart_policy={'Name':'no'}, mem_limit='1g',
                log_config=docker.types.LogConfig(type='json-file', config={'max-size':'2m','max-file':'2'}))
        if child.status != 'running':
            (self.state.root/'qbit/worker-status.json').unlink(missing_ok=True)
            child.start()

    def tick(self):
        with self.state.lock:
            try:
                self.reconcile()
                self.error = ''
            except Exception as exc:
                try:
                    self.stop()
                except Exception:
                    pass
                self.error = str(exc) if isinstance(exc, ValueError) else 'VPN eller Docker er ikke tilgængelig. qBittorrent er blokeret.'

    def status(self):
        settings = self.state.get()
        result = dict(settings, ready=False, message='Seedbox er stoppet.', profiles=self.profiles,
                      torrents=[], transfer={}, download_path=str(self.host_downloads))
        if self.error:
            result['message'] = self.error
        elif settings['enabled']:
            result['message'] = 'Venter på VPN og qBittorrent.'
            try:
                status = json.loads((self.state.root/'qbit/worker-status.json').read_text())
                child = self.child()
                if child and child.status == 'running' and 0 <= time.time()-status['checked_at'] < 10:
                    result.update(status)
                    if result.get('ready'):
                        result.update(self.rpc('status', {}))
            except Exception:
                result.update(ready=False, message='Venter på sikker forbindelse til qBittorrent.')
        return result

    def rpc(self, action, data):
        child = self.child()
        if not child or child.status != 'running':
            raise ValueError('qBittorrent er ikke startet.')
        # RPC has no host ports or direct network path from the web application.
        ident = uuid.uuid4().hex
        path = self.state.root/'rpc'/(ident+'.json')
        try:
            atomic(path, json.dumps({'action':action,'data':data}), mode=0o644)
            result = child.exec_run(['python','/app/qbit_rpc.py',ident])
            if result.exit_code:
                try:
                    failure=json.loads(result.output)
                    if failure.get('code')=='seeding_requirement':
                        raise ValueError(failure['error'])
                except (json.JSONDecodeError,KeyError,TypeError):
                    pass
                raise ValueError('qBittorrent kunne ikke udføre handlingen. Kontrollér VPN og torrentfil.')
            return json.loads(result.output)
        finally:
            path.unlink(missing_ok=True)
