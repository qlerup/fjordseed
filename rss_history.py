"""Group archived RSS releases using their torrent titles, never feed labels."""
import re
from rss import title_key


def series_title(title):
    title = str(title or 'Ukendt titel').strip()
    # Stop at an actual season/episode or dated-release boundary. Keep the
    # original punctuation for the existing normalized substring title filter.
    boundary = re.search(r'(?i)(?:^|[ ._\-])(?:s\d{1,3}(?=e\d|[ ._\-]|$)|\d{1,3}x\d{1,3}\b|(?:season|sæson)\s*\d|20\d{2}[._-]\d{2}[._-]\d{2})', title)
    stem = title[:boundary.start()].strip(' ._-') if boundary else ''
    if not stem:
        stem = re.split(r'(?i)[ ._\-](?:2160p|1080p|720p|576p|480p|nordic|danish|swedish|norwegian|web-dl|bluray|hdtv)\b', title, maxsplit=1)[0]
        stem = re.sub(r'(?i)\.(mkv|mp4|avi|ts)$', '', stem).strip(' ._-')
    return stem or title


def grouped(items, excluded=()):
    groups = {}
    excluded_keys = {title_key(t) for t in excluded}
    for item in items:
        stem = series_title(item['title'])
        key = title_key(stem)
        group = groups.setdefault(key, {'key': key, 'title': re.sub(r'[._]+', ' ', stem),
            'exclude_title': stem, 'excluded': key in excluded_keys, 'downloads': []})
        group['downloads'].append(item)
    return sorted(groups.values(), key=lambda g: g['title'].casefold())
