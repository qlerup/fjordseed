"""Capture direct or buffered torrent storage and publish complete retained payloads."""
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import time
import uuid

from state import atomic

CONFIG = Path('/config')
SETTINGS = Path('/rpc/download-settings.json')
BUFFER = '.incomplete'
PUBLISHING_MARKER = '.fjordseed-publishing'
_lock = threading.RLock()


def file_deletion_plan(row,files,prefs):
    """Only qBittorrent-listed files beneath the worker's download mounts."""
    if row.get('state')=='moving':
        raise ValueError('Vent til flytningen er afsluttet, før filerne slettes.')
    if not isinstance(files,list) or not files or len(files)>10000:
        raise ValueError('Torrentens filliste er ikke tilgængelig.')
    folders=list(dict.fromkeys(v for v in (row.get('save_path'),row.get('download_path')) if v))
    if not folders:
        raise ValueError('Torrentens filplacering mangler.')
    plan=[]
    for folder in folders:
        path=PurePosixPath(folder)
        if (not isinstance(folder,str) or not path.is_absolute() or '..' in path.parts
                or '\\' in folder or any(ord(c)<32 for c in folder) or str(path)!=folder.rstrip('/')):
            raise ValueError('Torrentens filplacering er ugyldig.')
        if path.is_relative_to('/downloads'):
            root=PurePosixPath('/downloads')
        elif path.is_relative_to('/download-locations') and len(path.parts)>=3 and re.fullmatch('[a-f0-9]{32}',path.parts[2]):
            root=PurePosixPath('/download-locations')/path.parts[2]
        else:
            raise ValueError('Torrentens filer ligger uden for downloadmapperne.')
        for entry in files:
            name=entry.get('name') if isinstance(entry,dict) else None
            if (not isinstance(name,str) or not name or len(name)>4096 or name.startswith('/')
                    or '\\' in name or '..' in PurePosixPath(name).parts
                    or any(ord(c)<32 for c in name) or str(PurePosixPath(name))!=name):
                raise ValueError('Torrentens filliste indeholder en ugyldig sti.')
            relative=path.relative_to(root)/name
            plan.append((str(root),str(relative)))
            if prefs.get('incomplete_files_ext') is True:
                plan.append((str(root),str(relative)+'.!qB'))
    return list(dict.fromkeys(plan))


@contextmanager
def file_parent(root,relative):
    """Open every path component without following links, including mount roots."""
    if os.open not in os.supports_dir_fd or not hasattr(os,'O_NOFOLLOW'):
        raise ValueError('Sletning af kun filer kræver en Linux-downloadcontainer.')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    fd=os.open('/',flags)
    try:
        parts=PurePosixPath(root).parts[1:]+PurePosixPath(relative).parts
        for part in parts[:-1]:
            child=os.open(part,flags,dir_fd=fd)
            os.close(fd);fd=child
        yield fd,parts[-1]
    finally:
        os.close(fd)


def check_file_plan(plan,remove=False):
    deleted=0
    for root,relative in plan:
        try:
            with file_parent(root,relative) as (fd,name):
                info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('Fillisten indeholder links eller andet end almindelige filer.')
                if remove:
                    os.unlink(name,dir_fd=fd);deleted+=1
        except FileNotFoundError:
            pass  # Missing/not-yet-downloaded files are already absent.
    return deleted


def delete_torrent_files(api,row,prefs):
    ident=row['hash']
    files=api('torrents/files?hash='+ident).json()
    plan=file_deletion_plan(row,files,prefs)
    check_file_plan(plan)  # Refuse unsafe paths before changing the torrent state.
    api('torrents/stop',{'hashes':ident})
    for _ in range(40):
        rows=api('torrents/info?hashes='+ident).json()
        if len(rows)!=1 or rows[0].get('hash')!=ident:
            raise ValueError('Torrenten findes ikke længere.')
        current=rows[0]
        if current.get('state') in ('stoppedUP','stoppedDL','pausedUP','pausedDL'):
            break
        time.sleep(.1)
    else:
        raise ValueError('Torrenten er ikke stoppet endnu. Prøv igen om lidt.')
    # Refresh paths after the stop: no stale save path or rename may be deleted.
    latest=file_deletion_plan(current,api('torrents/files?hash='+ident).json(),prefs)
    if latest!=plan:
        raise ValueError('Torrentens filplacering er ændret. Kontrollér den, og prøv igen.')
    check_file_plan(plan)
    deleted=check_file_plan(plan,remove=True)
    set_files_deleted([row.get(k) for k in ('hash','infohash_v1','infohash_v2')],True)
    return {'ok':True,'deleted_files':deleted,'torrent_retained':True,'stopped':True}


