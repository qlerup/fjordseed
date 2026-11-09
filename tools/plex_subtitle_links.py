"""Small authenticated LAN bridge for the existing Plex symlink library.

Only creates missing SRT links for a video already owned by sync_library.py.
Never removes, replaces or renames existing library content.
"""
import json
import os
from pathlib import Path, PurePosixPath
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOURCE=Path('/srv/fjordflix-media')
VIEW=Path('/srv/fjordflix-library')
LEDGER=Path('/var/lib/plex-library-sync/links.json')
CONFIG=Path('/etc/fjordseed-subtitle-links.json')


def ensure_links(relative, outputs):
    part=PurePosixPath(relative)
    if part.is_absolute() or '..' in part.parts or not part.name:
        raise ValueError('Ugyldig filmsti.')
    source=(SOURCE/relative).resolve(strict=True)
    if not source.is_relative_to(SOURCE.resolve()) or not source.is_file():
        raise ValueError('Filmen findes ikke i mediebiblioteket.')
    # An empty list resolves a newly indexed video's Plex path for a library scan.
    if not isinstance(outputs,list) or not 0<=len(outputs)<=30:
        raise ValueError('Ugyldig undertekstliste.')
    ledger=json.loads(LEDGER.read_text())
    candidates=[VIEW/name for name,target in ledger.items() if target==str(source)]
    candidates=[p for p in candidates if p.parent.resolve().is_relative_to(VIEW.resolve()) and p.is_symlink() and p.resolve()==source]
    if len(candidates)!=1:
        raise ValueError('Filmen har endnu ikke ét entydigt link i Plex-biblioteket.')
    video=candidates[0]
    for filename in outputs:
        if not isinstance(filename,str) or PurePosixPath(filename).name!=filename or not filename.startswith(source.stem+'.') or not filename.endswith('.srt'):
            raise ValueError('Undertekstens filnavn passer ikke til filmen.')
        sidecar=source.parent/filename
        if sidecar.is_symlink() or not sidecar.is_file() or not sidecar.resolve().is_relative_to(SOURCE.resolve()):
            raise ValueError('Underteksten findes ikke ved filmen.')
        link=video.with_name(video.stem+filename[len(source.stem):])
        if link.is_symlink():
            if link.resolve()!=sidecar.resolve():
                raise ValueError('Plex har allerede en anden undertekst med samme navn.')
        elif link.exists():
            raise ValueError('En eksisterende Plex-fil må ikke overskrives.')
        else:
            try:link.symlink_to(sidecar)
            except FileExistsError:
                if not link.is_symlink() or link.resolve()!=sidecar.resolve():raise
    return str(video)


def main():
    config=json.loads(CONFIG.read_text())
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            expected='Bearer '+config['secret']
            if self.path!='/subtitles/link' or not secrets.compare_digest(self.headers.get('Authorization',''),expected):
                self.send_error(403);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=32768:raise ValueError('Ugyldig forespørgsel.')
                data=json.loads(self.rfile.read(length))
                video=ensure_links(data['relative'],data['outputs'])
                result={'ok':True,'path':video};status=200
            except Exception:
                result={'ok':False,'error':'Plex-linkene kunne ikke opdateres. Kontrollér filmens placering og eksisterende undertekster.'};status=409
            body=json.dumps(result).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer((config.get('bind','127.0.0.1'),config.get('port',32401)),Handler)
    server.serve_forever()


if __name__=='__main__':main()
