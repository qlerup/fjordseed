"""Use verified NVDEC support for each input codec; encoding stays on NVENC."""
from functools import lru_cache
from pathlib import Path
import re
import shutil
import subprocess

CODECS = {
    'h264': 'H.264/AVC', 'hevc': 'H.265/HEVC',
    'mpeg1video': 'MPEG1', 'mpeg2video': 'MPEG2', 'mpeg4': 'MPEG4',
    'vp8': 'VP8', 'vp9': 'VP9', 'vc1': 'VC-1', 'av1': 'AV1',
}


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
    return {name: {value.strip() for value in formats.split(',')}
            for name, formats in re.findall(r'^\s*([^:\r\n]+):[ \t]*([^\r\n]*)', section, re.MULTILINE)}


def select(video,executable):
    codec=CODECS.get(video.get('codec_name'))
    if not codec:return 'avsw'
    pixel=video.get('pix_fmt')
    if pixel not in ('yuv420p','yuv420p10le'):return 'avsw'
    executable=Path(shutil.which(str(executable)) or executable)
    formats=capabilities(str(executable),executable.stat().st_mtime_ns).get(codec,set())
    supported='yv12(10bit)' in formats if pixel=='yuv420p10le' else bool({'nv12','yv12'}&formats)
    return 'avhw' if supported else 'avsw'