def set_files_deleted(hashes,value):
    with transaction() as entries:
        for ident in hashes:
            if ident in entries:entries[ident]['files_deleted']=value


def files_deleted(ident):
    return bool(read(CONFIG/'download-storage.json',{}).get(ident,{}).get('files_deleted'))


def prepare_file_restart(ident):
    """Keep an explicit re-download hidden from Flix until complete again."""
    with transaction() as entries:
        record=entries.get(ident)
        if not record or not record.get('files_deleted'):return
        if record.get('convert'):return  # Re-download only the original; preserve library output.
        directory=record['target'] if record.get('published') else record['stage']
        plan=file_deletion_plan({'save_path':directory},[{'name':PUBLISHING_MARKER}],{})
        for root,relative in plan:
            with file_parent(root,relative) as (fd,name):
                marker=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=fd)
                os.close(marker)
        record['published']=False


def read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


@contextmanager
def transaction():
    CONFIG.mkdir(parents=True, exist_ok=True)
    with _lock, (CONFIG/'download-storage.lock').open('a+') as handle:
        try:
            import fcntl
        except ImportError:
            fcntl = None
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            entries = read(CONFIG/'download-storage.json', {})
            yield entries
            atomic(CONFIG/'download-storage.json', json.dumps(entries))
        finally:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_UN)


def download_root():
    settings = read(SETTINGS, {})
    root = Path(settings.get('path', '/downloads'))
    if root != Path('/downloads') and not re.fullmatch(r'/download-locations/[a-f0-9]{32}', root.as_posix()):
        raise ValueError('Ugyldig downloadplacering.')
    return root


