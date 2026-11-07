"""Shared desktop/server encoding policy and media preservation checks."""
import json
import os
import subprocess
from collections import Counter
from fractions import Fraction

# Shared by download queues, library discovery, and the desktop converter.
VIDEO = frozenset({'.mkv', '.mp4', '.m4v', '.avi', '.mov', '.ts', '.m2ts', '.webm',
                   '.mpg', '.mpeg', '.mpe', '.mts', '.m2v', '.wmv', '.asf', '.flv', '.ogv'})

def probe(path, run=None):
    run = run or subprocess.run
    result=run(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters',
                           '-of','json',str(path)],capture_output=True,text=True,check=True,timeout=120)
    data=json.loads(result.stdout)
    frames=run(['ffprobe','-v','error','-threads','1','-select_streams','v:0',
        '-read_intervals','0%+#3','-show_frames','-show_entries','frame_side_data','-of','json',str(path)],
        capture_output=True,text=True,check=True,timeout=120)
    video=next(s for s in data['streams'] if s['codec_type']=='video')
    sides=video.setdefault('side_data_list',[])
    present={s['side_data_type'] for s in sides}
    data['_rpu_frames']=0
    for frame in json.loads(frames.stdout).get('frames',[]):
        for side in frame.get('side_data_list',[]):
            kind=side.get('side_data_type')
            if kind=='Dolby Vision RPU Data':data['_rpu_frames']+=1
            if kind in ('Mastering display metadata','Content light level metadata') and kind not in present:
                sides.append(side);present.add(kind)
    return data

def video(data):
    streams=[s for s in data['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')]
    if len(streams)!=1:
        raise ValueError('Filen skal have ét almindeligt videospor; originalen beholdes.')
    return streams[0]

def dovi(data):
    return next((s for s in video(data).get('side_data_list',[]) if s.get('side_data_type')=='DOVI configuration record'),{})

def checked_conversion_mode(value='video'):
    if value not in ('video', 'audio'):
        raise ValueError('Vælg video og lyd eller kun lyd.')
    return value


conversion_mode = checked_conversion_mode


def checked_audio_selection(value):
    if value is None:return None
    if (not isinstance(value,list) or not 1 <= len(value) <= 128 or
            any(type(i) is not int or not 0 <= i < 10000 for i in value) or len(set(value))!=len(value)):
        raise ValueError('Vælg mindst ét lydspor; hvert spor må kun vælges én gang.')
    return sorted(value)


def selected_audio_reference(data,selection=None):
    selection=checked_audio_selection(selection)
    streams=[s for s in data['streams'] if s['codec_type']=='audio']
    if selection is not None and any(i>=len(streams) for i in selection):
        raise ValueError('Lydsporet findes ikke længere. Scan filen igen.')
    kept=set(range(len(streams)) if selection is None else selection)
    index=-1;result=[]
    for stream in data['streams']:
        if stream['codec_type']=='audio':
            index+=1
            if index not in kept:continue
        result.append(stream)
    return {**data,'streams':result}


def audio_description(stream):
    tags={str(key).lower():value for key,value in stream.get('tags',{}).items()}
    return next((str(tags[key]) for key in ('title','description','comment','handler_name') if tags.get(key)), '')


def audio_plan(data,selected_audio_tracks=None):
    """Copy potential object audio; never infer absence of Atmos from channels."""
    selected_audio_reference(data,selected_audio_tracks)  # Validate actual track bounds.
    selection=checked_audio_selection(selected_audio_tracks)
    tracks=[]
    for index,stream in enumerate(s for s in data.get('streams',[]) if s.get('codec_type')=='audio'):
        if selection is not None and index not in selection:continue
        codec=stream.get('codec_name')
        protected=codec in ('truehd','eac3','dts','ac4','mlp')
        channels=stream.get('channels')
        layout=stream.get('channel_layout')
        # Unknown layouts/codecs must never be guessed or downmixed.
        if not protected and (type(channels) is not int or not 1 <= channels <= 8 or not layout or not codec):
            raise ValueError('Lydsporets kanalopsætning understøttes ikke sikkert; originalen beholdes.')
        tracks.append({'index':index,'stream_index':stream.get('index'),'description':audio_description(stream),'profile':stream.get('profile'),'codec':codec,'output_codec':codec if protected else 'flac',
            'action':'copy' if protected or codec=='flac' else 'convert',
            'channels':channels,'channel_layout':layout,'language':stream.get('tags',{}).get('language','und'),
            'title':stream.get('tags',{}).get('title',''),
            'reason':'Mulig Atmos/DTS:X bevares uændret' if protected else ''})
    return tracks


