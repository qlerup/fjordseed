"""Bounded audio cross-correlation and disposable two-film preview clips."""
import json
import math
from pathlib import Path
import re
import subprocess
import time

import numpy as np

import merge_media as merge
from state import atomic

RATE = 4000
SEARCH = 120
ASSETS = ('base.mp4', 'donor.m4a')


def correlate(reference, search):
    """Find a complete reference window in search; reject silence/repeated peaks."""
    a = np.asarray(reference, dtype=np.float64)
    b = np.asarray(search, dtype=np.float64)
    if len(a) < RATE or len(b) < len(a): return None
    a = a-a.mean()
    energy = float(a@a)
    if energy/len(a) < 1e-9: return None
    size = 1 << (len(a)+len(b)-2).bit_length()
    dots = np.fft.irfft(np.fft.rfft(b, size)*np.fft.rfft(a[::-1], size), size)[len(a)-1:len(b)]
    sums = np.concatenate(([0.], np.cumsum(b)))
    squares = np.concatenate(([0.], np.cumsum(b*b)))
    variances = np.maximum(0, squares[len(a):]-squares[:-len(a)]-(sums[len(a):]-sums[:-len(a)])**2/len(a))
    scores = np.zeros_like(dots)
    valid = variances > len(a)*1e-9
    scores[valid] = np.clip(np.abs(dots[valid])/np.sqrt(energy*variances[valid]), 0, 1)
    peak = int(np.argmax(scores)); score = float(scores[peak])
    # A periodic tone or repeated music must not look like a unique match.
    scores[max(0, peak-RATE//2):peak+RATE//2+1] = 0
    runner_up = float(scores.max())
    return {'sample': peak, 'score': round(score, 4), 'separation': round(score-runner_up, 4),
            'trusted': score >= .35 and score-runner_up >= .06}


def envelope(samples):
    width = RATE//100
    samples = np.asarray(samples, dtype=np.float64)
    usable = len(samples)//width*width
    if not usable: return []
    levels = np.sqrt(np.mean(samples[:usable].reshape(-1, width)**2, axis=1))
    scale = max(float(np.quantile(levels, .98)), 1e-8)
    return np.round(np.clip(levels/scale, 0, 1), 3).tolist()


def audio_index(source, ident):
    tracks = [t for t in source[2]['tracks'] if t['type'] == 'audio']
    if ident is None and not tracks: return None
    if type(ident) is not int: raise ValueError('Vælg et lydspor fra hver film til sammenligning.')
    found = next((i for i, track in enumerate(tracks) if track['id'] == ident), None)
    if found is None: raise ValueError('Det valgte sammenligningsspor findes ikke.')
    return found


def duration(source):
    value = source[2].get('container', {}).get('properties', {}).get('duration', 0)/1e9
    if not math.isfinite(value) or value < 3: raise ValueError('Filmens varighed kunne ikke læses.')
    return value


def pcm(path, track, start, length):
    # Preserve absolute source timestamps. Raw output otherwise silently drops
    # partial/negative audio packets, introducing e.g. a 32 ms AC-3 frame error.
    filters = (f'aresample={RATE},aresample=async=1:first_pts={round(start*RATE)},'
               f'atrim=duration={length:.6f},asetpts=PTS-STARTPTS')
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-threads', '2', '-ss', f'{max(0, start-2):.6f}', '-copyts', '-i', str(path),
            '-t', f'{length:.6f}', '-map', f'0:a:{track}', '-vn', '-sn', '-dn', '-af', filters, '-ac', '1', '-ar', str(RATE),
            '-c:a', 'pcm_s16le', '-f', 's16le', 'pipe:1']
    result = subprocess.run(args, capture_output=True, timeout=120)
    if result.returncode: raise ValueError('Lydsporet kunne ikke læses til sammenligning.')
    if len(result.stdout) > (length+1)*RATE*2: raise ValueError('Lydprøven overskrider grænsen.')
    return np.frombuffer(result.stdout, dtype='<i2').astype(np.float64)/32768


def report(directory, text, progress, **fields):
    atomic(directory/'progress.json', json.dumps({'detail': text, 'progress': progress, 'updated_at': time.time(), **fields}), mode=0o644)


def encode(args, target, timeout, stage, length):
    path = target.parent/(stage+'.ffmpeg')
    path.unlink(missing_ok=True)
    detail = 'Laver hovedfilens prøveklip' if stage == 'video' else 'Klargør det nye lydspor'
    report(target.parent, detail, None, stage=stage, stage_index=1 if stage == 'video' else 2,
           stage_total=3, duration=length, stage_started_at=time.time(), progress_file=path.name)
    args = [args[0], '-progress', str(path), '-stats_period', '1', '-nostats', *args[1:]]
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode or not target.exists():
        raise ValueError('Prøveklippet kunne ikke laves. Prøv et andet tidspunkt.' if stage == 'video' else
                         'Det nye lydspor kunne ikke klargøres til prøven.')


def analyse(sources, tracks, offset, directory):
    if any(track is None for track in tracks): raise ValueError('Automatisk match kræver lyd i begge filer.')
    lengths = [duration(source) for source in sources]
    window = min(30., min(lengths)/5)
    rows = []; wave = None
    for index, fraction in enumerate((.12, .5, .85)):
        start = min(lengths[0]-window, lengths[0]*fraction)
        report(directory, f'Sammenligner lyd · sted {index+1} af 3', index*30+5)
        donor_start = max(0., start-offset/1000-SEARCH)
        donor_end = min(lengths[1], start-offset/1000+window+SEARCH)
        row = {'time': round(start, 3), 'offset_ms': None, 'score': 0, 'trusted': False}
        if donor_end-donor_start >= window:
            base = pcm(sources[0][1], tracks[0], start, window)
            donor = pcm(sources[1][1], tracks[1], donor_start, donor_end-donor_start)
            match = correlate(base, donor)
            if match:
                row.update({k: match[k] for k in ('score', 'trusted', 'separation')})
                row['offset_ms'] = round((start-donor_start-match['sample']/RATE)*1000)
                if wave is None or match['score'] > wave['score']:
                    lo = max(0, match['sample']-4*RATE)
                    hi = min(len(donor), match['sample']+len(base)+4*RATE)
                    wave = {'score': match['score'], 'rate': 100, 'base_start': start,
                            'donor_start': donor_start+lo/RATE, 'base': envelope(base), 'donor': envelope(donor[lo:hi])}
        rows.append(row)
    trusted = [row['offset_ms'] for row in rows if row['trusted']]
    spread = max(trusted)-min(trusted) if trusted else None
    reliable = len(trusted) >= 2 and spread <= 40
    suggested = round(float(np.median(trusted))) if trusted else None
    # Three genuinely different locations are needed before calling a short clip reliable.
    if len({row['time'] for row in rows if row['trusted']}) < 2: reliable = False
    status = 'matched' if reliable else 'drift' if len(trusted) >= 2 else 'uncertain'
    return {'kind': 'analyse', 'status': status, 'reliable': reliable, 'offset_ms': suggested,
            'spread_ms': spread, 'samples': rows, 'waveform': wave, 'search_seconds': SEARCH,
            'detail': ('Lydsporene matcher flere steder. Kontrollér med prøveklippet.' if reliable else
                       'Forskydningen ændrer sig gennem filmen. En fast forskydning kan ikke synkronisere alle de målte steder.' if status == 'drift' else
                       'Ingen sikker forskydning fundet. Vælg samme sprog, prøv et andet lydspor, eller justér manuelt.')}


def clip(source, audio, start, length, target):
    # Detailed SDR/H.264 copies are only for the browser; final merges copy originals.
    video = next((s for s in merge.workflow.media_info(source[1]).get('streams', [])
                  if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), {})
    filters = "scale=w='min(1920,iw)':h='min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,format=yuv420p"
    if video.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
        filters = 'zscale=t=linear:npl=100,format=gbrpf32le,tonemap=hable,zscale=p=bt709:t=bt709:m=bt709:r=tv,'+filters
    filters = f'trim=start={start:.6f}:duration={length:.6f},setpts=PTS-{start:.6f}/TB,'+filters
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '2', '-filter_threads', '2', '-ss', f'{max(0, start-2):.6f}', '-copyts', '-i', str(source[1]),
            '-t', f'{length:.6f}', '-map', '0:V:0', '-sn', '-dn', '-map_metadata', '-1', '-vf', filters,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-threads', '2', '-pix_fmt', 'yuv420p']
    if audio is None: args += ['-an']
    else:
        audio_filter = (f'aresample=48000,aresample=async=1:first_pts={round(start*48000)},'
                        f'atrim=duration={length:.6f},asetpts=PTS-STARTPTS')
        args += ['-map', f'0:a:{audio}', '-af', audio_filter, '-c:a', 'aac', '-b:a', '128k', '-ac', '2']
    args += ['-movflags', '+faststart', str(target)]
    encode(args, target, 720, 'video', length)


def audio_clip(source, audio, start, length, target):
    filters = (f'aresample=48000,aresample=async=1:first_pts={round(start*48000)},'
               f'atrim=duration={length:.6f},asetpts=PTS-STARTPTS')
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '2', '-ss', f'{max(0, start-2):.6f}',
            '-copyts', '-i', str(source[1]), '-t', f'{length:.6f}', '-map', f'0:a:{audio}', '-vn', '-sn', '-dn',
            '-af', filters, '-c:a', 'aac', '-b:a', '320k', '-ac', '2', '-map_metadata', '-1',
            '-movflags', '+faststart', str(target)]
    encode(args, target, 120, 'audio', length)


