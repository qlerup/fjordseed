# Preservation and encoding routines copied from FjordSeed converter_worker.py.
import json, os, subprocess as _subprocess
from pathlib import Path
from collections import Counter
from fractions import Fraction
ROOT=Path(__file__).resolve().parent
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
def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters',
                           '-of','json',str(path)],capture_output=True,text=True,check=True,timeout=120)
    data=json.loads(result.stdout)
    frames=subprocess.run(['ffprobe','-v','error','-threads','1','-select_streams','v:0',
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

def command(source,target,bitrate,data):
    v=video(data)
    dv=dovi(data)
    if dv and not (dv.get('dv_profile')==7 or (dv.get('dv_profile')==8 and dv.get('dv_bl_signal_compatibility_id')==1)):
        raise ValueError('Denne Dolby Vision-profil understøttes ikke; originalen beholdes.')
    depth='10' if '10' in v.get('pix_fmt','') or dv or v.get('color_transfer') in ('smpte2084','arib-std-b67') else '8'
    if v.get('pix_fmt') not in ('yuv420p','yuv420p10le'):
        raise ValueError('Videoens farveformat understøttes ikke; originalen beholdes.')
    args=['nvencc','--avsw','-i',str(source),'-o',str(target),'-c','hevc',
          '--profile','main10' if depth=='10' else 'main','--output-depth',depth,'--preset','quality',
          '--vbr',str(bitrate*1000),'--max-bitrate',str(bitrate*1500),'--vbv-bufsize',str(bitrate*1500),
          '--colormatrix','auto','--transfer','auto','--colorprim','auto','--chromaloc','auto',
          '--audio-copy','--audio-metadata','copy','--audio-disposition','copy',
          '--sub-copy','--sub-metadata','copy','--sub-disposition','copy','--attachment-copy','--metadata','copy',
          '--chapter-copy','--avsync','vfr']
    if v.get('color_transfer')=='smpte2084':args+=['--max-cll','copy','--master-display','copy']
    if dv:args+=['--dolby-vision-profile','8.1','--dolby-vision-rpu','copy']
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
                        s.get('tags',{}).get('title',''),s.get('disposition',{}).get('default',0),s.get('disposition',{}).get('forced',0))
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

def restore_flags(original,target):
    # NVEncC's unqualified disposition copy may apply the first track's flags
    # to all tracks. Correct MKV headers in place, without remuxing DV video.
    args=['mkvpropedit',str(target)]
    for kind,prefix in (('audio','a'),('subtitle','s')):
        for index,stream in enumerate((s for s in original['streams'] if s['codec_type']==kind),1):
            args+=['--edit',f'track:{prefix}{index}','--set','flag-default='+str(stream.get('disposition',{}).get('default',0)),
                   '--set','flag-forced='+str(stream.get('disposition',{}).get('forced',0))]
    # Rebuild statistics instead of retaining the original video's old bitrate.
    args+=['--add-track-statistics-tags']
    result=subprocess.run(args,capture_output=True,text=True,timeout=1800,env={**os.environ,'LC_ALL':'C.UTF-8'})
    if result.returncode not in (0,1):raise ValueError('MKV-metadata kunne ikke bevares; originalen beholdes.')