def output_reserve(data,source_size,selected_audio_tracks=None):
    duration=float(data['format']['duration'])
    if not 0 < duration < 10**9:raise ValueError('Filens varighed er ugyldig.')
    reserve=source_size
    for stream,track in zip((s for s in selected_audio_reference(data,selected_audio_tracks)['streams'] if s['codec_type']=='audio'),audio_plan(data,selected_audio_tracks)):
        if track['action']=='convert':
            rate=int(stream.get('sample_rate',0))
            if not 0 < rate <= 768000:raise ValueError('Lydsporets samplerate er ugyldig.')
            reserve+=int(duration*rate*track['channels']*4*1.01)
    return reserve+1024**3


def audio_command(source,target,data,selected_audio_tracks=None):
    plan=audio_plan(data,selected_audio_tracks)
    if not plan:raise ValueError('Filen har ingen lydspor at konvertere.')
    args=['ffmpeg','-nostdin','-n','-i',str(source),'-map','0','-map_metadata','0','-map_chapters','0','-c','copy']
    args += ['-map','-0:a']
    for track in plan:args += ['-map',f"0:a:{track['index']}"]
    for index,track in enumerate(plan):
        if track['action']=='convert':
            args += [f'-c:a:{index}',track['output_codec']]
            # Never set -ac: FFmpeg would infer a default layout from its count.
    return args+['-progress','pipe:1','-nostats',str(target)]


def validate_audio(original,result,selected_audio_tracks=None):
    from copy import deepcopy
    plan=audio_plan(original,selected_audio_tracks)
    original=selected_audio_reference(original,selected_audio_tracks)
    old=[s for s in original['streams'] if s['codec_type']=='audio']
    new=[s for s in result['streams'] if s['codec_type']=='audio']
    if len(old)!=len(new):raise ValueError('Kontrol fejlede: lydspor mangler.')
    reference=deepcopy(original)
    for a,b,track,r in zip(old,new,plan,(s for s in reference['streams'] if s['codec_type']=='audio')):
        if b.get('codec_name')!=track['output_codec']:
            raise ValueError('Kontrol fejlede: lydformatet matcher ikke jobbet.')
        for field in ('channels','channel_layout','sample_rate'):
            if a.get(field)!=b.get(field):raise ValueError('Kontrol fejlede: lydens '+field+' blev ændret.')
        if track['action']=='copy' and a.get('profile')!=b.get('profile'):
            raise ValueError('Kontrol fejlede: lydprofilen blev ændret.')
        r['codec_name']=b.get('codec_name')
        r['profile']=b.get('profile')
    for field in ('codec_name','profile','level'):
        if video(original).get(field)!=video(result).get(field):
            raise ValueError('Kontrol fejlede: videoen skal kopieres ved kun lyd.')
    if dovi(original)!=dovi(result) or bool(original.get('_rpu_frames'))!=bool(result.get('_rpu_frames')):
        raise ValueError('Kontrol fejlede: Dolby Vision blev ændret ved kun lyd.')
    # The ordinary validator expects re-encoded DV 8.1; audio-only retains source DV.
    cleaned=deepcopy(result)
    for data in (reference,cleaned):
        video(data)['side_data_list']=[s for s in video(data).get('side_data_list',[]) if s.get('side_data_type')!='DOVI configuration record']
    validate(reference,cleaned)
    for a,b in zip(old,new):
        if a.get('tags',{}).get('language','und')!=b.get('tags',{}).get('language','und') or a.get('tags',{}).get('title','')!=b.get('tags',{}).get('title',''):
            raise ValueError('Kontrol fejlede: lydsporenes rækkefølge eller sprog blev ændret.')


