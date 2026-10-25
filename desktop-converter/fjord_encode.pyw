"""Local NVIDIA converter. Originals are read-only inputs; outputs never overwrite."""
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from fractions import Fraction
import encode_core as core

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'preferences.json'

class Cancelled(Exception):
    pass

def convert(source, folder, bitrate, notify, stop):
    source, folder = Path(source), Path(folder)
    if not source.is_file():
        raise ValueError('Kildefilen findes ikke.')
    if not folder.is_dir():
        raise ValueError('Vælg en eksisterende mappe til resultatet.')
    if bitrate not in (10, 15, 20, 25, 30):
        raise ValueError('Ugyldig bitrate.')
    for tool in core.TOOLS.values():
        if not tool.is_file():
            raise ValueError('Mangler værktøj: ' + str(tool))
    if shutil.disk_usage(folder).free < source.stat().st_size + 1024**3:
        raise ValueError('Der skal være mindst originalfilens størrelse + 1 GiB ledigt til konverteringen.')
    stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    target = folder / f'{source.stem[:110]}-Fjord-{bitrate}Mbps-{stamp}.mkv'
    partial = target.with_suffix('.partial.mkv')
    logfile = target.with_suffix('.log')
    started = time.monotonic()
    notify('log', str(logfile))
    notify('status', 'Undersøger video, HDR, lyd og undertekster …')
    with logfile.open('x', encoding='utf-8') as log:
        try:
            original = core.probe(source)
            if stop.is_set():
                raise Cancelled()
            args = core.command(source, partial, bitrate, original)
            args[0] = str(core.TOOLS['nvencc'])
            expected = float(original['format']['duration']) * float(Fraction(core.video(original)['avg_frame_rate']))
            log.write(json.dumps(args, ensure_ascii=False) + '\n')
            notify('status', 'Konverterer på NVIDIA-GPU …')
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace',
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            finished = threading.Event()
            def watch_cancel():
                while not finished.wait(.2):
                    if stop.is_set():
                        if process.poll() is None:
                            process.terminate()
                        return
            threading.Thread(target=watch_cancel, daemon=True).start()
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    match = re.search(r'(\d+) frames:\s*([\d.]+) fps', line)
                    if match:
                        frames, fps = int(match[1]), float(match[2])
                        remaining = max(0, (expected - frames) / max(fps, .01))
                        notify('progress', (min(99, frames / max(expected, 1) * 100), fps, remaining))
                code = process.wait()
            finally:
                finished.set()
                process.stdout.close()
                if process.poll() is None:
                    process.kill()
                    process.wait()
            if stop.is_set():
                raise Cancelled()
            if code:
                raise RuntimeError('NVEncC kunne ikke fuldføre konverteringen. Se loggen.')
            notify('status', 'Kontrollerer Dolby Vision/HDR, alle spor og kapitler …')
            core.restore_flags(original, partial)
            result = core.probe(partial)
            core.validate(original, result)
            if stop.is_set():
                raise Cancelled()
            partial.rename(target)
            seconds = time.monotonic() - started
            report = {'source': str(source), 'output': str(target), 'seconds': round(seconds, 2),
                      'video_mbps_target': bitrate, 'gpu_encoder': 'NVEncC 9.39 HEVC quality',
                      'audio_tracks': sum(s['codec_type']=='audio' for s in result['streams']),
                      'subtitle_tracks': sum(s['codec_type']=='subtitle' for s in result['streams']),
                      'dolby_vision': core.dovi(result), 'verified': True}
            target.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            notify('done', (str(target), seconds, report))
            return target
        except BaseException:
            log.write(traceback.format_exc())
            raise

def duration(seconds):
    seconds = int(seconds)
    return f'{seconds//60} min. {seconds%60:02} sek.'

from fjord_ui import ConverterUI

if __name__=='__main__':
    ConverterUI(convert, Cancelled, ROOT, CONFIG).mainloop()
