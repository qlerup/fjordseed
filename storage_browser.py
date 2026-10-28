"""Directory-only operations inside a scoped Docker helper."""
import json
import stat
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import sys

ROOTS = ('/mnt', '/media', '/srv')


def checked(root, value):
    if not isinstance(value, str) or not any(value == p or value.startswith(p + '/') for p in ROOTS):
        raise ValueError('Vælg en mappe under /mnt, /media eller /srv.')
    parts = PurePosixPath(value).parts[1:]
    if '..' in parts or len(value) > 1024:
        raise ValueError('Ugyldig mappesti.')
    result = root
    for part in parts:
        result = result / part
        if result.is_symlink():
            raise ValueError('Links kan ikke bruges som filplacering.')
    return result


def browse(root, value):
    if not value:
        return {'path': '', 'parent': None, 'directories': [
            {'name': p, 'path': p} for p in ROOTS if (root / p[1:]).is_dir() and not (root / p[1:]).is_symlink()]}
    directory = checked(root, value)
    if not directory.is_dir():
        raise ValueError('Mappen findes ikke på Docker-serveren.')
    directories = []
    truncated = False
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False) and not entry.name.startswith('.'):
                if len(directories) == 500:
                    truncated = True
                    break
                directories.append({'name': entry.name, 'path': value.rstrip('/') + '/' + entry.name})
    return {'path': value, 'parent': '' if value in ROOTS else str(PurePosixPath(value).parent),
            'directories': sorted(directories, key=lambda r: r['name'].lower()),
            'free_bytes': shutil.disk_usage(directory).free, 'truncated': truncated}


def probe(root, value):
    directory = checked(root, value)
    ancestor = directory
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not ancestor.is_dir() or ancestor == root:
        raise ValueError('Den overordnede mappe skal findes på serveren.')
    return {'ancestor': '/' + ancestor.relative_to(root).as_posix(),
            'relative': directory.relative_to(ancestor).as_posix()}


def mount_status(root, value, mountinfo=None):
    directory = checked(root, value)
    parts = PurePosixPath(value).parts
    required = len(parts) >= 3 and parts[1] in ('mnt', 'media')
    suggested = str(PurePosixPath(*parts[:4 if parts[1:3] == ('mnt', 'pve') else 3]))
    if not required:
        return {'ready': True, 'required': False, 'mount_target': suggested,
                'message': 'Placeringen bruger serverens lokale filsystem.'}
    if mountinfo is None:
        mountinfo = Path('/proc/self/mountinfo').read_text()
    candidates = []
    # /host is the LXC/Docker host root, not an extra storage mount.
    prefix = root.as_posix().rstrip('/')
    destination = prefix + value
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 10 or '-' not in fields:
            continue
        point = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4])
        kind = fields[fields.index('-') + 1]
        if kind in ('tmpfs', 'proc', 'sysfs', 'overlay', 'autofs'):
            continue
        if point.startswith(prefix + '/') and (destination == point or destination.startswith(point.rstrip('/') + '/')):
            candidates.append(point)
    mounted = max(candidates, key=len) if candidates else None
    return {'ready': bool(mounted), 'required': True,
            'mount_target': mounted[len(prefix):] if mounted else suggested,
            'message': 'Mountet er tilgængeligt i LXC’en.' if mounted else
                       'Drevet er ikke monteret her. En almindelig mappe er ikke nok.'}