def download_name(name):
    """One readable path component, also usable from Windows/NAS file browsers."""
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', str(name or ''))
    name=name.encode('utf-8',errors='ignore')[:160].decode('utf-8',errors='ignore').strip(' .')
    if not name:return 'Download-'+uuid.uuid4().hex[:8]
    if name.startswith('.') or name.split('.')[0].upper() in {
            'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        name='_'+name
    return name


def prepare(hashes, folder='', name='', convert=False):
    """Capture destination at add time, including across default-folder changes."""
    from rss import folder_path
    root = download_root()
    target = folder_path(folder, root)
    with transaction() as entries:
        # A repeated add must never overwrite an existing destination or policy.
        record = next((entries[h] for h in hashes if h in entries), None)
        if record is None:
            if convert:
                from conversion import require_enabled
                require_enabled()
            buffered=convert or read(SETTINGS,{}).get('streaming_enabled',True)
            parent=root/BUFFER if buffered else target
            if buffered and (root/BUFFER).is_symlink():
                raise ValueError('Buffermappen må ikke være et link.')
            if any(p.is_symlink() for p in (parent,*parent.parents,target,*target.parents)):
                raise ValueError('Downloadmappen må ikke indeholde links.')
            base=download_name(name)
            reserved={v[k].casefold() for v in entries.values() for k in ('stage','target')}
            for attempt in range(100):
                token=base if attempt==0 else base+'-'+uuid.uuid4().hex[:8]
                stage=parent/token
                destination=target/token
                if any(str(p).casefold() in reserved or p.exists() or p.is_symlink() for p in (stage,destination)):
                    continue
                try:stage.mkdir(parents=True, exist_ok=False)
                except FileExistsError:continue
                break
            else:raise ValueError('Kunne ikke oprette en unik downloadmappe.')
            record = {'stage': str(stage), 'target': str(destination), 'published': False}
            if convert:
                settings=read(SETTINGS,{})
                record.update(convert=True,conversion_bitrate=settings.get('conversion_bitrate',30),
                              conversion_target=settings.get('conversion_target','server'))
            if not buffered:
                # Lightweight marker also protects a future Flix connection from
                # indexing these files before the entire torrent is complete.
                (stage/PUBLISHING_MARKER).touch(exist_ok=False)
            for ident in hashes:
                entries[ident] = record
        return record['stage']


def forget(hashes):
    """Allow a later re-add to capture the current default, never remove payloads."""
    with transaction() as entries:
        stages = {entries[h]['stage'] for h in hashes if h in entries}
        for ident in list(entries):
            if entries[ident]['stage'] in stages:
                entries.pop(ident)
        for value in stages:
            try:
                Path(value).rmdir()  # Empty directories only; manual removal retains data.
            except OSError:
                pass


def managed_directory(value):
    if not isinstance(value,str) or len(value)>4096 or '\\' in value or any(ord(c)<32 for c in value):return False
    path=PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts or str(path)!=value:return False
    return path.is_relative_to('/downloads') or (
        path.is_relative_to('/download-locations') and len(path.parts)>=3
        and re.fullmatch('[a-f0-9]{32}',path.parts[2]) is not None)


def migration_target(root,name,entries):
    base=download_name(name)
    reserved={v[k].casefold() for v in entries.values() for k in ('stage','target')}
    for attempt in range(100):
        path=root/(base if attempt==0 else base+'-'+uuid.uuid4().hex[:8])
        if str(path).casefold() not in reserved and not path.exists() and not path.is_symlink():return path
    raise ValueError('Kunne ikke finde en ledig biblioteksmappe.')


def retained_library():
    settings=read(SETTINGS,{})
    library=settings.get('retained_library_path')
    if (library!=settings.get('path') or not managed_directory(library)
            or not re.fullmatch(r'/downloads|/download-locations/[a-f0-9]{32}',library or '')):
        return None
    return library


def publish_complete(api, rows):
    """Publish retained payloads; optionally migrate older torrents via qBittorrent."""
    errors = []
    library=retained_library()
    with transaction() as entries:
        active={row.get(k) for row in rows for k in ('hash','infohash_v1','infohash_v2') if row.get(k)}
        migration_busy=any(entries.get(h,{}).get('migration') and not entries[h].get('published')
                           and not entries[h].get('files_deleted') for h in active) or any(
            row.get('state')=='moving' for row in rows)
        for row in rows:
            record = next((entries.get(row.get(k)) for k in ('hash','infohash_v1','infohash_v2')
                           if entries.get(row.get(k))), None)
            if record and record.get('library_replaced'):
                continue
            if record and record.get('files_deleted'):
                continue
            if record and record.get('convert'):
                from conversion import reconcile
                try:
                    reconcile(api,row,record)
                    record.pop('conversion_error',None)
                except (OSError,ValueError,KeyError,TypeError):
                    record['conversion_error']='Konvertering/flytning afventer kontrol af filer, lager og skriverettigheder. Originalen beholdes.'
                    errors.append(record['conversion_error'])
                continue
            state = row.get('state', '')
            if (row.get('progress') != 1 or state not in {'uploading','stalledUP','forcedUP','stoppedUP','pausedUP','queuedUP'}
                    or row.get('share_limit_action') not in ('Stop', 'Remove')):
                continue
            current = str(row.get('save_path', '')).rstrip('/')
            # Only a connected, explicitly enabled library may adopt old downloads.
            # One migration at a time; native setLocation moves this torrent's files only.
            if (library and not migration_busy and managed_directory(current)
                    and not PurePosixPath(current).is_relative_to(library)
                    and (not record or record.get('published') or current==record['stage'])):
                try:
                    source=Path(current)
                    if not source.is_dir() or any(p.is_symlink() for p in (source,*source.parents)):
                        raise ValueError('Downloadmappen er ikke tilgængelig.')
                    destination=migration_target(Path(library),row.get('name',''),entries)
                    previous=record
                    record={'stage':current,'target':destination.as_posix(),'published':False,'migration':True,
                            'cleanup_stage':bool(previous and current in (previous['stage'],previous['target']))}
                    if previous:
                        for ident,value in list(entries.items()):
                            if value['stage']==previous['stage']:entries[ident]=record
                    for field in ('hash','infohash_v1','infohash_v2'):
                        ident=row.get(field)
                        if isinstance(ident,str) and re.fullmatch('[a-fA-F0-9]{40}|[a-fA-F0-9]{64}',ident):entries[ident]=record
                    migration_busy=True
                except (OSError,ValueError):
                    errors.append('En tidligere download kunne ikke klargøres til FjordFlix. Kontrollér lager og skriverettigheder.')
                    continue
            if not record or record.get('published'):continue
            if current == record['target']:
                # setLocation is asynchronous: acknowledge only on a later poll.
                try:
                    (Path(record['target']) / PUBLISHING_MARKER).unlink(missing_ok=True)
                except OSError:
                    errors.append('En færdig download kunne ikke frigives til biblioteket. Kontrollér skriverettigheder.')
                    continue
                record['published'] = True
                for key, value in entries.items():
                    if value['stage'] == record['stage']:
                        value['published'] = True
                if record.get('cleanup_stage',True):
                    try:
                        Path(record['stage']).rmdir()
                    except OSError:
                        pass
                continue
            if current != record['stage']:
                errors.append('En torrent har skiftet placering; automatisk flytning er sat på pause.')
                continue
            try:
                target = Path(record['target'])
                # Never merge into another release, follow links, or overwrite files.
                for part in (target, *target.parents):
                    if part.is_symlink():
                        raise ValueError('Målmappen indeholder et link.')
                if target.exists() and any(p.name != PUBLISHING_MARKER for p in target.iterdir()):
                    raise ValueError('Målmappen indeholder allerede filer; flytningen afventer kontrol.')
                target.mkdir(parents=True, exist_ok=True)
                # Flix must not index the destination during an asynchronous copy.
                marker = target / PUBLISHING_MARKER
                if marker.is_symlink():
                    raise ValueError('Flyttemarkeringen må ikke være et link.')
                marker.touch(exist_ok=True)
                api('torrents/setLocation', {'hashes':row['hash'], 'location':str(target)})
            except Exception:
                errors.append('En færdig download kunne ikke flyttes. Kontrollér lager og skriverettigheder.')
    return errors


def moving_progress(row, entries):
    """Best-effort estimate; qBittorrent does not expose native move progress."""
    record = next((entries.get(row.get(k)) for k in ('hash','infohash_v1','infohash_v2')
                   if entries.get(row.get(k))), None)
    if record and record.get('files_deleted'):
        return {'files_deleted':True,'progress':0,'completed':0}
    if record and record.get('convert'):
        from conversion import status
        result=status(record)
        if record.get('conversion_error'):
            result={'state':'error','progress':0,'detail':record['conversion_error']}
        return {'conversion':result,'conversion_enabled':True}
    if row.get('state') != 'moving':
        return {}
    unknown = {'move_progress': None}
    if not record or not row.get('size') or row['size'] <= 0:
        return unknown
    destination = Path(record['target'] if row.get('share_limit_action') in ('Stop','Remove') else record['stage'])
    if str(destination).rstrip('/') == str(row.get('save_path','')).rstrip('/'):
        return unknown
    try:
        if any(p.is_symlink() for p in (destination, *destination.parents)):
            return unknown
        if not destination.is_dir():
            return unknown
        allocated, count = 0, 0
        def failed(error):
            raise error
        for directory, dirs, files in os.walk(destination, followlinks=False, onerror=failed):
            dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink()]
            for name in files:
                path = Path(directory)/name
                if path.is_symlink():
                    continue
                count += 1
                if count > 10000:
                    return unknown
                info = path.stat()
                if not hasattr(info, 'st_blocks'):
                    return unknown  # File length alone may be preallocated.
                allocated += min(info.st_size, info.st_blocks * 512)
        return {'move_progress': min(.99, allocated / row['size']), 'move_estimated': True}
    except OSError:
        return unknown
