import json
import os
from pathlib import Path
import re
import time
import uuid
from types import SimpleNamespace

import docker

from state import atomic
from rss import write_snapshot
from storage import Storage
from torrent_port import internal_port

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
            if not selected or (selected['relay_enabled'] and selected.get('gateway_enabled') is not True):
                raise ValueError('Vælg en VPN-profil uden TCP-videresendelse; porten skal bruges af qBittorrent.')
        self.state.save(ident, data['enabled'])

    def stop(self, remove=False):
        child = self.child()
        if child:
            if child.status != 'exited':
                child.stop(timeout=40)
            if remove:
                child.remove()
        ledger=self.state.root/'torrent-firewall.json'
        if ledger.exists():
            self.clear_torrent_rules(SimpleNamespace(labels=json.loads(ledger.read_text())))
            ledger.unlink()
        elif child and child.labels.get('dk.fjordseed.torrent-mode')=='gateway':
            self.clear_torrent_rules(child)

    def torrent_rules(self,vpn,port,remove=False):
        """Open only this seedbox's second port on the protected VPN interface."""
        marker='fjordseed-'+self.state.get()['id']
        added=[]
        for protocol in ('tcp','udp'):
            args=['-i','tun0','-p',protocol,'--dport',str(port),'-m','comment','--comment',marker,'-j','ACCEPT']
            check=vpn.exec_run(['iptables','-C','INPUT',*args])
            if check.exit_code not in (0,1):
                raise ValueError('Torrentportens VPN-firewall kunne ikke kontrolleres.')
            if (remove and check.exit_code==0) or (not remove and check.exit_code==1):
                operation='-D' if remove else '-I'
                result=vpn.exec_run(['iptables',operation,'INPUT',*args])
                if result.exit_code:
                    for previous in added:
                        vpn.exec_run(['iptables','-D','INPUT',*previous])
                    raise ValueError('Torrentportens VPN-firewall kunne ikke opdateres.')
                if not remove:added.append(args)

    def clear_torrent_rules(self,child):
        if not re.fullmatch('[a-f0-9]{32}',child.labels.get(PROFILE,'')):
            raise ValueError('Torrentportens VPN-profil er ugyldig.')
        try:
            vpn=self.client.containers.get('fjordvpn-'+child.labels[PROFILE]+'-vpn')
        except docker.errors.NotFound:
            return
        if (vpn.labels.get('dk.fjordvpn.managed')!='1' or vpn.labels.get(PROFILE)!=child.labels[PROFILE]
                or vpn.labels.get('com.docker.compose.project')!=child.labels.get('dk.fjordseed.vpn-project')):
            raise ValueError('Torrentportens VPN tilhører en anden installation.')
        port=int(child.labels['dk.fjordseed.torrent-internal-port'])
        if port not in (56789,56790):
            raise ValueError('Torrentportens registrering er ugyldig.')
        if vpn.status=='running':
            self.torrent_rules(vpn,port,remove=True)

    def reconcile(self):
        storage = Storage(self)
        storage.ensure_seeder()
        storage.publish()
        write_snapshot(self.state.root,self.uid,self.gid)
        settings = self.state.get()
        if not settings['enabled']:
            self.stop()
            self.discover()
            return
        manager, profiles = self.discover()
        p = next((p for p in profiles if p['id'] == settings['profile_id']), None)
        gateway=bool(p and p.get('gateway_enabled') is True)
        if not p or not p['desired'] or (p['relay_enabled'] and not gateway):
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
        mode='gateway' if gateway else 'dedicated'
        try:private=internal_port(p['status']['public_port']) if gateway else 0
        except (ValueError,TypeError,KeyError):private=56789 if gateway else 0
        if child and (child.labels.get('dk.fjordseed.vpn-generation') != generation or child.attrs['Image'] != self.image
                or child.labels.get('dk.fjordseed.torrent-mode','dedicated')!=mode
                or (gateway and child.labels.get('dk.fjordseed.torrent-internal-port')!=str(private))
                or self.mount(child, '/config') != self.host_data/'qbit'
                or self.mount(child, '/downloads') != self.host_downloads
                or child.attrs['Config'].get('User') != f'{self.uid}:{self.gid}'
                or any(not any(m.get('Destination')==v['bind'] and m.get('Source')==p and m.get('RW',True)
                    for m in child.attrs['Mounts']) for p,v in storage.mounts().items())):
            self.stop(remove=True)
            child = None
        # Publish the new profile only after a previous namespace has stopped.
        # Otherwise its worker could announce the new profile's endpoint early.
        atomic(self.state.root/'vpn/status.json', json.dumps({**p.get('status', {}),
            'relay_enabled':p['relay_enabled'],'gateway_enabled':gateway,
            'torrent_internal_port':private}), mode=0o644)
        if gateway:
            atomic(self.state.root/'torrent-firewall.json',json.dumps({PROFILE:p['id'],
                'dk.fjordseed.torrent-internal-port':str(private),
                'dk.fjordseed.vpn-project':manager.labels.get('com.docker.compose.project','')}))
            self.torrent_rules(vpn,private)
        if child is None:
            labels = {OWNER:settings['id'], PROFILE:p['id'], 'dk.fjordseed.vpn-generation':generation,
                'com.docker.compose.project':self.project, 'com.docker.compose.service':'qbittorrent',
                'com.docker.compose.oneoff':'False', 'com.docker.compose.config-hash':'fjordseed-v1'}
            labels.update({'dk.fjordseed.torrent-mode':mode,'dk.fjordseed.torrent-internal-port':str(private),
                           'dk.fjordseed.vpn-project':manager.labels.get('com.docker.compose.project','')})
            volumes = {str(self.host_data/'qbit'):{'bind':'/config','mode':'rw'},
                str(self.host_data/'rpc'):{'bind':'/rpc','mode':'ro'},
                str(self.host_data/'resolv.conf'):{'bind':'/etc/resolv.conf','mode':'ro'},
                str(self.host_downloads):{'bind':'/downloads','mode':'rw'},
                str(self.host_data/'vpn'):{'bind':'/vpn','mode':'ro'}}
            child = self.client.containers.create(self.image, name=self.name, labels=labels,
                command=['python','/app/qbit_worker.py'], network_mode='container:' + vpn.id,
                user=f'{self.uid}:{self.gid}', mounts=[docker.types.Mount(v['bind'],p,type='bind',read_only=v['mode']=='ro')
                    for p,v in [*volumes.items(),*storage.mounts().items()]], read_only=True,
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
            try:
                from converter_runtime import sync
                sync(self)
                self.conversion_error=''
            except Exception:
                self.conversion_error='GPU-workeren kunne ikke klargøres. Kontrollér GPU-installation og bufferens rettigheder.'

    def status(self):
        settings = self.state.get()
        result = dict(settings, ready=False, message='Seedbox er stoppet.', profiles=self.profiles,
                      torrents=[], torrents_available=False, transfer={}, download_path=Storage(self).public()['path'])
        result['conversion_error']=getattr(self,'conversion_error','')
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
                        result['torrents_available']=True
                        if status.get('torrent_mode')=='gateway':
                            result['port']=status['public_torrent_port']
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
            if action=='library-shared-complete':
                verification_client=docker.from_env(timeout=600)
                try:result=verification_client.containers.get(child.id).exec_run(['python','/app/qbit_rpc.py',ident])
                finally:verification_client.close()
            else:result = child.exec_run(['python','/app/qbit_rpc.py',ident])
            if result.exit_code:
                try:
                    failure=json.loads(result.output)
                    if action.startswith('library-'):
                        raise ValueError(failure['error'])
                    if failure.get('code')=='seeding_requirement':
                        raise ValueError(failure['error'])
                except (json.JSONDecodeError,KeyError,TypeError):
                    pass
                raise ValueError('qBittorrent kunne ikke udføre handlingen. Kontrollér VPN og torrentfil.')
            return json.loads(result.output)
        finally:
            path.unlink(missing_ok=True)