def command(source,target,bitrate,data,reader="avsw",conversion_mode='video',selected_audio_tracks=None):
    if checked_conversion_mode(conversion_mode)=='audio':return audio_command(source,target,data,selected_audio_tracks)
    if selected_audio_tracks is not None:raise ValueError('Lydspor kan kun fravælges ved kun lyd-konvertering.')
    v=video(data)
    dv=dovi(data)
    if dv and not (dv.get('dv_profile')==7 or (dv.get('dv_profile')==8 and dv.get('dv_bl_signal_compatibility_id')==1)):
        raise ValueError('Denne Dolby Vision-profil understøttes ikke; originalen beholdes.')
    depth='10' if '10' in v.get('pix_fmt','') or dv or v.get('color_transfer') in ('smpte2084','arib-std-b67') else '8'
    if v.get('pix_fmt') not in ('yuv420p','yuv420p10le'):
        raise ValueError('Videoens farveformat understøttes ikke; originalen beholdes.')
    args=['nvencc','--'+reader,'-i',str(source),'-o',str(target),'-c','hevc',
          '--profile','main10' if depth=='10' else 'main','--output-depth',depth,'--preset','quality',
          '--vbr',str(bitrate*1000),'--max-bitrate',str(bitrate*1500),'--vbv-bufsize',str(bitrate*1500),
          '--colormatrix','auto','--transfer','auto','--colorprim','auto','--chromaloc','auto',
          '--audio-copy','--audio-metadata','copy','--audio-disposition','copy',
          '--sub-copy','--sub-metadata','copy','--sub-disposition','copy','--attachment-copy','--metadata','copy',
          '--chapter-copy','--avsync','vfr']
    if v.get('color_transfer')=='smpte2084':args+=['--max-cll','copy','--master-display','copy']
    if dv:
        # NVEncC 9.39 forces level 10 with explicit 8.1. Copy retains the
        # source level and converts supported profile 7 BL+RPU to 8.1.
        # Apply the same bitstream flags explicitly for profile 7 inputs.
        args+=['--dolby-vision-profile','copy','--dolby-vision-rpu','copy',
               '--repeat-headers','--aud','--pic-struct']
    return args

def validate(original,result):
    before,after=video(original),video(result)
    for field in ('width','height','pix_fmt','color_transfer','color_primaries','color_space'):
        if before.get(field)!=after.get(field):
            raise ValueError('Kontrol fejlede: videoens '+field+' blev ændret.')
    a,b=Fraction(before['avg_frame_rate']),Fraction(after['avg_frame_rate'])
    if abs(float(a-b))>.01:raise ValueError('Billedhastigheden blev ændret.')
    if abs(float(original['format']['duration'])-float(result['format']['duration']))>3:
        raise ValueError('Kontrol fejlede: varigheden blev ændret.')
    def duration(data):
        stream=video(data)
        tag=stream.get('tags',{}).get('DURATION','').split(':')
        if len(tag)==3:return sum(float(x)*m for x,m in zip(tag,(3600,60,1)))
        return float(stream.get('duration',data['format']['duration']))
    if abs(duration(original)-duration(result))>3:
        raise ValueError('Kontrol fejlede: videospor er afkortet.')
    def tracks(data,kind):
        return Counter((s.get('codec_name'),s.get('tags',{}).get('language','und'),s.get('channels'),
                        s.get('tags',{}).get('title',''),s.get('channel_layout'),s.get('sample_rate'),s.get('profile'),s.get('disposition',{}).get('default',0),s.get('disposition',{}).get('forced',0))
                       for s in data['streams'] if s['codec_type']==kind)
    for kind in ('audio','subtitle','attachment'):
        if tracks(original,kind)!=tracks(result,kind):raise ValueError('Kontrol fejlede: '+kind+'-spor ændret.')
    if len(original.get('chapters',[]))!=len(result.get('chapters',[])):
        raise ValueError('Kontrol fejlede: kapitler mangler.')
    for old,new in zip(original.get('chapters',[]),result.get('chapters',[])):
        if abs(float(old['start_time'])-float(new['start_time']))>.1 or old.get('tags',{}).get('title')!=new.get('tags',{}).get('title'):
            raise ValueError('Kontrol fejlede: kapitler ændret.')
    required={s['side_data_type'] for s in before.get('side_data_list',[])} & {'Mastering display metadata','Content light level metadata'}
    if not required <= {s['side_data_type'] for s in after.get('side_data_list',[])}:
        raise ValueError('Kontrol fejlede: HDR-metadata mangler.')
    if dovi(original):
        dv=dovi(result)
        if not (dv.get('dv_profile')==8 and dv.get('dv_bl_signal_compatibility_id')==1 and result.get('_rpu_frames')):
            raise ValueError('Kontrol fejlede: Dolby Vision 8.1/RPU mangler.')
        source_level=dovi(original).get('dv_level')
        if type(source_level) is not int or not 1<=source_level<=13 or dv.get('dv_level')!=source_level:
            raise ValueError('Kontrol fejlede: Dolby Vision-level blev ændret eller mangler.')
        if dv.get('bl_present_flag')!=1 or dv.get('rpu_present_flag')!=1 or dv.get('el_present_flag')!=0:
            raise ValueError('Kontrol fejlede: Dolby Vision-lag passer ikke til profil 8.1.')

