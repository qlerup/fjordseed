"""Catch missing build-context allowlist entries before deployment."""
from fnmatch import fnmatchcase
from pathlib import Path
import shlex


def test_local_copy_sources_are_present_in_docker_build_context():
    root = Path(__file__).resolve().parents[1]
    rules = [line.strip() for line in (root/'.dockerignore').read_text().splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    for line in (root/'Dockerfile').read_text().splitlines():
        if not line.startswith('COPY '):
            continue
        words = shlex.split(line)
        if not words or words[0] != 'COPY' or any(w.startswith('--from=') for w in words):
            continue
        for source in words[1:-1]:
            assert (root/source).exists(), f'Docker COPY source does not exist: {source}'
            included = True
            for rule in rules:
                pattern = rule.lstrip('!').rstrip('/')
                if fnmatchcase(source.rstrip('/'), pattern):
                    included = rule.startswith('!')
            assert included, f'Docker COPY source excluded by .dockerignore: {source}'
