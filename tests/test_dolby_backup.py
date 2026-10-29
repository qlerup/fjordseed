import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

import pytest
import dolby_backup as b

DV={'dv_profile':8,'dv_bl_signal_compatibility_id':1,'bl_present_flag':1,'el_present_flag':0,'rpu_present_flag':1,'dv_level':6}


def element(ident,payload):
    key=ident.to_bytes((ident.bit_length()+7)//8,'big')
    return key+((1<<28)|len(payload)).to_bytes(4,'big')+payload


def master(ident,payload):
    return element(ident,element(0xbf,zlib.crc32(payload).to_bytes(4,'little'))+payload)


def movie(laced=False):
    private=bytes(21)+b'\x03'
    fields=element(0xd7,b'\x01')+element(0x83,b'\x01')+element(0x86,b'V_MPEGH/ISO/HEVC')+element(0x63a2,private)
    fields+=element(0x41e4,element(0x41ed,bytes.fromhex('01001035')+bytes(20)))
    tracks=master(0x1654ae6b,master(0xae,fields))
    def nal(kind,payload):
        data=bytes([kind<<1,1])+payload
        return len(data).to_bytes(4,'big')+data
    frame=nal(1,b'unchanged picture')+nal(62,b'Dolby metadata\x80')
    video=element(0xa3,b'\x81\0\0'+bytes([2 if laced else 0])+frame)
    audio=element(0xa3,b'\x82\0\0\0'+b'unchanged TrueHD Atmos payload')
    return element(0x1a45dfa3,b'')+master(0x18538067,tracks+master(0x1f43b675,video+audio))


@pytest.fixture
def path(tmp_path,monkeypatch):
    monkeypatch.setattr(b.shutil,'disk_usage',lambda _:type('Usage',(),{'free':10**12})())
    p=tmp_path/'film.mkv';p.write_bytes(movie());return p


def test_hdr_removes_rpu_and_dovi_configuration_without_changing_picture_or_audio(path):
    original=path.read_bytes();b.suspend(path,DV)
    hdr=path.read_bytes()
    assert len(hdr)==len(original)
    assert b'Dolby metadata' not in hdr
    assert b'unchanged picture' in hdr and b'unchanged TrueHD Atmos payload' in hdr
    assert b.verify(path)['rpu_frames']==1
    b.suspend(path,DV)  # idempotent
    b.restore(path)
    assert path.read_bytes()==original
    b.restore(path)  # crash recovery after replacement
    assert b.sidecar(path).exists()


def test_modified_video_is_never_replaced(path):
    b.suspend(path,DV);path.write_bytes(path.read_bytes()+b'changed')
    before=path.read_bytes()
    with pytest.raises(ValueError,match='ændret'):b.restore(path)
    assert path.read_bytes()==before


def test_corrupted_archive_never_replaces_hdr_file(path):
    b.suspend(path,DV);before=path.read_bytes();archive=b.sidecar(path)
    with zipfile.ZipFile(archive) as z:m=z.read('manifest.json');patches=bytearray(z.read('patches.bin'))
    patches[-1]^=1
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('manifest.json',m);z.writestr('patches.bin',patches)
    with pytest.raises(ValueError,match='kontrolsum'):b.restore(path)
    assert path.read_bytes()==before


def test_unsupported_lacing_does_not_change_source(path):
    original=movie(laced=True);path.write_bytes(original)
    with pytest.raises(ValueError,match='Lacing'):b.suspend(path,DV)
    assert path.read_bytes()==original and not b.sidecar(path).exists()


def test_symlink_rejected(path,tmp_path):
    link=tmp_path/'link.mkv'
    try:link.symlink_to(path)
    except OSError:pytest.skip('Symlink privilege unavailable')
    with pytest.raises(ValueError,match='links'):b.suspend(link,DV)


def test_crc_checksums_of_modified_masters_are_valid(path):
    b.suspend(path,DV)
    data=path.read_bytes();stream=io.BytesIO(data)
    masters={0x18538067,0x1654ae6b,0xae,0x1f43b675}
    def check(start,end):
        for key,pos,a,c in b.elements(stream,start,end):
            if key==0xbf:assert int.from_bytes(data[a:c],'little')==zlib.crc32(data[start:pos]+data[c:end])
            elif key in masters:check(a,c)
    check(0,len(data))


def test_restore_does_not_modify_other_hardlinks(path,tmp_path):
    import os
    b.suspend(path,DV);other=tmp_path/'other.mkv';os.link(path,other);hdr=other.read_bytes()
    b.restore(path)
    assert other.read_bytes()==hdr
    assert path.read_bytes()!=hdr


def test_publication_moves_backup_and_refuses_to_overwrite(path,tmp_path):
    from conversion_media import publish_output
    b.suspend(path,DV);target=tmp_path/'published.mkv'
    publish_output(path,target)
    assert not path.exists() and not b.sidecar(path).exists()
    b.verify(target);b.restore(target);assert target.read_bytes()==movie()
    another=tmp_path/'another.mkv';another.write_bytes(b'new')
    with pytest.raises(ValueError):publish_output(another,target)
    assert target.read_bytes()==movie()


def test_publication_recovers_archive_already_moved(path,tmp_path):
    from conversion_media import publish_output
    b.suspend(path,DV);target=tmp_path/'published.mkv'
    b.sidecar(path).rename(b.sidecar(target))
    publish_output(path,target);b.verify(target)


def test_interrupted_archive_work_copy_is_cleaned_only_for_same_output(path):
    import hashlib
    prefix='.fjord-dv-'+hashlib.sha256(str(path).encode()).hexdigest()[:16]+'-'
    stale=path.parent/(prefix+'interrupted.mkv');stale.write_bytes(b'incomplete')
    unrelated=path.parent/'.fjord-dv-another-output.mkv';unrelated.write_bytes(b'keep')
    b.suspend(path,DV)
    assert not stale.exists() and unrelated.read_bytes()==b'keep'
    b.restore(path);assert path.read_bytes()==movie()
