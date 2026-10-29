"""Prefer verified NVDEC support over FFmpeg's HEVC software decoder."""
from functools import lru_cache
from pathlib import Path
import re
import shutil
import subprocess


@lru_cache(maxsize=4)
def capabilities(executable,modified):
    try:
        result=subprocess.run([executable,'--check-features'],capture_output=True,text=True,
            encoding='utf-8',errors='replace',check=True,timeout=15,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.SubprocessError) as exc:
        raise ValueError('NVIDIAs afkodningsfunktioner kunne ikke kontrolleres. Konverteringen er ikke startet.') from exc
    # Encoder capabilities elsewhere in this output do not establish NVDEC support.
    section=result.stdout.partition('NVDec features')[2]
    match=re.search(r'^\s*H\.265/HEVC:\s*([^\r\n]+)',section,re.MULTILINE)
    return {value.strip() for value in match[1].split(',')} if match else set()


def select(video,executable):
    if video.get('codec_name')!='hevc':return 'avsw'
    pixel=video.get('pix_fmt')
    if pixel not in ('yuv420p','yuv420p10le'):return 'avsw'
    executable=Path(shutil.which(str(executable)) or executable)
    formats=capabilities(str(executable),executable.stat().st_mtime_ns)
    supported='yv12(10bit)' in formats if pixel=='yuv420p10le' else bool({'nv12','yv12'}&formats)
    return 'avhw' if supported else 'avsw'
