"""Generate the multi-resolution Fjord mark without image dependencies."""
from pathlib import Path
import struct


def image(size):
    pixels=bytearray()
    for y in range(size-1,-1,-1):
        for x in range(size):
            samples=[]
            for dx,dy in ((.25,.25),(.75,.25),(.25,.75),(.75,.75)):
                a,b=(x+dx)/size,(y+dy)/size
                cx,cy=max(.22,min(.78,a)),max(.22,min(.78,b))
                inside=.04<=a<=.96 and .04<=b<=.96 and (a-cx)**2+(b-cy)**2<=.18**2
                letter=(.29<=a<=.42 and .23<=b<=.79) or (.42<=a<=.75 and .23<=b<=.35) or (.42<=a<=.67 and .46<=b<=.58)
                samples.append((124,228,196,255) if inside and letter else (23,62,59,255) if inside else (23,62,59,0))
            r,g,b,alpha=[round(sum(s[i] for s in samples)/4) for i in range(4)]
            pixels.extend((b,g,r,alpha))
    mask=bytes(((size+31)//32)*4*size)
    return struct.pack('<IIIHHIIIIII',40,size,size*2,1,32,0,len(pixels),0,0,0,0)+pixels+mask


def main():
    sizes=(16,24,32,48,64,128,256)
    images=[image(size) for size in sizes]
    offset=6+16*len(sizes);entries=[]
    for size,data in zip(sizes,images):
        entries.append(struct.pack('<BBBBHHII',size if size<256 else 0,size if size<256 else 0,0,0,1,32,len(data),offset))
        offset+=len(data)
    Path(__file__).with_name('fjord.ico').write_bytes(struct.pack('<HHH',0,1,len(sizes))+b''.join(entries)+b''.join(images))


if __name__=='__main__':main()
