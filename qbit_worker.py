"""Fail-closed supervisor. No qBittorrent process until the VPN is healthy."""
import configparser
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time

from qbit_rpc import call, sync_share_limits, sync_download_queue, MAX_ACTIVE_DOWNLOADS
from state import atomic
from rss import sync_rss,rss_report,sync_snapshot
from torrent_port import Lease,internal_port

STOP = threading.Event()
LOG = logging.getLogger(__name__)


def vpn_status():
    path=Path('/vpn/status.json')
    return json.loads(path.read_text()) if path.exists() else {}


def ready(root=Path('/vpn'), now=None, interfaces=None, status=None):
    now = time.time() if now is None else now
    status = json.loads((root/'status.json').read_text()) if status is None else status
    gateway=status.get('gateway_enabled') is True
    if (not status.get('healthy') or not 0 <= now - status['checked_at'] < 15
            or (status.get('relay_enabled', True) and not gateway)):
        raise ValueError('VPN is not ready')
    names = interfaces if interfaces is not None else [name for _, name in socket.if_nameindex()]
    if 'tun0' not in names:
        raise ValueError('VPN interface missing')
    port = int(status['public_port'])
    if not 1 <= port <= 65535 or port == 8080:
        raise ValueError('Invalid or conflicting port')
    return port, status.get('public_ip', ''), status.get('country', '')


def configure(port, root=Path('/config'), announce_port=0):
    folder = root / 'qBittorrent' / 'config'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'qBittorrent.conf'
    parser = configparser.RawConfigParser()
    parser.optionxform = str
    if path.exists():
        parser.read(path)
    values = {
        'LegalNotice': {'Accepted':'true'},
        'BitTorrent': {'Session\\Interface':'tun0', 'Session\\InterfaceName':'tun0',
            'Session\\InterfaceAddress':'', 'Session\\Port':str(port),
            'Session\\AnnouncePort':str(announce_port),
            'Session\\DefaultSavePath':'/downloads', 'Session\\LSDEnabled':'false',
            'Session\\QueueingSystemEnabled':'true', 'Session\\MaxActiveDownloads':str(MAX_ACTIVE_DOWNLOADS),
            'Session\\MaxActiveUploads':'-1', 'Session\\MaxActiveTorrents':'-1',
            'Session\\IgnoreSlowTorrentsForQueueing':'false'},
        'Network': {'PortForwardingEnabled':'false'},
        'Preferences': {'WebUI\\Address':'127.0.0.1', 'WebUI\\Port':'8080',
            'WebUI\\LocalHostAuth':'false', 'WebUI\\CSRFProtection':'true',
            'WebUI\\HostHeaderValidation':'true', 'WebUI\\ServerDomains':'localhost;127.0.0.1',
            'WebUI\\UseUPnP':'false', 'Connection\\UPnP':'false'},
        'AutoRun': {'enabled':'false', 'OnTorrentAdded\\Enabled':'false'},
        'RSS': {'Session\\EnableProcessing':'false','AutoDownloader\\EnableProcessing':'false'},
    }
    for section, entries in values.items():
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in entries.items():
            parser.set(section, key, value)
    import io
    output = io.StringIO()
    parser.write(output, space_around_delimiters=False)
    atomic(path, output.getvalue())


