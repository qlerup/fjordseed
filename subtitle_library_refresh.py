"""Refresh the exact Plex item and verify Fjordflix sidecar discovery."""
import json
import time
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
import requests


class LibraryRefresh:
    def __init__(self, root):
        self.config = root/'subtitle-library.json'

    def refresh(self, relative, outputs, languages, report=lambda text:None):
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts or not path.name:
            raise ValueError('Ugyldig bibliotekssti.')
        if not self.config.exists():
            raise ValueError('SRT er gemt. Automatisk Plex/Fjordflix-opdatering er ikke konfigureret.')
        config = json.loads(self.config.read_text())
        statuses = {}
        report('Kontrollerer undertekster i Fjordflix')
        try:
            import docker
            client = docker.from_env(timeout=30)
            try:
                target = str(PurePosixPath(config['fjordflix_root'])/path)
                code = ('import json,sys; from app.sidecars import siblings; '
                        'print(json.dumps([p.name for t,p in siblings(sys.argv[1])]))')
                result = client.containers.get(config['fjordflix_container']).exec_run(['python','-c',code,target])
                if result.exit_code or not set(outputs).issubset(set(json.loads(result.output))):
                    raise ValueError('Fjordflix kan endnu ikke finde alle nye SRT-filer.')
                statuses['fjordflix'] = 'Klar · underteksterne hentes, når filmen åbnes'
            finally:
                client.close()
        except Exception:
            raise ValueError('SRT er gemt, men Fjordflix kunne ikke bekræfte filerne. Genoptag for at prøve igen.') from None
        report('Finder filmen i Plex')
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.headers['X-Plex-Token'] = config['plex_token']
                base = config['plex_url'].rstrip('/')
                def get(url, **params):
                    response=session.get(base+url,params=params,timeout=(5,20),allow_redirects=False)
                    response.raise_for_status()
                    return ET.fromstring(response.content)
                target = str(PurePosixPath(config['plex_root'])/path)
                if config.get('plex_link_url'):
                    linked=requests.post(config['plex_link_url'],json={'relative':relative,'outputs':outputs},
                        headers={'Authorization':'Bearer '+config['plex_link_secret']},timeout=(5,20),allow_redirects=False)
                    linked.raise_for_status()
                    result=linked.json();target=result.get('path','')
                    if not result.get('ok') or not target.startswith(config['plex_view_root'].rstrip('/')+'/') or '..' in PurePosixPath(target).parts:
                        raise ValueError('Plex-linket kunne ikke bekræftes.')
                ident = None
                for section in get('/library/sections').findall('Directory'):
                    if section.get('type') not in ('movie','show'):
                        continue
                    if not any(target.startswith(location.get('path','').rstrip('/')+'/') for location in section.findall('Location')):
                        continue
                    key = section.get('key','')
                    if not key.isdigit():
                        continue
                    for offset in range(0,10000,200):
                        page = get('/library/sections/'+key+'/all',type=4 if section.get('type')=='show' else 1,
                                   **{'X-Plex-Container-Start':offset,'X-Plex-Container-Size':200})
                        videos=page.findall('Video')
                        for video in videos:
                            if any(part.get('file')==target for part in video.findall('./Media/Part')):
                                ident=video.get('ratingKey');break
                        if ident or len(videos)<200:
                            break
                    if ident:
                        break
                if not ident or not ident.isdigit():
                    raise ValueError('SRT er gemt, men filmen blev ikke fundet på den forventede sti i Plex.')
                report('Plex registrerer de nye undertekster')
                response=session.put(base+'/library/metadata/'+ident+'/refresh',timeout=(5,20),allow_redirects=False)
                response.raise_for_status()
                from subtitle_text import language
                for _ in range(20):
                    metadata=get('/library/metadata/'+ident)
                    found={language(stream.get('languageCode')) for part in metadata.findall('.//Part') if part.get('file')==target
                           for stream in part.findall('Stream') if stream.get('streamType')=='3' and stream.get('key') and stream.get('codec') in ('srt','subrip')}
                    if set(languages).issubset(found):
                        statuses['plex']='Klar · nye SRT-spor registreret'
                        return statuses
                    time.sleep(2)
                raise ValueError('SRT er gemt og Plex er opdateret, men sporene er endnu ikke bekræftet. Genoptag for at kontrollere igen.')
        except (requests.RequestException,ET.ParseError,KeyError):
            raise ValueError('SRT er gemt, men Plex-opdateringen kunne ikke bekræftes. Genoptag for at prøve igen.') from None
