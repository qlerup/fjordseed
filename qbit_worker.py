"""Fail-closed supervisor. No qBittorrent process until the VPN is healthy."""
import configparser
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time

from qbit_rpc import call
from state import atomic
from rss import sync_rss,rss_report

STOP = threading.Event()


def ready(root=Path('/vpn'), now=None, interfaces=None):
    now = time.time() if now is None else now
    status = json.loads((root/'status.json').read_text())
    if not status.get('healthy') or not 0 <= now - status['checked_at'] < 15 or status.get('relay_enabled', True):
        raise ValueError('VPN is not ready')
    names = interfaces if interfaces is not None else [name for _, name in socket.if_nameindex()]
    if 'tun0' not in names:
        raise ValueError('VPN interface missing')
    port = int(status['public_port'])
    if not 1 <= port <= 65535 or port == 8080:
        raise ValueError('Invalid or conflicting port')
    return port, status.get('public_ip', ''), status.get('country', '')


def configure(port, root=Path('/config')):
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
            'Session\\DefaultSavePath':'/downloads', 'Session\\LSDEnabled':'false'},
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


def stop_process(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(3)


def run():
    process = None
    started = 0
    rss_content=None
    rss_last=0
    reports=[]
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    try:
        while not STOP.is_set():
            status = {'ready':False, 'checked_at':time.time(), 'message':'Venter på beskyttet VPN-forbindelse.'}
            try:
                port, address, country = ready()
                # The Docker firewall is the primary kill switch. This independent
                # gate also prevents restoring torrents into an unhealthy tunnel.
                with __import__('requests').Session() as client:
                    client.trust_env = False
                    response = client.get('http://127.0.0.1:9999/', timeout=2)
                    if response.status_code != 200:
                        raise ValueError('VPN health check failed')
                if process is None or process.poll() is not None:
                    configure(port)
                    process = subprocess.Popen(['qbittorrent-nox','--profile=/config','--webui-port=8080','--confirm-legal-notice'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    started = time.monotonic()
                    rss_content=None
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
                    if prefs.get('listen_port') != port:
                        call('app/setPreferences', {'json':json.dumps({'listen_port':port,'random_port':False,'upnp':False})})
                        if call('app/preferences').json().get('listen_port') != port:
                            raise ValueError('Port synchronization failed')
                    try:
                        content=Path('/config/fjord-rss.json').read_text() if Path('/config/fjord-rss.json').exists() else '[]'
                        if content!=rss_content:
                            sync_rss(json.loads(content))
                            rss_content=content
                            rss_last=0
                        if time.monotonic()-rss_last>10:
                            reports=rss_report()
                            rss_last=time.monotonic()
                        status['rss']=reports
                    except Exception:
                        status['rss_error']=True
                    status.update(ready=True, port=port, public_ip=address, country=country, message='qBittorrent kører gennem VPN.')
            except Exception:
                stop_process(process)
                process = None
            atomic('/config/worker-status.json', json.dumps(status), mode=0o644)
            STOP.wait(2)
    finally:
        stop_process(process)
        atomic('/config/worker-status.json', json.dumps({'ready':False, 'checked_at':time.time(), 'message':'Seedbox stoppet.'}), mode=0o644)


if __name__ == '__main__':
    run()
