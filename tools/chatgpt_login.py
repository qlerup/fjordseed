"""Fjordseed's local OAuth callback helper. Python 3, no third-party packages.

Run the command shown under AI-oversættelse in Fjordseed. Credentials remain on
the server; this helper only forwards the short-lived authorization code.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import webbrowser


def main():
    parser=argparse.ArgumentParser(description='Forbind Fjordseed med ChatGPT')
    parser.add_argument('--server',required=True); parser.add_argument('--pair',required=True)
    args=parser.parse_args(); server=args.server.rstrip('/')
    url=urlparse(server)
    if url.scheme!='https' and not(url.scheme=='http' and url.hostname in ('127.0.0.1','localhost')):
        parser.error('Brug Fjordseeds HTTPS-adresse eller en lokal SSH-tunnel (http://127.0.0.1:8099).')
    if url.username or url.password or url.query or url.fragment or url.path:
        parser.error('--server skal være en ren serveradresse uden sti.')

    def post(action,data):
        req=Request(server+'/api/subtitles/auth/'+action,data=json.dumps(data).encode(),
            headers={'Authorization':'Bearer '+args.pair,'Content-Type':'application/json'},method='POST')
        with urlopen(req,timeout=60) as response: return json.load(response)

    outcome={}; expected={}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self,*_): pass  # Never log authorization codes.
        def do_GET(self):
            parsed=urlparse(self.path); params={k:v[0] for k,v in parse_qs(parsed.query).items()}
            if parsed.path!='/auth/callback' or not secrets.compare_digest(params.get('state',''),expected['state']):
                self.send_error(400,'Invalid callback'); return
            try:
                post('complete',params); outcome['ok']=True
                message='ChatGPT er forbundet. Du kan lukke vinduet og vende tilbage til Fjordseed.'
            except Exception:
                outcome['ok']=False; message='Login kunne ikke afsluttes. Start igen i Fjordseed.'
            self.send_response(200); self.send_header('Content-Type','text/plain; charset=utf-8'); self.end_headers()
            self.wfile.write(message.encode())
    with HTTPServer(('127.0.0.1',0),Callback) as listener:
        listener.timeout=1
        prepared=post('prepare',{'redirect_uri':f'http://127.0.0.1:{listener.server_port}/auth/callback'})
        expected['state']=prepared['state']; webbrowser.open(prepared['url'])
        print('Afslut login i browseren. Venter i højst 10 minutter …')
        deadline=time.monotonic()+600
        while not outcome and time.monotonic()<deadline: listener.handle_request()
    if not outcome.get('ok'): raise SystemExit('Login blev ikke afsluttet. Start igen i Fjordseed.')
    print('ChatGPT er forbundet. Vend tilbage til Fjordseed.')


if __name__=='__main__': main()
