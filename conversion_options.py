"""Validated per-film settings and stream-preserving audio remuxing."""
from copy import deepcopy

from conversion_media import video, dovi, validate

MODES = ('full', 'video', 'audio')


def normalize(value, media):
    if not isinstance(value, dict) or value.get('mode') not in MODES:
        raise ValueError('Vælg fuld, video- eller lydkonvertering.')
    video(media)
    mode = value['mode']
    bitrate = value.get('bitrate', 30)
    if type(bitrate) is not int or bitrate not in (20, 30, 40):
        raise ValueError('Vælg 20, 30 eller 40 Mbps.')
    dv = value.get('dolby_vision_mode', 'separate')
    if dv not in ('separate', 'preserve'):
        raise ValueError('Vælg HDR10 med gemt Dolby Vision eller Dolby Vision 8.1.')
    codec = value.get('audio_codec', 'copy')
    if codec not in ('copy', 'eac3', 'ac3'):
        raise ValueError('Vælg original lyd, E-AC3 eller AC3.')
    result = dict(mode=mode, bitrate=bitrate, dolby_vision_mode=dv, audio_codec=codec)
    for kind in ('audio', 'subtitle'):
        available = [s['index'] for s in media['streams'] if s['codec_type'] == kind]
        chosen = value.get(kind, available)
        if not isinstance(chosen, list) or any(type(i) is not int or i not in available for i in chosen) or len(set(chosen)) != len(chosen):
            raise ValueError('De valgte spor findes ikke i filmen.')
        # Copy untouched domains in their entirety.
        if mode == 'video' or (mode == 'audio' and kind == 'subtitle'):
            chosen = available
        if kind == 'audio' and available and not chosen:
            raise ValueError('Vælg mindst ét lydspor.')
        result[kind] = [i for i in available if i in chosen]
    if mode == 'video': result['audio_codec'] = 'copy'
    if mode == 'audio': result['dolby_vision_mode'] = 'preserve'
    if mode != 'audio' and dovi(media):
        dv = dovi(media)
        if not (dv.get('dv_profile') == 7 or (dv.get('dv_profile') == 8 and dv.get('dv_bl_signal_compatibility_id') == 1)):
            raise ValueError('Videokonvertering understøtter Dolby Vision 7 og 8.1. Vælg kun lyd for at bevare andre profiler.')
    for stream in media['streams']:
        if (stream['codec_type'] == 'audio' and stream['index'] in result['audio']
                and result['audio_codec'] != 'copy' and stream.get('codec_name') != result['audio_codec']
                and (type(stream.get('channels')) is not int or not 1 <= stream['channels'] <= 6)):
            raise ValueError('AC3/E-AC3 understøtter her op til 5.1. Behold original lyd for dette spor; kanaler nedmikses ikke.')
    for stream in media['streams']:
        if (stream['codec_type'] == 'audio' and stream['index'] in result['audio']
                and result['audio_codec'] != 'copy' and stream.get('codec_name') != result['audio_codec']):
            layout = stream.get('channel_layout') or {1:'mono', 2:'stereo'}.get(stream.get('channels'))
            if layout not in ('mono','stereo','2.1','3.0','3.0(back)','quad','quad(side)','4.0','3.1','4.1','5.0','5.0(side)','5.1','5.1(side)'):
                raise ValueError('Lydsporets kanalopsætning er ukendt eller understøttes ikke af AC3/E-AC3. Behold original lyd.')
    return result


def reference(media, options):
    result = deepcopy(media)
    streams = []
    for stream in result['streams']:
        kind = stream['codec_type']
        if kind in ('audio', 'subtitle') and stream['index'] not in options[kind]: continue
        streams.append(stream)
        if kind == 'audio' and options['audio_codec'] != 'copy' and stream.get('codec_name') != options['audio_codec']:
            compatible = deepcopy(stream)
            compatible['codec_name'] = options['audio_codec']
            compatible.pop('profile', None)
            layout = stream.get('channel_layout') or {1:'mono', 2:'stereo'}.get(stream.get('channels'))
            compatible['channel_layout'] = {'quad':'quad(side)', '5.0':'5.0(side)', '5.1':'5.1(side)'}.get(layout, layout)
            compatible['sample_rate'] = '48000'
            compatible.setdefault('disposition', {})['default'] = 0
            streams.append(compatible)
    result['streams'] = streams
    return result


def remux_command(source, encoded, target, media, options):
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-i', str(source)]
    if encoded: args += ['-i', str(encoded)]
    args += ['-map', '1:v:0' if encoded else '0:v:0', '-c', 'copy', '-map_metadata', '0', '-map_chapters', '0']
    audio = 0
    for stream in media['streams']:
        kind, index = stream['codec_type'], stream['index']
        if kind == 'audio' and index in options['audio']:
            args += ['-map', f'0:{index}']; audio += 1
            if options['audio_codec'] != 'copy' and stream.get('codec_name') != options['audio_codec']:
                args += ['-map', f'0:{index}', f'-c:a:{audio}', options['audio_codec'],
                         f'-ar:a:{audio}', '48000', f'-b:a:{audio}', '640k' if stream['channels'] > 2 else '192k',
                         f'-disposition:a:{audio}', '0']
                audio += 1
        elif kind == 'subtitle' and index in options['subtitle']:
            args += ['-map', f'0:{index}']
        elif kind == 'attachment': args += ['-map', f'0:{index}']
    return args + [str(target)]


def validate_audio_only(original, result):
    # General validation expects encoded DV 8.1. A stream copy instead retains
    # the exact source profile, including profile 5/7 and its enhancement layer.
    if dovi(original) != dovi(result) or bool(original.get('_rpu_frames')) != bool(result.get('_rpu_frames')):
        raise ValueError('Dolby Vision blev ændret under lydkonvertering.')
    before, after = deepcopy(original), deepcopy(result)
    for data in (before, after):
        video(data)['side_data_list'] = [s for s in video(data).get('side_data_list', []) if s.get('side_data_type') != 'DOVI configuration record']
    if video(before).get('codec_name') != video(after).get('codec_name'):
        raise ValueError('Videoformatet blev ændret under lydkonvertering.')
    validate(before, after)


def estimate(media, size, options):
    from media_bitrates import number
    duration = number(media.get('format', {}).get('duration'))
    if not duration: return None
    def bps(s):
        return number(s.get('bit_rate')) or number(s.get('tags', {}).get('BPS')) or number(s.get('tags', {}).get('BPS-eng'))
    original_audio = [s for s in media['streams'] if s['codec_type'] == 'audio']
    # Do not fabricate savings when source stream sizes are unknown.
    if any(not bps(s) for s in original_audio): return None
    audio = sum(bps(s) for s in original_audio if s['index'] in options['audio'])
    for s in original_audio:
        if s['index'] in options['audio'] and options['audio_codec'] != 'copy' and s.get('codec_name') != options['audio_codec']:
            audio += 640000 if s.get('channels', 2) > 2 else 192000
    if options['mode'] == 'audio':
        return round(max(0, size - sum(bps(s) for s in original_audio)*duration/8 + audio*duration/8))
    return round((options['bitrate']*1000000 + audio)*duration/8*1.01)