def create(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Ugyldig mappesti.')
    # Hold directory descriptors and never follow links, including during races.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in Path(relative).parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    finally:
        os.close(fd)
    return {'created': True}


def writable():
    import tempfile
    folder = Path('/folder/.incomplete')
    if folder.is_symlink():
        raise ValueError('Buffermappen må ikke være et link.')
    folder.mkdir(mode=0o755, exist_ok=True)
    shared=Path('/folder/.fjordseed-shared')
    if shared.is_symlink():raise ValueError('Arbejdsmappe til konvertering må ikke være et link.')
    shared.mkdir(mode=0o755,exist_ok=True)
    for directory in (Path('/folder'), folder):
        with tempfile.TemporaryFile(dir=directory) as probe_file:
            probe_file.write(b'fjordseed')
            probe_file.flush()
    return {'writable':True}


def seeder(root=Path('/folder')):
    """Create only the app-owned seeding destination in the scoped download root."""
    import tempfile
    folder = root / 'Seeder'
    if folder.is_symlink():
        raise ValueError('Seeder-mappen må ikke være et link.')
    folder.mkdir(mode=0o775, exist_ok=True)
    if not folder.is_dir():
        raise ValueError('Seeder skal være en mappe.')
    with tempfile.TemporaryFile(dir=folder) as probe_file:
        probe_file.write(b'fjordseed')
        probe_file.flush()
    return {'created': True, 'directory': 'Seeder'}


def usage(directory):
    disk = shutil.disk_usage(directory)
    return {'total_bytes':disk.total, 'used_bytes':disk.used, 'free_bytes':disk.free,
            'reserved_bytes':max(0,disk.total-disk.used-disk.free)}


def temporary_usage(roots, config=None):
    """Allocated file bytes in buffers, without following links or counting hardlinks twice."""
    config=config or {}
    seen={}
    stages=config.get('rss_stages',[[] for _ in roots])
    stage_files={}
    selected_device=Path(roots[config.get('selected',0)]).stat().st_dev if roots else None
    def fail(error):
        if not isinstance(error,FileNotFoundError):raise error
    for index,root,name in ((i,r,n) for i,r in enumerate(roots) for n in ('.incomplete','.fjordseed-buffer')):
        buffer=Path(root)/name
        if buffer.is_symlink():raise ValueError('Buffermappen må ikke være et link.')
        if not buffer.exists():continue
        rss_roots=[Path(root)/p for p in stages[index]]
        for directory,dirs,files,fd in os.fwalk(buffer,follow_symlinks=False,onerror=fail):
            is_rss=any(Path(directory).is_relative_to(p) for p in rss_roots)
            owner=next((str(p.relative_to(root)) for p in rss_roots if Path(directory).is_relative_to(p)),None)
            for name in files:
                try:info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                except FileNotFoundError:continue  # Concurrent completion/removal.
                identity=(info.st_dev,info.st_ino)
                if stat.S_ISREG(info.st_mode):
                    previous=seen.get(identity)
                    seen[identity]=(info.st_blocks*512,is_rss or bool(previous and previous[1]))
                    if owner is not None and info.st_dev==selected_device:
                        stage_files.setdefault((index,owner),{})[identity]=(info.st_blocks*512,info.st_nlink==1)
    known=config.get('rss_known',True)
    return {'temporary_bytes':sum(n for n,rss in seen.values()),
            'rss_temporary_bytes':sum(n for n,rss in seen.values() if rss) if known else None,
            'current_rss_bytes':sum(n for (device,inode),(n,rss) in seen.items() if rss and device==selected_device) if known else None,
            'rss_stage_usage':[{'root':index,'stage':stage,'bytes':sum(n for n,_ in files.values()),
                'reclaimable_bytes':sum(n for n,exclusive in files.values() if exclusive)}
                for (index,stage),files in stage_files.items()]}


if __name__ == '__main__':
    try:
        action, value = sys.argv[1:3]
        result = temporary_usage(sorted(Path('/folder').iterdir(),key=lambda p:int(p.name)),json.loads(value)) if action == 'temporary_usage' else usage(Path('/folder')) if action == 'usage' else writable() if action == 'writable' else seeder() if action == 'seeder' else mount_status(Path('/host'), value) if action == 'mount' else create(Path('/folder'), value) if action == 'create' else (
            probe(Path('/host'), value) if action == 'probe' else browse(Path('/host'), value))
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else 'Mappen kunne ikke læses eller oprettes. Kontrollér sti og rettigheder.'}))
        sys.exit(1)
