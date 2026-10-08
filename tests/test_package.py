from pathlib import Path
import shlex


def test_docker_copy_sources_are_in_build_context():
    root=Path(__file__).resolve().parents[1]
    allowed={line.strip()[1:].rstrip('/') for line in (root/'.dockerignore').read_text().splitlines()
             if line.startswith('!')}
    for line in (root/'Dockerfile').read_text().splitlines():
        if line.startswith('COPY '):
            for source in shlex.split(line)[1:-1]:
                assert (root/source).exists(), source
                assert source in allowed, f'{source} is excluded from Docker build context'
