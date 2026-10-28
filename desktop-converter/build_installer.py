"""Build a per-user installer from the app and checksum-pinned vendor archives.

Never package an existing installation: it contains pairing tokens and preferences.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

VERSION = '0.5.2'
ROOT = Path(__file__).resolve().parent
FORBIDDEN = {'worker-settings.json', 'preferences.json', 'client-state.json'}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def archive_for(tool, cache):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / tool['file']
    if not target.exists():
        temporary = target.with_suffix(target.suffix + '.partial')
        urllib.request.urlretrieve(tool['url'], temporary)
        if sha256(temporary) != tool['sha256']:
            temporary.unlink()
            raise ValueError('Checksum mismatch for downloaded ' + tool['file'])
        temporary.replace(target)
    if sha256(target) != tool['sha256']:
        raise ValueError('Checksum mismatch for cached ' + tool['file'])
    return target


def validate_payload(payload):
    for relative in ('Fjord-konvertering.exe', 'fjord.ico', 'NVEncC64.exe',
                     'ffmpeg/bin/ffprobe.exe', 'ffmpeg/bin/ffmpeg.exe', 'mkvtoolnix/mkvpropedit.exe'):
        if not (payload / relative).is_file():
            raise ValueError('Installer payload is missing ' + relative)
    for path in payload.rglob('*'):
        if path.is_symlink() or path.name.lower() in FORBIDDEN or path.name.lower().startswith('client-state'):
            raise ValueError('User settings or links must never be included in the installer')


def build(compiler, archives, output, executable=None, version=VERSION):
    if os.name != 'nt':
        raise RuntimeError('The installer is built on Windows.')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a three-part numeric app version.')
    compiler = Path(compiler).resolve()
    if not compiler.is_file():
        raise ValueError('Pass the path to the Inno Setup ISCC.exe compiler.')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='fjord-installer-build-')).resolve()
    try:
        payload = work / 'payload'
        payload.mkdir()
        if executable:
            shutil.copy2(executable, payload / 'Fjord-konvertering.exe')
        else:
            from build_windows import build as build_executable
            build_executable(payload)
        shutil.copy2(ROOT / 'fjord.ico', payload / 'fjord.ico')
        tools = json.loads((ROOT / 'tools.json').read_text(encoding='utf-8'))
        for name in ('nvenc', 'ffmpeg', 'mkvtoolnix'):
            archive = archive_for(tools[name], Path(archives).resolve())
            destination = payload / 'ffmpeg' if name == 'ffmpeg' else payload
            destination.mkdir(exist_ok=True)
            command = ['tar.exe', '-xf', str(archive), '-C', str(destination)]
            if name == 'ffmpeg':
                command.append('--strip-components=1')
            subprocess.run(command, check=True)
        shutil.copy2(ROOT / 'tools.json', payload / 'toolchain-sources.json')
        validate_payload(payload)
        subprocess.run([str(compiler), '/Qp', '/DPayloadDir=' + str(payload), '/DMyAppVersion=' + version,
                        '/O' + str(work / 'dist'), str(ROOT / 'installer.iss')], check=True)
        installer = output / 'Fjord-konvertering-Setup.exe'
        shutil.copy2(work / 'dist' / installer.name, installer)
        installer.with_suffix('.exe.sha256').write_text(sha256(installer) + '  ' + installer.name + '\n', encoding='ascii')
        print('Built installer: ' + str(installer), flush=True)
        return installer
    finally:
        if work.parent == Path(tempfile.gettempdir()).resolve() and work.name.startswith('fjord-installer-build-'):
            shutil.rmtree(work)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--archives', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--exe')
    parser.add_argument('--version', default=VERSION)
    arguments = parser.parse_args()
    build(arguments.compiler, arguments.archives, arguments.output_dir, arguments.exe, arguments.version)
