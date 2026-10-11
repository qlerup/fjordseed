"""Asynchronous, bounded local cache for public tracker posters."""
import hashlib
import queue
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests


def poster_url(value):
    if not isinstance(value, str) or len(value) > 500:
        return None
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.netloc not in ('tmdbc.org', 'image.tmdb.org')
                or url.query or url.fragment):
            return None
        pattern = r'/tmdb/t/p/' if url.netloc == 'tmdbc.org' else r'/t/p/'
        if not re.fullmatch(pattern + r'(?:w[0-9]{2,4}|original)/[A-Za-z0-9_-]+\.(?:jpg|png|webp)', url.path):
            return None
        return value
    except ValueError:
        return None


class Covers:
    TTL = 86400
    MAX_IMAGE = 2 * 1024 * 1024
    MAX_CACHE = 64 * 1024 * 1024

    def __init__(self, root):
        self.root = Path(root) / 'cover-cache'
        self.root.mkdir(exist_ok=True, mode=0o700)
        self.jobs = queue.Queue(maxsize=100)
        self.lock = threading.Lock()
        self.pending = set()
        self.retry = {}
        self.prune()

    def path(self, ident):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{64}', ident):
            return None
        path = self.root / (ident + '.img')
        return path if path.is_file() else None

    def request(self, source):
        source = poster_url(source)
        if not source:
            return None
        ident = hashlib.sha256(source.encode()).hexdigest()
        path = self.path(ident)
        now = time.time()
        try:
            stale = path is None or now - path.stat().st_mtime > self.TTL
        except FileNotFoundError:
            path = None
            stale = True
        if stale:
            with self.lock:
                if ident not in self.pending and now >= self.retry.get(ident, 0):
                    try:
                        self.jobs.put_nowait((ident, source))
                        self.pending.add(ident)
                    except queue.Full:
                        pass
        return '/api/covers/' + ident if path else None

    def download(self, ident, source):
        # No tracker credentials, arbitrary URLs, redirects or environment proxies.
        if poster_url(source) is None:
            raise ValueError('Invalid poster source')
        with requests.Session() as client:
            client.trust_env = False
            with client.get(source, timeout=(3, 5), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise ValueError('Poster unavailable')
                raw = bytearray()
                for chunk in response.iter_content(8192):
                    raw.extend(chunk)
                    if len(raw) > self.MAX_IMAGE:
                        raise ValueError('Poster too large')
        if not (raw.startswith(b'\xff\xd8\xff') or raw.startswith(b'\x89PNG\r\n\x1a\n')
                or raw[:4] == b'RIFF' and raw[8:12] == b'WEBP'):
            raise ValueError('Unsupported image')
        temporary = self.root / (ident + '.tmp')
        try:
            temporary.write_bytes(raw)
            temporary.chmod(0o600)
            temporary.replace(self.root / (ident + '.img'))
        finally:
            temporary.unlink(missing_ok=True)
        self.prune()

    def prune(self):
        files = sorted(self.root.glob('*.img'), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if time.time() - path.stat().st_mtime > 7 * self.TTL or total > self.MAX_CACHE:
                total -= path.stat().st_size
                path.unlink(missing_ok=True)

    def run(self, stop):
        while not stop.is_set():
            try:
                ident, source = self.jobs.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.download(ident, source)
            except Exception:
                with self.lock:
                    if len(self.retry) >= 1000:
                        self.retry.clear()
                    self.retry[ident] = time.time() + 300
            finally:
                with self.lock:
                    self.pending.discard(ident)
                self.jobs.task_done()
            stop.wait(.2)
