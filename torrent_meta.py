"""Read torrent identity without fetching announce URLs or exposing passkeys."""
import base64
import hashlib
import re
from urllib.parse import parse_qs, urlsplit


def magnet_meta(magnet):
    if not isinstance(magnet,str) or len(magnet)>16384 or not magnet.startswith('magnet:?') or '\n' in magnet or '\r' in magnet:
        raise ValueError('Indtast et gyldigt magnetlink.')
    params=parse_qs(urlsplit(magnet).query)
    hashes=[]
    for xt in params.get('xt',[]):
        value=xt.removeprefix('urn:btih:')
        if xt.startswith('urn:btih:'):
            if re.fullmatch('[a-fA-F0-9]{40}',value):
                hashes.append(value.lower())
            elif re.fullmatch('[A-Za-z2-7]{32}',value):
                hashes.append(base64.b32decode(value.upper()).hex())
        elif re.fullmatch('urn:btmh:1220[a-fA-F0-9]{64}',xt):
            hashes.append(xt[13:].lower())
    if not hashes:
        raise ValueError('Magnetlinket mangler en gyldig info-hash.')
    return {'hashes':list(dict.fromkeys(hashes)), 'name':params.get('dn',[''])[0][:200]}


def torrent_meta(raw):
    if not raw or len(raw)>4*1024*1024:
        raise ValueError('Torrentfilen er ugyldig eller for stor.')
    pos=0
    nodes=0
    info_span=None

    def parse(depth=0):
        nonlocal pos,nodes,info_span
        nodes+=1
        if depth>32 or nodes>100000 or pos>=len(raw):
            raise ValueError('Torrentfilen er ugyldig.')
        token=raw[pos:pos+1]
        if token==b'i':
            end=raw.find(b'e',pos+1)
            value=raw[pos+1:end] if end>=0 else b''
            if not re.fullmatch(rb'0|-?[1-9][0-9]{0,19}',value):
                raise ValueError('Torrentfilen er ugyldig.')
            pos=end+1
            return int(value)
        if token in (b'd',b'l'):
            pos+=1
            result={} if token==b'd' else []
            while pos<len(raw) and raw[pos:pos+1]!=b'e':
                if token==b'd':
                    key=parse(depth+1)
                    if not isinstance(key,bytes) or key in result:
                        raise ValueError('Torrentfilen er ugyldig.')
                    start=pos
                    result[key]=parse(depth+1)
                    if depth==0 and key==b'info':
                        info_span=(start,pos)
                else:
                    result.append(parse(depth+1))
            if pos>=len(raw):
                raise ValueError('Torrentfilen er ugyldig.')
            pos+=1
            return result
        end=raw.find(b':',pos)
        length=raw[pos:end] if end>=0 else b''
        if not re.fullmatch(rb'0|[1-9][0-9]{0,7}',length):
            raise ValueError('Torrentfilen er ugyldig.')
        size=int(length)
        pos=end+1
        if pos+size>len(raw):
            raise ValueError('Torrentfilen er ugyldig.')
        value=raw[pos:pos+size]
        pos+=size
        return value

    data=parse()
    if pos!=len(raw) or not isinstance(data,dict) or not isinstance(data.get(b'info'),dict) or not info_span:
        raise ValueError('Torrentfilen mangler torrentoplysninger.')
    info=data[b'info']
    name=info.get(b'name.utf-8',info.get(b'name',b''))
    if not isinstance(name,bytes):
        raise ValueError('Torrentfilen har et ugyldigt navn.')
    encoded=raw[slice(*info_span)]
    hashes=[]
    if info.get(b'meta version')!=2 or b'pieces' in info:
        hashes.append(hashlib.sha1(encoded).hexdigest())
    if info.get(b'meta version')==2:
        hashes.append(hashlib.sha256(encoded).hexdigest())
    size=None
    lengths=[]
    if type(info.get(b'length')) is int:
        lengths=[info[b'length']]
    elif isinstance(info.get(b'files'),list):
        lengths=[entry.get(b'length') if isinstance(entry,dict) else None for entry in info[b'files']]
    elif isinstance(info.get(b'file tree'),dict):
        def visit(tree):
            for key,value in tree.items():
                if key==b'':
                    lengths.append(value.get(b'length') if isinstance(value,dict) else None)
                elif isinstance(value,dict):
                    visit(value)
                else:
                    lengths.append(None)
        visit(info[b'file tree'])
    if lengths and all(type(length) is int and 0<=length<=2**63-1 for length in lengths):
        total=sum(lengths)
        if total<=2**63-1:
            size=total
    return {'hashes':hashes,'name':name.decode('utf-8',errors='replace')[:200],'size':size}
