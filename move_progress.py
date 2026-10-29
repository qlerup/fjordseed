"""Read-only copy estimates; preallocated but unwritten disk blocks do not count."""
from pathlib import Path
import struct

from conversion import checked


def written_bytes(path,size):
    try:
        import fcntl
        path=checked(path)
        if not path.exists():return 0
        with path.open('rb') as handle:
            start=0;written=0
            for _ in range(32):
                buffer=bytearray(32+56*128)
                struct.pack_into('<QQIIII',buffer,0,start,2**64-1-start,0,0,128,0)
                fcntl.ioctl(handle.fileno(),0xC020660B,buffer,True)
                count=struct.unpack_from('<QQIIII',buffer)[3]
                if not count:return min(size,written)
                for index in range(count):
                    extent=struct.unpack_from('<QQQQQIIII',buffer,32+56*index)
                    logical,length,flags=extent[0],extent[2],extent[5]
                    if not flags&(0x800|0x2|0x4):written+=max(0,min(size,logical+length)-logical)
                    start=logical+length
                if flags&1:return min(size,written)
    except (ImportError,OSError,ValueError):
        pass
    return None  # Unsupported filesystem/Windows or too fragmented: never guess 100%.


def estimate(job):
    total=sum(entry['size'] for entry in job['files'])
    written=0
    for entry in job['files']:
        value=written_bytes(Path(job['seed'])/entry['name'],entry['size'])
        if value is None:return {'phase_progress':None,'move_total_bytes':total}
        written+=value
    return {'phase_progress':min(99.9,100*written/total) if total else None,
            'move_bytes':written,'move_total_bytes':total,'move_estimated':True}
