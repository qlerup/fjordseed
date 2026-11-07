"""Decode SUP display sets and OCR them, retaining presentation times to 1 ms.

PGS is image-based. Never invent an end time or silently discard unreadable text.
"""
import io
import struct
import subprocess
import time
from subtitle_text import timestamp

OCR = {'en':'eng','da':'dan','sv':'swe','no':'nor','de':'deu','fr':'fra',
       'es':'spa','it':'ita','nl':'nld','pt':'por','fi':'fin','pl':'pol',
       'uk':'ukr','ar':'ara','ja':'jpn','ko':'kor','zh':'chi_sim'}


def rle(data, width, height):
    if not 0<width<=8192 or not 0<height<=4320: raise ValueError('Ugyldigt PGS-billede.')
    pixels=bytearray(width*height); x=y=i=0
    while i<len(data) and y<height:
        value=data[i]; i+=1
        if value: count=1
        else:
            if i>=len(data): raise ValueError('Afbrudt PGS-billede.')
            flags=data[i]; i+=1
            if flags==0:
                if x!=width: raise ValueError('Ufuldstændig PGS-billedlinje.')
                x=0; y+=1; continue
            count=flags & 0x3f
            if flags & 0x40:
                if i>=len(data): raise ValueError('Afbrudt PGS-billede.')
                count=(count<<8)|data[i]; i+=1
            if flags & 0x80:
                if i>=len(data): raise ValueError('Afbrudt PGS-farve.')
                value=data[i]; i+=1
        if not count or x+count>width: raise ValueError('Ugyldig PGS-billedlinje.')
        pixels[y*width+x:y*width+x+count]=bytes([value])*count; x+=count
    if y!=height and not(y==height-1 and x==width): raise ValueError('Ufuldstændigt PGS-billede.')
    return bytes(pixels)


def recognize(image, lang):
    from PIL import ImageOps
    image=ImageOps.expand(image,border=20,fill=255)
    output=io.BytesIO(); image.save(output,format='PNG')
    result=subprocess.run(['tesseract','stdin','stdout','-l',OCR.get(lang,'eng'),'--psm','6'],
        input=output.getvalue(),capture_output=True,timeout=45)
    if result.returncode: raise ValueError('PGS-tekstgenkendelse fejlede. Kontrollér at OCR-sproget er installeret.')
    text=result.stdout.decode('utf-8').strip()
    if not text: raise ValueError('En PGS-undertekst kunne ikke læses. Vælg et andet kildespor.')
    return text


def read_pgs(path, lang, ocr=recognize):
    from PIL import Image
    objects={}; fragments={}; palettes={}; composition=None; pending=None; cues=[]
    previous=0; wrap=0
    deadline=time.monotonic()+1800
    with open(path,'rb') as stream:
        while header:=stream.read(13):
            if time.monotonic()>deadline: raise ValueError('PGS-tekstgenkendelse overskred 30 minutter. Vælg et andet spor.')
            if len(header)!=13 or header[:2]!=b'PG': raise ValueError('Ugyldig PGS-fil.')
            pts,_,kind,length=struct.unpack('>IIBH',header[2:])
            if pts<previous and previous-pts>2**31: wrap+=2**32
            previous=pts; at=(pts+wrap+45)//90
            data=stream.read(length)
            if len(data)!=length: raise ValueError('Afbrudt PGS-fil.')
            if kind==0x14:
                if len(data)<2 or (len(data)-2)%5: raise ValueError('Ugyldig PGS-palette.')
                palette=palettes.setdefault(data[0],{})
                for i in range(2,len(data),5):
                    index,luma,_,_,alpha=data[i:i+5]
                    # Dark glyphs on white for Tesseract; transparent pixels stay white.
                    palette[index]=255-round(luma*alpha/255)
            elif kind==0x15:
                if len(data)<4: raise ValueError('Ugyldigt PGS-objekt.')
                ident=int.from_bytes(data[:2],'big'); flags=data[3]
                if flags & 0x80:
                    if len(data)<11: raise ValueError('Ugyldigt PGS-objekt.')
                    length=int.from_bytes(data[4:7],'big')-4
                    width,height=struct.unpack('>HH',data[7:11])
                    if not 0<length<=64*1024*1024: raise ValueError('PGS-objektet er for stort.')
                    fragments[ident]=[width,height,length,bytearray(data[11:])]
                else:
                    if ident not in fragments: raise ValueError('PGS-objektets begyndelse mangler.')
                    fragments[ident][3].extend(data[4:])
                obj=fragments[ident]
                if len(obj[3])>obj[2]: raise ValueError('Ugyldig PGS-objektlængde.')
                if flags & 0x40:
                    if len(obj[3])!=obj[2]: raise ValueError('PGS-objektet er ufuldstændigt.')
                    objects[ident]=(obj[0],obj[1],rle(obj[3],obj[0],obj[1]))
                    del fragments[ident]
            elif kind==0x16:
                if len(data)<11: raise ValueError('Ugyldig PGS-komposition.')
                width,height=struct.unpack('>HH',data[:4])
                if not 0<width<=8192 or not 0<height<=4320: raise ValueError('Ugyldig PGS-størrelse.')
                if data[7]&0x80: objects.clear(); fragments.clear(); palettes.clear()
                entries=[]; pos=11
                for _ in range(data[10]):
                    if pos+8>len(data): raise ValueError('Afbrudt PGS-komposition.')
                    ident,window,flags,x,y=struct.unpack('>HBBHH',data[pos:pos+8]); pos+=8
                    crop=None
                    if flags&0x80:
                        if pos+8>len(data): raise ValueError('Afbrudt PGS-beskæring.')
                        crop=struct.unpack('>HHHH',data[pos:pos+8]); pos+=8
                    entries.append((ident,x,y,crop))
                composition=(at,width,height,data[9],entries)
            elif kind==0x80 and composition:
                at,width,height,palette_id,entries=composition; composition=None
                if pending:
                    start,text=pending
                    if at<=start: raise ValueError('PGS-tidskoderne er ikke entydige.')
                    cues.append({'id':len(cues)+1,'timing':timestamp(start)+' --> '+timestamp(at),'text':text})
                    pending=None
                if entries:
                    canvas=Image.new('L',(width,height),255)
                    palette=palettes.get(palette_id)
                    if palette is None: raise ValueError('PGS-paletten mangler.')
                    for ident,x,y,crop in entries:
                        if ident not in objects: raise ValueError('PGS-billedet mangler.')
                        w,h,pixels=objects[ident]
                        image=Image.frombytes('L',(w,h),pixels).point([palette.get(i,255) for i in range(256)])
                        if crop:
                            cx,cy,cw,ch=crop; image=image.crop((cx,cy,cx+cw,cy+ch))
                        canvas.paste(image,(x,y))
                    from PIL import ImageOps
                    bounds=ImageOps.invert(canvas).getbbox()
                    if bounds: pending=(at,ocr(canvas.crop(bounds),lang))
                if len(cues)>20000: raise ValueError('PGS indeholder for mange blokke.')
    if pending: raise ValueError('Den sidste PGS-undertekst mangler en sluttid. Vælg et andet spor.')
    if not cues: raise ValueError('PGS-sporet indeholder ingen læsbare undertekster.')
    return cues