def stop_process(process, graceful=False):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(30 if graceful else 10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(3)


def sync_resume_interval(prefs, api=None):
    """Bound loss of qBittorrent's own checkpoint on an unclean restart."""
    interval=prefs.get('save_resume_data_interval')
    if type(interval) is int and interval!=1:
        (api or call)('app/setPreferences',{'json':json.dumps({'save_resume_data_interval':1})})


def run():
    process = None
    started = 0
    rss_content=None
    rss_last=0
    reports=[]
    share_last=0
    seeding_error=None
    lease=Lease()
    connection=None
    last_failure=None
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    try:
        while not STOP.is_set():
            status = {'ready':False, 'checked_at':time.time(), 'message':'Venter på beskyttet VPN-forbindelse.'}
            stage='vpn_status'
            context={}
            try:
                context=vpn_status()
                port, address, country = ready(status=context)
                # The Docker firewall is the primary kill switch. This independent
                # gate also prevents restoring torrents into an unhealthy tunnel.
                stage='vpn_health'
                with __import__('requests').Session() as client:
                    client.trust_env = False
                    response = client.get('http://127.0.0.1:9999/', timeout=2)
                    if response.status_code != 200:
                        raise ValueError('VPN health check failed')
                gateway=context.get('gateway_enabled') is True
                if gateway:
                    stage='torrent_port'
                    status['message']='Afventer gatewayens ekstra torrentport og beskyttet qBittorrent.'
                    if connection is not None and connection[2]!=address:
                        lease.close()  # A lease from the previous VPN endpoint is not reusable.
                    private,public=lease.get(port)
                    if context.get('torrent_internal_port')!=private:
                        raise ValueError('Torrentportens firewall afventer den aktuelle gatewayport.')
                    announce=public
                else:
                    lease.close();private,public,announce=port,port,0
                next_connection=(private,announce,address) if gateway else None
                if process is not None and connection!=next_connection:
                    LOG.warning('qBittorrent restarting: VPN endpoint or torrent port changed')
                    stop_process(process,graceful=True)
                    process=None
                exit_code=process.poll() if process is not None else None
                if process is None or exit_code is not None:
                    if process is not None:
                        LOG.warning('qBittorrent exited unexpectedly: returncode=%s',exit_code)
                    stage='process_start'
                    configure(private,announce_port=announce)
                    process = subprocess.Popen(['qbittorrent-nox','--profile=/config','--webui-port=8080','--confirm-legal-notice'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    started = time.monotonic()
                    rss_content=None
                    share_last=0
                    connection=next_connection
                stage='network_settings'
                try:
                    prefs = call('app/preferences').json()
                except Exception:
                    if time.monotonic() - started < 12:
                        status['message'] = 'Starter qBittorrent bag VPN…'
                    else:
                        raise
                else:
                    if prefs.get('current_network_interface') != 'tun0' or prefs.get('upnp') is not False:
                        raise ValueError('Unsafe network settings')
                    if gateway and prefs.get('announce_port')!=public:
                        raise ValueError('qBittorrent annoncerer ikke den åbne torrentport.')
                    # Private trackers need time to acknowledge stopped announces
                    # before a restart generates a new peer ID. Keep the VPN-failure
                    # termination path short; extend only normal shutdown.
                    if type(prefs.get('stop_tracker_timeout')) is int and prefs['stop_tracker_timeout'] < 10:
                        call('app/setPreferences', {'json':json.dumps({'stop_tracker_timeout':10})})
                    sync_resume_interval(prefs)
                    stage='download_queue'
                    sync_download_queue(prefs)
                    stage='listen_port'
                    if prefs.get('listen_port') != private:
                        call('app/setPreferences', {'json':json.dumps({'listen_port':private,'random_port':False,'upnp':False})})
                        if call('app/preferences').json().get('listen_port') != private:
                            raise ValueError('Port synchronization failed')
                    if time.monotonic()-share_last>10:
                        try:
                            storage_errors=sync_share_limits()
                            seeding_error=' '.join(dict.fromkeys(storage_errors)) or None
                        except Exception:
                            # A policy/read failure must not interrupt seeders.
                            # VPN failures still reach the outer kill switch.
                            seeding_error='Seedingkontrol fejlede; automatisk stop afventer næste kontrol.'
                        share_last=time.monotonic()
                    if seeding_error:
                        status['seeding_error']=seeding_error
                    try:
                        content=Path('/config/fjord-rss.json').read_text() if Path('/config/fjord-rss.json').exists() else '[]'
                        signature=content
                        if signature!=rss_content:
                            sync_snapshot()
                            rss_content=signature
                            rss_last=0
                        if time.monotonic()-rss_last>10:
                            reports=rss_report()
                            rss_last=time.monotonic()
                        status['rss']=reports
                    except Exception:
                        status['rss_error']=True
                    status.update(ready=True,port=public,public_torrent_port=public,internal_port=private,
                        torrent_mode='gateway' if gateway else 'dedicated',public_ip=address,country=country,
                        message='qBittorrent deler gatewayens VPN med sin egen åbne torrentport.' if gateway else 'qBittorrent kører gennem VPN.')
                    if seeding_error:
                        status['message']+=' '+seeding_error
            except Exception as exc:
                # Do not log exception text: HTTP errors can contain private URLs.
                # Preserve the last failure after recovery so brief restarts remain diagnosable.
                context=context if isinstance(context,dict) else {}
                stamp=context.get('checked_at')
                age=round(time.time()-stamp,1) if isinstance(stamp,(int,float)) else None
                last_failure={'at':time.time(),'stage':stage,'error_type':type(exc).__name__,
                              'vpn_status_age':age,'vpn_healthy':context.get('healthy')}
                LOG.warning('qBittorrent safety stop: %s',json.dumps(last_failure))
                status['message']='qBittorrent afventer sikker forbindelse. Kontrol fejlede: '+stage+'.'
                stop_process(process)
                process = None
                connection=None
                lease.close()
            if last_failure:
                status['last_failure']=last_failure
            atomic('/config/worker-status.json', json.dumps(status), mode=0o644)
            STOP.wait(2)
    finally:
        stop_process(process, graceful=True)
        lease.close()
        atomic('/config/worker-status.json', json.dumps({'ready':False, 'checked_at':time.time(), 'message':'Seedbox stoppet.'}), mode=0o644)


if __name__ == '__main__':
    run()
