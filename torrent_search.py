"""qBittorrent search transport. Executed only in the VPN container."""
from urllib.parse import urlencode
import base64
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import requests

ENGINES = {'eztv': 'EZTV', 'limetorrents': 'LimeTorrents', 'piratebay': 'The Pirate Bay',
           'solidtorrents': 'Solid Torrents', 'torlock': 'Torlock',
           'torrentproject': 'TorrentProject', 'torrentscsv': 'Torrents.csv'}
PAGE_SIZE = 10


def plugin_metadata(row, root=Path('/config/qBittorrent/data/nova3')):
    """Resolve custom plugin links with qBittorrent's own metadata downloader."""
    name = row.get('engineName', '')
    if not re.fullmatch(r'[a-zA-Z0-9_]+', name) or not (root/'engines'/f'{name}.py').is_file():
        raise ValueError('Søgemaskinen kan ikke hente dette link.')
    from torrent_meta import torrent_meta
    with tempfile.TemporaryDirectory(prefix='fjordseed-search-') as directory:
        result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(root/'nova2dl.py'), name, row['fileUrl']],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, 'TMPDIR': directory, 'TEMP': directory, 'TMP': directory})
        if result.returncode or len(result.stdout) > 32768:
            raise ValueError('Søgemaskinen kunne ikke hente torrentfilen.')
        path = Path(result.stdout.strip().split(' ', 1)[0]).resolve()
        if not path.is_relative_to(Path(directory).resolve()) or not path.is_file():
            raise ValueError('Søgemaskinen returnerede en ugyldig fil.')
        with path.open('rb') as file:
            raw = file.read(4*1024*1024+1)
        torrent_meta(raw)
        return {'torrent': base64.b64encode(raw).decode()}


def integer(value, maximum=2147483647):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Ugyldigt søgeresultat.')
    return value


def execute(action, data, api):
    if action == 'search-plugins':
        return {'plugins': api('search/plugins').json(), 'catalog': ENGINES}
    if action == 'search-install':
        name = data.get('name')
        if not isinstance(name, str) or name not in (*ENGINES, 'all'):
            raise ValueError('Vælg en søgemaskine fra listen.')
        names = list(ENGINES) if name == 'all' else [name]
        if name == 'all':
            installed = {p['name']: p for p in api('search/plugins').json()}
            missing = [n for n in names if n not in installed]
            disabled = [n for n in names if n in installed and not installed[n].get('enabled')]
            if disabled:
                api('search/enablePlugin', {'names': '|'.join(disabled), 'enable': 'true'})
        else:
            missing = names
        if missing:
            api('search/installPlugin', {'sources': '|'.join(
                f'https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/{n}.py'
                for n in missing)})
        return {'ok': True, 'requested': names}
    if action == 'search-start':
        pattern = data.get('pattern')
        if not isinstance(pattern, str) or not 2 <= len(pattern.strip()) <= 200:
            raise ValueError('Skriv mellem 2 og 200 tegn at søge efter.')
        plugins = api('search/plugins').json()
        enabled = [p['name'] for p in plugins if p.get('enabled')]
        name = data.get('plugin', 'enabled')
        if not enabled:
            raise ValueError('Tilføj en søgemaskine først.')
        if name != 'enabled' and name not in enabled:
            raise ValueError('Søgemaskinen er ikke tilgængelig.')
        return api('search/start', {'pattern': pattern.strip(), 'plugins': name, 'category': 'all'}).json()
    ident = integer(data.get('id'))
    if action in ('search-stop', 'search-delete'):
        try:
            api('search/' + action.removeprefix('search-'), {'id': ident})
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise
        return {'ok': True}
    offset = integer(data.get('offset', 0))
    minimum = integer(data.get('min_seeders', 0), 1000000) if action == 'search-results' else 0
    # Filtering precedes pagination. Preserve each native result's index so
    # selecting a filtered row still resolves the exact original torrent.
    limit = 1 if action == 'search-resolve' else 0 if minimum else PAGE_SIZE
    native_offset = 0 if minimum else offset
    try:
        result = api('search/results?' + urlencode({'id': ident, 'offset': native_offset, 'limit': limit})).json()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise ValueError('Søgningen er udløbet, eller qBittorrent er genstartet. Start en ny søgning.') from None
        raise
    if action == 'search-results':
        if minimum:
            matches = [(index, row) for index, row in enumerate(result.get('results', []))
                       if type(row.get('nbSeeders')) is int and row['nbSeeders'] >= minimum]
            rows = [{**row, 'result_index': index} for index, row in matches[offset:offset + PAGE_SIZE]]
            return {**result, 'results': rows, 'total': len(matches),
                    'unfiltered_total': result.get('total', 0), 'min_seeders': minimum}
        rows = [{**row, 'result_index': offset + index}
                for index, row in enumerate(result.get('results', [])[:PAGE_SIZE])]
        return {**result, 'results': rows, 'unfiltered_total': result.get('total', 0), 'min_seeders': 0}
    if action == 'search-resolve':
        rows = result.get('results', [])
        if not rows:
            raise ValueError('Søgeresultatet findes ikke længere. Søg igen.')
        from rss_gate import fetch_metadata
        # Fetch only the selected result's metadata through the existing VPN
        # downloader, then use the normal manual add flow and storage policy.
        try:
            _, payload = fetch_metadata(rows[0]['fileUrl'])
        except (ValueError, requests.RequestException, OSError):
            try:
                payload = plugin_metadata(rows[0])
            except (ValueError, OSError, subprocess.SubprocessError):
                raise ValueError('Torrentlinket kunne ikke hentes. Prøv et andet resultat eller en anden søgemaskine.') from None
        return {**payload, 'name': rows[0]['fileName']}
    raise ValueError('Ukendt søgehandling.')
