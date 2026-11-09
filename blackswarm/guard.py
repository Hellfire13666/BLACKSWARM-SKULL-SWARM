"""BLACKSWARM VAULT GUARD: explicit offline backups and integrity verification.

Reads existing SQLite databases with SQLite's online backup API using readonly
connections. Backups are private ZIPs containing SHA-256 manifest and snapshots.
Never creates missing vaults, restores sources, runs network actions or opens UI.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from contextlib import closing
import shutil
from pathlib import Path
from urllib.parse import quote

from . import core, bookmarks

# Stable logical ZIP locations, never embedded user-specific paths.
DB_NAMES = {
    'research': ('research/results.sqlite3', 'results.sqlite3'),
    'bookmarks': ('favorites/bookmarks.sqlite3', 'bookmarks.sqlite3'),
    'collections': ('collections/collections.sqlite3', 'collections.sqlite3'),
    'tags': ('tags/tags.sqlite3', 'tags.sqlite3'),
}
MAX_SOURCE_BYTES = 512 * 1024 * 1024  # 512MiB per store, fail safely.
MAX_MANIFEST_BYTES = 64 * 1024


def source_paths(research_root=None, curation_root=None):
    """No disk changes. Defaults respect the same environment as existing vaults."""
    research = Path(research_root) if research_root is not None else core.STORE
    curation = Path(curation_root) if curation_root is not None else bookmarks.BOOKMARKS_HOME
    return {
        'research': research / DB_NAMES['research'][1],
        'bookmarks': curation / DB_NAMES['bookmarks'][1],
        'collections': curation / DB_NAMES['collections'][1],
        'tags': curation / DB_NAMES['tags'][1],
    }


def backup_destination(folder=None):
    if folder is not None:
        return Path(folder)
    return Path(os.environ.get('BLACKSWARM_BACKUP_DIR', str(Path.home()/'Documents'/'BLACKSWARM-EXPORTS'/'PRIVATE-VAULT-BACKUPS')))


def _status(path):
    """Reject symlinks and nonregular sources rather than following them."""
    if path.is_symlink():
        return 'UNSAFE (symlink)'
    if not path.exists():
        return 'MISSING'
    if not path.is_file():
        return 'UNSAFE (not a file)'
    return 'READY'


def preview(sources=None):
    sources = source_paths() if sources is None else sources
    return [{'name': name, 'path':str(path), 'status':_status(path),
             'bytes':path.stat().st_size if _status(path)=='READY' else 0}
            for name,path in sources.items()]


def _ro_sqlite(path):
    url = 'file:' + quote(str(path.absolute()), safe='/') + '?mode=ro'
    db = sqlite3.connect(url, uri=True, timeout=15)
    db.execute('PRAGMA query_only=ON')
    return db


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda:fh.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _quick_check(path):
    with closing(_ro_sqlite(path)) as db:
        check = db.execute('PRAGMA quick_check').fetchone()
    if not check or check[0] != 'ok':
        raise ValueError('SQLite integrity check failed')


def create_backup(sources=None, backup_dir=None):
    """Explicit operation: consistent snapshots into new ZIP, sources never updated.

    Returns (new_zip_path, manifest). A missing source is reported, not created.
    Refuses unsafe sources, empty backups, symlink destinations or overwrite.
    """
    sources = source_paths() if sources is None else sources
    if set(sources) != set(DB_NAMES):
        raise ValueError('Expected the four known BLACKSWARM source names')
    statuses = preview(sources)
    unsafe = [x['name'] for x in statuses if x['status'].startswith('UNSAFE')]
    if unsafe:
        raise ValueError('Unsafe vault path; refused: ' + ', '.join(unsafe))
    existing = [x for x in statuses if x['status']=='READY']
    if not existing:
        raise ValueError('No existing BLACKSWARM vaults to back up')
    if any(row['bytes'] > MAX_SOURCE_BYTES for row in existing):
        raise ValueError('One or more vaults exceed the 512 MiB safety limit')
    target = backup_destination(backup_dir)
    if target.is_symlink():
        raise ValueError('Refusing symlink backup folder')
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not target.is_dir():
        raise ValueError('Backup destination is not a folder')
    created = datetime.now(timezone.utc)
    name = 'BLACKSWARM-VAULT-GUARD-' + created.strftime('%Y%m%dT%H%M%S') + f'-{created.microsecond:06d}Z.zip'
    final = target/name
    archive_tmp = None
    try:
        with tempfile.TemporaryDirectory(prefix='blackswarm-snap-') as tmp:
            tmpdir = Path(tmp)
            entries=[]
            for row in existing:
                src = sources[row['name']]
                snapshot = tmpdir / (row['name']+'.sqlite3')
                # Use SQLite online backup for a consistent copy even if the
                # original DB has uncheckpointed WAL pages or active readers.
                with closing(_ro_sqlite(src)) as reader, closing(sqlite3.connect(snapshot)) as writer:
                    reader.backup(writer, pages=64, sleep=0.05)
                    writer.commit()
                _quick_check(snapshot)
                if snapshot.stat().st_size > MAX_SOURCE_BYTES:
                    raise ValueError('Snapshot exceeds the 512 MiB safety limit')
                entries.append({'name':row['name'], 'archive_path':DB_NAMES[row['name']][0],
                                'bytes':snapshot.stat().st_size, 'sha256':_sha256(snapshot),
                                'snapshot':snapshot})
            manifest={
                'format':'BLACKSWARM-VAULT-GUARD-v1',
                'created_utc':created.isoformat(timespec='seconds'),
                'included':[{'name':e['name'],'archive_path':e['archive_path'],
                             'bytes':e['bytes'],'sha256':e['sha256']} for e in entries],
                'missing':[r['name'] for r in statuses if r['status']=='MISSING'],
                'note':'Local SQLite research/curation only. Not encrypted. No restore performed.',
            }
            fd, path = tempfile.mkstemp(prefix='.blackswarm-building-', suffix='.zip', dir=target)
            archive_tmp = Path(path)
            os.chmod(archive_tmp,0o600)
            with os.fdopen(fd,'w+b') as buf:
                with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                    zf.writestr('manifest.json',json.dumps(manifest,sort_keys=True,indent=2)+'\n')
                    for entry in entries:
                        zf.write(entry['snapshot'],arcname=entry['archive_path'])
                buf.flush()
                os.fsync(buf.fileno())
            # Verify completed archive before publication.
            verify_backup(archive_tmp)
            os.link(archive_tmp,final)  # fails if destination exists; no clobber
            return final, manifest
    finally:
        if archive_tmp is not None:
            archive_tmp.unlink(missing_ok=True)


def _verify_zip_entry(zf,info,expected):
    if info.file_size != expected['bytes'] or info.file_size > MAX_SOURCE_BYTES:
        raise ValueError('Snapshot size does not match manifest')
    h=hashlib.sha256()
    with zf.open(info) as f:
        while True:
            data=f.read(1024*1024)
            if not data:break
            h.update(data)
    if h.hexdigest() != expected['sha256']:
        raise ValueError('Snapshot SHA-256 mismatch: ' + expected['name'])
    # Use a temporary private file for a genuine SQLite integrity check.
    # Never extract a ZIP-supplied path or modify any live database.
    with tempfile.TemporaryDirectory(prefix='blackswarm-verify-') as tmp:
        scratch=Path(tmp)/'verify.sqlite3'
        with zf.open(info) as origin, scratch.open('xb') as dest:
            shutil.copyfileobj(origin,dest,length=1024*1024)
        try:
            _quick_check(scratch)
        except sqlite3.Error as exc:
            raise ValueError('SQLite snapshot failed integrity check') from exc


def verify_backup(path):
    """Check a saved ZIP without writing any DB or extracting its data."""
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Backup is not a regular archive')
    with zipfile.ZipFile(path,'r') as zf:
        files = zf.infolist()
        names = [i.filename for i in files]
        if len(names)!=len(set(names)) or 'manifest.json' not in names or len(names)>5:
            raise ValueError('Unexpected or duplicate ZIP entries')
        info=zf.getinfo('manifest.json')
        if info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError('Manifest too large')
        with zf.open(info) as f:
            manifest=json.loads(f.read(MAX_MANIFEST_BYTES+1).decode('utf-8'))
        if manifest.get('format')!='BLACKSWARM-VAULT-GUARD-v1':
            raise ValueError('Unsupported manifest format')
        included=manifest.get('included')
        if not isinstance(included,list) or not (1<=len(included)<=4):
            raise ValueError('No valid included vaults')
        expected={'manifest.json'}
        names_seen=set()
        for entry in included:
            if not isinstance(entry,dict):
                raise ValueError('Invalid manifest entry')
            name=entry.get('name')
            if name not in DB_NAMES or name in names_seen:
                raise ValueError('Unexpected or duplicate vault name')
            names_seen.add(name)
            if entry.get('archive_path') != DB_NAMES[name][0]:
                raise ValueError('Unexpected archive path')
            if not isinstance(entry.get('bytes'),int) or entry['bytes']<100 or entry['bytes']>MAX_SOURCE_BYTES:
                raise ValueError('Invalid snapshot size')
            sha=entry.get('sha256','')
            if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
                raise ValueError('Invalid SHA-256 value')
            expected.add(entry['archive_path'])
            if entry['archive_path'] not in names:
                raise ValueError('Missing snapshot in archive')
            _verify_zip_entry(zf,zf.getinfo(entry['archive_path']),entry)
        if set(names)!=expected:
            raise ValueError('Archive contains unexpected files')
    return manifest


def list_backups(folder=None):
    root=backup_destination(folder)
    if root.is_symlink() or not root.is_dir():
        return []
    return sorted((p for p in root.glob('BLACKSWARM-VAULT-GUARD-*.zip')
                   if p.is_file() and not p.is_symlink()),reverse=True)


def guard_desk(neon,input_fn=None,sources=None,backup_dir=None):
    """Terminal menu: every write requires confirmation, no restore offered."""
    input_fn = input_fn or input
    sources = source_paths() if sources is None else sources
    dest = backup_destination(backup_dir)
    print('\n'+neon.fg('  ╔════════ BLACKSWARM // VAULT GUARD ═══════╗','purple',True))
    print(neon.fg('  ║ PRIVATE SNAPSHOTS · SHA-256 · VERIFY    ║','cyan'))
    print(neon.fg('  ╚═══════════════════════════════════════╝','purple'))
    print(neon.fg('  BLACKSWARM local vaults only. Not an outside-account recovery tool.','yellow'))
    print(neon.fg('  Backup ZIPs are NOT ENCRYPTED. Keep them private.','yellow'))
    while True:
        print('\n'+neon.fg('  ═════ VAULT GUARD CONTROL ═════','purple',True))
        for idx,color,caption in [('1','cyan','PREVIEW EXISTING VAULTS (READ-ONLY)'),
                                  ('2','green','CREATE PRIVATE SNAPSHOT BACKUP'),
                                  ('3','purple','VERIFY A SAVED BACKUP'),
                                  ('0','red','BACK TO COMMAND DECK')]:
            print(neon.fg(f'  [{idx}] ',color)+caption)
        choice=input_fn(neon.fg('  GUARD ❯ ','green',True)).strip().lower()
        if choice in ('0','q','quit',''):
            print(neon.fg('  Vault Guard closed. Nothing restored or overwritten.','purple'))
            return
        if choice=='1':
            print('\n'+neon.fg('  ☣ AVAILABLE BLACKSWARM DATABASES','purple',True))
            for item in preview(sources):
                color='green' if item['status']=='READY' else 'yellow'
                print(neon.fg(f"  {item['name'].upper():12} {item['status']}",color))
            print(neon.fg('  Preview only. No missing files created.','cyan'))
        elif choice=='2':
            available=[r for r in preview(sources) if r['status']=='READY']
            if not available:
                print(neon.fg('  No existing local vaults to back up.','yellow'));continue
            print(neon.fg(f'  Copy {len(available)} existing vault(s) to a NEW private ZIP.','cyan'))
            print(neon.fg('  No live file will be replaced. Unencrypted local backup.','yellow'))
            confirm=input_fn(neon.fg('  Type BACKUP to create a separate archive: ','green')).strip()
            if confirm != 'BACKUP':
                print(neon.fg('  Canceled.','yellow'));continue
            try:
                path,manifest=create_backup(sources,dest)
            except (OSError,ValueError,sqlite3.Error,zipfile.BadZipFile) as exc:
                print(neon.fg('  Backup failed: '+str(exc)[:200], 'red'));continue
            print(neon.fg('  ✓ VERIFIED PRIVATE BACKUP CREATED.','green',True))
            print(neon.fg('  ARCHIVE ','cyan')+str(path))
            print(neon.fg(f"  {len(manifest['included'])} databases  |  {len(manifest['missing'])} missing  |  SHA-256 verified",'green'))
        elif choice=='3':
            backups=list_backups(dest)
            if not backups:
                print(neon.fg('  No Vault Guard backups found in the private backup folder.','yellow'))
                continue
            for idx,path in enumerate(backups[:30],1):
                print(neon.fg(f'  [{idx}] ', 'cyan')+path.name)
            number=input_fn(neon.fg('  Backup number to verify (Enter = cancel): ','cyan')).strip()
            if not number:continue
            if not number.isdecimal() or not 1<=int(number)<=min(len(backups),30):
                print(neon.fg('  Invalid backup number.','yellow'));continue
            try:
                manifest=verify_backup(backups[int(number)-1])
                print(neon.fg(f"  ✓ BACKUP VERIFIED: {len(manifest['included'])} SQLite snapshots match SHA-256.",'green'))
                print(neon.fg('  Read-only verification. No live databases altered.','cyan'))
            except (OSError,ValueError,json.JSONDecodeError,zipfile.BadZipFile) as exc:
                print(neon.fg('  Verification failed: '+str(exc)[:200],'red'))
        else:
            print(neon.fg('  Select 0, 1, 2 or 3.','yellow'))
