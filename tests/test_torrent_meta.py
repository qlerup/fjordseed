import base64
import hashlib

import pytest

from torrent_meta import torrent_meta,magnet_meta


def test_exact_original_info_bytes_and_no_announce_passkeys():
    # Deliberately unsorted dictionary: re-encoding would produce a different hash.
    info=b'd4:name11:example.iso6:lengthi4ee'
    raw=b'd8:announce28:https://example/passkey-test4:info'+info+b'e'
    meta=torrent_meta(raw)
    assert meta=={'hashes':[hashlib.sha1(info).hexdigest()],'name':'example.iso'}
    assert 'passkey' not in str(meta)


def test_v2_and_hybrid_hashes():
    info=b'd12:meta versioni2e4:name1:xe'
    assert torrent_meta(b'd4:info'+info+b'e')['hashes']==[hashlib.sha256(info).hexdigest()]
    hybrid=b'd12:meta versioni2e4:name1:x6:pieces0:e'
    assert torrent_meta(b'd4:info'+hybrid+b'e')['hashes']==[
        hashlib.sha1(hybrid).hexdigest(),hashlib.sha256(hybrid).hexdigest()]


@pytest.mark.parametrize('raw', [b'',b'garbage',b'd4:info0:e',b'd4:infodeejunk',
    b'd4:infode4:infodee',b'd4:infod4:namei1eee',b'l'*40+b'e'*40,
    b'd4:infod4:name9999999:xe',b'd4:infod4:name1:x6:lengthi01eee'])
def test_invalid_bencode_is_rejected(raw):
    with pytest.raises(ValueError):
        torrent_meta(raw)


def test_magnet_hex_base32_and_v2():
    digest=hashlib.sha1(b'fixture').digest()
    assert magnet_meta('magnet:?xt=urn:btih:'+digest.hex()+'&dn=Demo')['hashes']==[digest.hex()]
    assert magnet_meta('magnet:?xt=urn:btih:'+base64.b32encode(digest).decode())['hashes']==[digest.hex()]
    assert magnet_meta('magnet:?xt=urn:btmh:1220'+'a'*64)['hashes']==['a'*64]
    with pytest.raises(ValueError):
        magnet_meta('magnet:?xt=urn:btih:bad')
