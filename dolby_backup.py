"""Reversible DV 8.1 removal from unencrypted, unlaced HEVC Matroska.

Keep byte offsets unchanged: replace DV RPU NALs with HEVC filler NALs and
BlockAdditionMapping with EBML Void. Save exact overwritten bytes, including
updated CRCs, in a compressed sidecar. Restoration is byte-for-byte, guarded by
full-file SHA256. Never modify a published file in place (it may be hardlinked).
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
import zipfile
import zlib

SUFFIX = '.fjord-dv.zip'
CHUNK = 4 * 1024 * 1024


def sidecar(path):
    return Path(str(path) + SUFFIX)


def checked(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Dolby Vision må ikke følge symbolske links.')
    return path


def digest(path):
    with checked(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def vint(stream, identifier=False):
    first = stream.read(1)
    if not first or not first[0]:
        raise ValueError('Ugyldig MKV-længde.')
    n = 1
    while not first[0] & (1 << (8-n)):
        n += 1
    rest = stream.read(n-1)
    if len(rest) != n-1:
        raise ValueError('Afkortet MKV-header.')
    value = int.from_bytes(first+rest, 'big')
    return (value if identifier else value & ((1 << (7*n))-1)), n


def elements(stream, start, end):
    pos = start
    while pos < end:
        stream.seek(pos)
        ident, _ = vint(stream, True)
        size, n = vint(stream)
        data = stream.tell()
        if size == (1 << (7*n))-1:
            # Only the top-level Segment may have unknown size.
            if ident != 0x18538067:
                raise ValueError('Denne MKV bruger ukendt elementlængde.')
            size = end-data
        stop = data+size
        if stop > end:
            raise ValueError('MKV-element uden for filen.')
        yield ident, pos, data, stop
        pos = stop


def metadata(archive):
    with zipfile.ZipFile(checked(archive)) as z:
        info = z.getinfo('manifest.json')
        if info.file_size > 65536:
            raise ValueError('Ugyldigt Dolby Vision-arkiv.')
        m = json.loads(z.read(info))
        if not isinstance(m,dict):raise ValueError('Ugyldigt Dolby Vision-arkiv.')
        if (m.get('version') != 1 or type(m.get('size')) is not int or m['size'] <= 0
                or type(m.get('patches')) is not int or not 0 < m['patches'] < 10000000
                or any(not isinstance(m.get(k),str) or len(m[k]) != 64 for k in ('hdr_sha256','dv_sha256'))):
            raise ValueError('Ugyldigt Dolby Vision-arkiv.')
        return m


def verify(path, archive=None):
    m = metadata(archive or sidecar(path))
    if checked(path).stat().st_size != m['size'] or digest(path) != m['hdr_sha256']:
        raise ValueError('Videoen matcher ikke de gemte Dolby Vision-data. Ingen filer ændres.')
    with zipfile.ZipFile(archive or sidecar(path)) as z:
        if z.testzip() is not None:raise ValueError('Dolby Vision-arkivet er beskadiget.')
    return m


def suspend(path, dv):
    """Only on a disposable encoded output, before publication."""
    path = checked(path)
    archive = checked(sidecar(path))
    if archive.exists():
        m=metadata(archive)
        current=digest(path)
        if current==m['hdr_sha256']:return
        if current!=m['dv_sha256']:raise ValueError('Videoen matcher ikke Dolby Vision-arkivet.')
        archive.unlink()  # interrupted before HDR replacement; DV is still intact
    if not (dv.get('dv_profile') == 8 and dv.get('dv_bl_signal_compatibility_id') == 1
            and dv.get('bl_present_flag') == 1 and dv.get('el_present_flag') == 0):
        raise ValueError('Kun HDR10-kompatibel Dolby Vision 8.1 kan gemmes separat.')
    # Caller owns the conversion job lock. Clean only this output's leftovers.
    prefix='.fjord-dv-'+hashlib.sha256(str(path).encode()).hexdigest()[:16]+'-'
    for leftover in path.parent.glob(prefix+'*'):
        if leftover.name.endswith(('.mkv','.mkv.zip')):checked(leftover).unlink()
    size = path.stat().st_size
    if shutil.disk_usage(path.parent).free < size + 1024**3:
        raise ValueError('Der mangler plads til sikker Dolby Vision-opbevaring.')
    fd, name = tempfile.mkstemp(prefix=prefix, suffix='.mkv', dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    backup = Path(name+'.zip')
    original_hash = digest(path)
    try:
        shutil.copyfile(path, temporary)
        count = 0
        rpus = 0
        mappings = 0
        with path.open('rb') as src, temporary.open('r+b') as dst, zipfile.ZipFile(backup,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            with z.open('patches.bin','w',force_zip64=True) as patches:
                def patch(offset, replacement):
                    nonlocal count
                    src.seek(offset)
                    old = src.read(len(replacement))
                    if len(old) != len(replacement):raise ValueError('Afkortet fil.')
                    patches.write(struct.pack('>QI',offset,len(old)))
                    patches.write(old)
                    dst.seek(offset);dst.write(replacement)
                    count += 1

                def crc(start,end,children,changed):
                    if not changed:return
                    for ident,pos,data,stop in children:
                        if ident != 0xbf:continue
                        if stop-data != 4:raise ValueError('Ugyldig MKV-kontrolsum.')
                        dst.flush();value = 0
                        for a,b in ((start,pos),(stop,end)):
                            dst.seek(a)
                            while a < b:
                                block=dst.read(min(CHUNK,b-a))
                                if not block:raise ValueError('Afkortet MKV-fil.')
                                value=zlib.crc32(block,value);a+=len(block)
                        patch(data,value.to_bytes(4,'little'))

                video_track = None
                nal_length = None
                def tracks(start,end):
                    nonlocal video_track,nal_length,mappings
                    children=list(elements(src,start,end));changed=False
                    for ident,pos,data,stop in children:
                        if ident != 0xae:continue
                        fields=list(elements(src,data,stop));values={}
                        for key,_,a,b in fields:
                            if key in (0xd7,0x83,0x86,0x63a2):
                                if b-a > 1024*1024:raise ValueError('Ugyldig MKV-sporheader.')
                                src.seek(a);values[key]=src.read(b-a)
                            if key == 0x6d80:raise ValueError('Komprimerede eller krypterede MKV-spor understøttes ikke.')
                        if int.from_bytes(values.get(0x83,b''),'big') != 1:continue
                        if video_track is not None:raise ValueError('Kun ét videospor understøttes.')
                        if values.get(0x86) != b'V_MPEGH/ISO/HEVC' or len(values.get(0x63a2,b'')) < 22:
                            raise ValueError('Dolby Vision-videosporet er ikke HEVC.')
                        video_track=int.from_bytes(values[0xd7],'big');nal_length=(values[0x63a2][21]&3)+1
                        entry_changed=False
                        for key,p,a,b in fields:
                            if key != 0x41e4:continue
                            mapping=list(elements(src,a,b))
                            if not any(k == 0x41ed for k,_,_,_ in mapping):continue
                            # Same total byte length, with an 8-byte EBML size.
                            total=b-p
                            if total < 9:raise ValueError('Ugyldig Dolby Vision-header.')
                            patch(p,b'\xec'+((1<<56)|(total-9)).to_bytes(8,'big')+bytes(total-9))
                            mappings+=1;entry_changed=True
                        crc(data,stop,fields,entry_changed);changed|=entry_changed
                    crc(start,end,children,changed)

                def block(start,end):
                    nonlocal rpus
                    src.seek(start);track,_=vint(src)
                    header=src.read(3)
                    if len(header)!=3:raise ValueError('Afkortet MKV-blok.')
                    if track != video_track:return False
                    if header[2]&6:raise ValueError('Lacing på videospor understøttes ikke.')
                    pos=src.tell();changed=False
                    while pos < end:
                        src.seek(pos);raw=src.read(nal_length)
                        if len(raw)!=nal_length:raise ValueError('Afkortet HEVC-længde.')
                        n=int.from_bytes(raw,'big');pos+=nal_length
                        if n<2 or pos+n>end:raise ValueError('Ugyldig HEVC-pakke.')
                        head=src.read(2);kind=(head[0]>>1)&63
                        if kind==62:
                            if not 3<=n<=1024*1024:raise ValueError('Ugyldigt Dolby Vision RPU.')
                            # HEVC filler_data_rbsp: ff bytes followed by rbsp stop bit.
                            patch(pos,bytes([(head[0]&0x81)|(38<<1),head[1]])+b'\xff'*(n-3)+b'\x80')
                            rpus+=1;changed=True
                        pos+=n
                    return changed

                def cluster(start,end):
                    children=list(elements(src,start,end));changed=False
                    for ident,pos,data,stop in children:
                        if ident==0xa3:changed=block(data,stop) or changed
                        elif ident==0xa0:
                            sub=list(elements(src,data,stop));dirty=False
                            for key,_,a,b in sub:
                                if key==0xa1:dirty=block(a,b) or dirty
                            crc(data,stop,sub,dirty);changed|=dirty
                    crc(start,end,children,changed)

                segments=[e for e in elements(src,0,size) if e[0]==0x18538067]
                if len(segments)!=1:raise ValueError('Ugyldig MKV-segmentstruktur.')
                _,_,start,end=segments[0]
                # Segment children include only a few thousand clusters, not frames.
                children=list(elements(src,start,end))
                for ident,_,a,b in children:
                    if ident==0x1654ae6b:tracks(a,b)
                if not video_track or mappings!=1:raise ValueError('Dolby Vision-headeren kunne ikke gemmes entydigt.')
                for ident,_,a,b in children:
                    if ident==0x1f43b675:cluster(a,b)
                if not rpus:raise ValueError('Dolby Vision RPU-data mangler.')
                crc(start,end,children,True)
                dst.flush();os.fsync(dst.fileno())
            m={'version':1,'size':size,'dv_sha256':original_hash,'hdr_sha256':digest(temporary),
               'patches':count,'rpu_frames':rpus,'dolby_vision':dv,'created_at':time.time()}
            z.writestr('manifest.json',json.dumps(m))
        # Archive committed before the HDR file; an interruption cannot lose DV.
        if digest(path)!=original_hash:raise ValueError('Videoen blev ændret under arbejdet.')
        with backup.open('r+b') as saved:os.fsync(saved.fileno())
        os.replace(backup,archive)
        shutil.copymode(path,temporary)
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True);backup.unlink(missing_ok=True)


def restore(path, progress=None):
    path=checked(path);archive=checked(sidecar(path));m=metadata(archive)
    current=digest(path)
    if current==m['dv_sha256']:return m  # recovery after replace, before job receipt
    if current!=m['hdr_sha256'] or path.stat().st_size!=m['size']:
        raise ValueError('Videoen er ændret siden konverteringen. Gendannelse er afvist.')
    if shutil.disk_usage(path.parent).free < m['size']+1024**3:
        raise ValueError('Der mangler plads til en sikker arbejdskopi.')
    fd,name=tempfile.mkstemp(prefix='.fjord-dv-restore-'+hashlib.sha256(str(path).encode()).hexdigest()[:16]+'-',suffix='.mkv',dir=path.parent);os.close(fd)
    temporary=Path(name)
    try:
        shutil.copyfile(path,temporary)
        with zipfile.ZipFile(archive) as z,z.open('patches.bin') as patches,temporary.open('r+b') as out:
            for _ in range(m['patches']):
                header=patches.read(12)
                if len(header)!=12:raise ValueError('Dolby Vision-arkivet er afkortet.')
                offset,length=struct.unpack('>QI',header)
                if not 0<length<=1024*1024 or offset+length>m['size']:
                    raise ValueError('Ugyldige Dolby Vision-data.')
                data=patches.read(length)
                if len(data)!=length:raise ValueError('Dolby Vision-arkivet er afkortet.')
                out.seek(offset);out.write(data)
            if patches.read(1):raise ValueError('Uventede data i Dolby Vision-arkivet.')
            out.flush();os.fsync(out.fileno())
        if digest(temporary)!=m['dv_sha256']:
            raise ValueError('Gendannelsens kontrolsum stemmer ikke. HDR10-filen er bevaret.')
        if digest(path)!=m['hdr_sha256']:
            raise ValueError('Videoen blev ændret under gendannelsen.')
        shutil.copymode(path,temporary);os.replace(temporary,path)
        return m
    finally:
        temporary.unlink(missing_ok=True)