def restore_flags(original,target, run=None):
    run = run or subprocess.run
    # NVEncC's unqualified disposition copy may apply the first track's flags
    # to all tracks. Correct MKV headers in place, without remuxing DV video.
    args=['mkvpropedit',str(target)]
    for kind,prefix in (('audio','a'),('subtitle','s')):
        for index,stream in enumerate((s for s in original['streams'] if s['codec_type']==kind),1):
            args+=['--edit',f'track:{prefix}{index}','--set','flag-default='+str(stream.get('disposition',{}).get('default',0)),
                   '--set','flag-forced='+str(stream.get('disposition',{}).get('forced',0))]
    # Rebuild statistics instead of retaining the original video's old bitrate.
    args+=['--add-track-statistics-tags']
    result=run(args,capture_output=True,text=True,timeout=1800,env={**os.environ,'LC_ALL':'C.UTF-8'})
    if result.returncode not in (0,1):raise ValueError('MKV-metadata kunne ikke bevares; originalen beholdes.')


def dolby_mode(value='separate'):
    if value not in ('separate', 'preserve'):
        raise ValueError('Vælg Dolby Vision i filmen eller gemt separat.')
    return value


def validate_file(original, path, run=None, mode='separate', conversion_mode='video', selected_audio_tracks=None):
    """Verify the job-selected DV output or HDR output with reversible archive."""
    from copy import deepcopy
    from dolby_backup import verify
    mode = dolby_mode(mode)
    result = probe(path, run=run)
    if checked_conversion_mode(conversion_mode)=='audio':
        validate_audio(original,result,selected_audio_tracks)
        return result
    if mode == 'preserve':
        validate(original,result)
        return result
    if dovi(original) and not dovi(result):
        manifest=verify(path)
        if result.get('_rpu_frames'):
            raise ValueError('Kontrol fejlede: Dolby Vision RPU er stadig aktivt.')
        reference = deepcopy(original)
        video(reference)['side_data_list'] = [s for s in video(reference).get('side_data_list',[])
                                              if s.get('side_data_type') != 'DOVI configuration record']
        validate(reference,result)
        restored=deepcopy(result)
        video(restored).setdefault('side_data_list',[]).append(manifest['dolby_vision'])
        restored['_rpu_frames']=manifest['rpu_frames']
        validate(original,restored)
    else:
        if dovi(original):raise ValueError('Dolby Vision skal gemmes separat før publicering.')
        validate(original,result)
    return result


def prepare_output(original, path, run=None, mode='separate', conversion_mode='video', selected_audio_tracks=None):
    """Same Windows/server policy: preserve DV or archive it for HDR10 playback."""
    from dolby_backup import suspend, sidecar, restore
    mode = dolby_mode(mode)
    if checked_conversion_mode(conversion_mode)=='audio':
        restore_flags(selected_audio_reference(original,selected_audio_tracks),path,run=run)
        return validate_file(original,path,run=run,mode=mode,conversion_mode='audio',selected_audio_tracks=selected_audio_tracks)
    if sidecar(path).exists():
        if mode == 'preserve':
            restore(path)
            result = validate_file(original,path,run=run,mode=mode)
            sidecar(path).unlink()
            return result
        if not dovi(probe(path,run=run)):
            return validate_file(original,path,run=run,mode=mode)
    restore_flags(original,path,run=run)
    result = probe(path,run=run)
    validate(original,result)
    if dovi(original) and mode == 'separate':
        suspend(path,dovi(result))
        result = validate_file(original,path,run=run)
    return result


def publish_output(partial, target):
    from dolby_backup import sidecar, verify
    if target.exists():raise ValueError('Resultatfilen findes allerede. Ingen filer overskrives.')
    if sidecar(target).exists():
        # Resume a crash after archive publication but before media publication.
        verify(partial,sidecar(target))
    elif sidecar(partial).exists():
        if os.name=='nt':sidecar(partial).rename(sidecar(target))
        else:os.link(sidecar(partial),sidecar(target))
    if os.name=='nt':
        partial.rename(target)  # Windows rename is exclusive and supports SMB.
    else:os.link(partial,target)  # exclusive publication, including on Windows
    partial.unlink(missing_ok=True)
    sidecar(partial).unlink(missing_ok=True)