def preview(sources, tracks, offset, data, directory):
    if tracks[1] is None or data.get('donor_audio') not in sources[1][3]:
        raise ValueError('Vælg et lydspor fra den anden fil til fletningen, og brug det i prøven.')
    start = data.get('start', 60)
    lengths = [duration(source) for source in sources]
    if type(start) not in (int, float) or not 0 <= start < lengths[0]-1 or not math.isfinite(start):
        raise ValueError('Vælg et tidspunkt inden for hovedfilens varighed.')
    requested_length = data.get('length', 15)
    if type(requested_length) is not int or not 5 <= requested_length <= 120:
        raise ValueError('Vælg en prøvelængde på 5 til 120 hele sekunder.')
    length = min(float(requested_length), lengths[0]-start)
    aligned = start-offset/1000
    if aligned+length <= 0 or aligned >= lengths[1]:
        raise ValueError('Forskydningen placerer den anden fil uden for dette prøveklip.')
    donor_start = max(0., aligned-5)
    donor_length = min(length+10, lengths[1]-donor_start)
    report(directory, 'Læser videooplysninger til prøveklippet', None, stage='prepare')
    clip(sources[0], None, start, length, directory/'base.mp4')
    audio_clip(sources[1], tracks[1], donor_start, donor_length, directory/'donor.m4a')
    video = next((s for s in merge.workflow.media_info(sources[0][1]).get('streams', []) if s.get('codec_type') == 'video'), {})
    from fractions import Fraction
    try: fps = float(Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate') or '25'))
    except (ValueError, ZeroDivisionError): fps = 25.
    if not math.isfinite(fps) or not 1 <= fps <= 120: fps = 25.
    return {'kind': 'preview', 'base_start': start, 'donor_start': donor_start,
            'base_duration': length, 'donor_duration': donor_length, 'offset_ms': offset,
            'base_audio': False, 'donor_audio': True, 'video_fps': fps,
            'detail': 'Prøven er klar: video fra hovedfilen med det nye lydspor.'}


def run(api, kind, data):
    ident = data.get('check_id')
    if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident): raise ValueError('Ugyldig forhåndsvisning.')
    sources, offset = merge.validate(api, data, require_import=False)
    tracks = [audio_index(source, data.get(key+'_audio')) for source, key in zip(sources, ('base', 'donor'))]
    directory = merge.library.checked(merge.storage.CONFIG/'merge-previews'/ident)
    directory.mkdir(parents=True, exist_ok=True)
    result = analyse(sources, tracks, offset, directory) if kind == 'analyse' else preview(sources, tracks, offset, data, directory)
    if kind == 'preview': report(directory, 'Kontrollerer prøven og kildefilerne', None, stage='verify', stage_index=3, stage_total=3)
    merge.validate(api, data, require_import=False)
    report(directory, 'Kontrollen er færdig', 100, stage='done')
    return result
