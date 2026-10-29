# Windows tool paths; encoding and validation live in conversion_media.py.
import json, os, sys, subprocess as _subprocess
from pathlib import Path
ROOT=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
FFPROBE=ROOT/'ffmpeg'/'bin'/'ffprobe.exe'
if not FFPROBE.exists():
    FFPROBE=ROOT/'ffmpeg-master-latest-win64-gpl'/'bin'/'ffprobe.exe'
TOOLS={'nvencc':ROOT/'NVEncC64.exe','ffprobe':FFPROBE,'mkvpropedit':ROOT/'mkvtoolnix'/'mkvpropedit.exe'}
class ProcessTools:
    @staticmethod
    def run(args,**kwargs):
        args=[str(TOOLS.get(args[0],args[0])),*args[1:]]
        kwargs.setdefault('creationflags',_subprocess.CREATE_NO_WINDOW)
        if kwargs.get('text'):
            kwargs.setdefault('encoding','utf-8')
            kwargs.setdefault('errors','replace')
        return _subprocess.run(args,**kwargs)
subprocess=ProcessTools()
# Source checkout and PyInstaller both resolve the same shared policy module.
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conversion_media import command, video, dovi, validate
from conversion_media import probe as _probe, restore_flags as _restore_flags


def probe(path):
    return _probe(path, run=subprocess.run)


def restore_flags(original,target):
    return _restore_flags(original,target, run=subprocess.run)

from conversion_media import publish_output
from conversion_media import prepare_output as _prepare_output

def prepare_output(original,target,mode='separate'):
    return _prepare_output(original,target,run=subprocess.run,mode=mode)
