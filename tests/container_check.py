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
    # A disabled native rule must still expose title matches for badge gating.
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    from rss import sync_rss, PREFIX
    class FeedHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','application/rss+xml');self.end_headers()
            self.wfile.write(('<?xml version="1.0"?><rss version="2.0"><channel><title>Fixture</title>'
                '<link>https://example.org</link><description>Fixture</description><item><title>Linux fixture</title>'
                '<guid>fixture</guid><link>magnet:?xt=urn:btih:'+'a'*40+'</link></item></channel></rss>').encode())
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),FeedHandler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    entry=dict(id='a'*32,name='Fixture',url='https://nordicbytes.org/rss',enabled=True,folder='',include='Linux',
               ratio_limit=2,ratio_action='keep',required_badges=[],min_leechers=50,tracker_id='b'*32)
    sync_rss([entry])
    name=PREFIX+entry['id']
    rule=call('rss/rules').json()[name]
    assert rule['enabled'] is False
    assert call('app/preferences').json()['rss_auto_downloading_enabled'] is False
    # Loopback fixture only; this container has no external network.
    url='http://127.0.0.1:'+str(server.server_port)+'/feed'
    call('rss/setFeedURL',{'path':name,'url':url})
    rule['affectedFeeds']=[url]
    call('rss/setRule',{'ruleName':name,'ruleDef':json.dumps(rule)})
    call('rss/refreshItem',{'itemPath':name})
    for _ in range(50):
        matches=call('rss/matchingArticles?ruleName='+name).json()
        if matches.get(name):break
        time.sleep(.2)
    assert matches[name]==['Linux fixture'],matches
    assert call('torrents/info').json()==[]
    server.shutdown()
finally:stop_process(p)
p=subprocess.Popen(['python','/app/qbit_worker.py'])
try:
    time.sleep(5)
    assert json.loads(Path('/config/worker-status.json').read_text())['ready'] is False
    processes=[(f.parent/'comm').read_text().strip() for f in Path('/proc').glob('[0-9]*/cmdline') if (f.parent/'comm').exists()]
    assert 'qbittorrent-nox' not in processes
finally:stop_process(p)
print('PASS: actual qBittorrent binding, loopback API, port update; supervisor blocks without VPN; no downloads')
