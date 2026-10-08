"""Run inside the built image, with --network none and writable /config."""
import json
from pathlib import Path
import subprocess
import time
import sys
sys.path.insert(0,'/app')
from qbit_worker import configure, stop_process
from qbit_rpc import call, execute

configure(45001)
p=subprocess.Popen(['qbittorrent-nox','--profile=/config','--webui-port=8080','--confirm-legal-notice'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            prefs=call('app/preferences').json()
            break
        except Exception:time.sleep(.2)
    assert prefs['current_network_interface']=='tun0'
    assert prefs['listen_port']==45001 and prefs['upnp'] is False
    assert prefs['web_ui_address']=='127.0.0.1' and prefs['save_path']=='/downloads'
    call('app/setPreferences',{'json':json.dumps({'listen_port':45002})})
    assert call('app/preferences').json()['listen_port']==45002
    assert execute('status',{})['torrents']==[]
finally:stop_process(p)
p=subprocess.Popen(['python','/app/qbit_worker.py'])
try:
    time.sleep(5)
    assert json.loads(Path('/config/worker-status.json').read_text())['ready'] is False
    processes=[(f.parent/'comm').read_text().strip() for f in Path('/proc').glob('[0-9]*/cmdline') if (f.parent/'comm').exists()]
    assert 'qbittorrent-nox' not in processes
finally:stop_process(p)
print('PASS: actual qBittorrent binding, loopback API, port update; supervisor blocks without VPN; no downloads')
