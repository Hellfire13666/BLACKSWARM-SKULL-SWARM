"""Vault Guard: offline snapshots, integrity checks and protection of live databases."""
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, closing
from pathlib import Path
from unittest.mock import patch

from blackswarm import app, bookmarks, collections, core, guard, tags
from blackswarm.neon import Neon


class VaultGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.research=core.Vault(self.root/'live-research')
        self.shelf=bookmarks.BookmarkShelf(self.root/'live-curation')
        self.folders=collections.IntelCollections(self.root/'live-curation')
        self.labels=tags.SwarmTags(self.root/'live-curation')
        sample={'url':'https://openlibrary.org/works/Example','title':'Linux Security References',
                'sources':['Open Library'],'relevance':'high','score':88,'snippet':'public link metadata'}
        session=self.research.store('cybersecurity','live',50,[sample],{'openlibrary':{'status':'ok','found':1}})
        bid,_=self.shelf.add(sample,session,'cybersecurity','Read later')
        folder=self.folders.create('Cybersecurity Reads','Personal notes')
        self.folders.add(folder,self.shelf.find(bid))
        self.labels.add(sample['url'],'toolkit Hacker')
        self.sources={'research':self.research.dbpath,'bookmarks':self.shelf.dbpath,
                      'collections':self.folders.path,'tags':self.labels.path}
        self.backups=self.root/'BACKUPS'
        self.hashes={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in self.sources.items()}

    def unchanged(self):
        self.assertEqual({name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in self.sources.items()},self.hashes)

    def test_preview_has_four_real_files_and_does_not_create(self):
        found=guard.preview(self.sources)
        self.assertEqual({x['status'] for x in found},{'READY'})
        self.assertFalse(self.backups.exists())
        self.unchanged()

    def test_create_snapshot_and_verify_four_stores(self):
        path,manifest=guard.create_backup(self.sources,self.backups)
        self.assertEqual(set(x['name'] for x in manifest['included']),set(self.sources))
        self.assertEqual(manifest['missing'],[])
        self.assertEqual(guard.verify_backup(path),manifest)
        self.assertEqual(len(guard.list_backups(self.backups)),1)
        self.assertEqual(path.stat().st_mode & 0o777,0o600 if os.name=='posix' else path.stat().st_mode & 0o777)
        with zipfile.ZipFile(path) as zf:
            contents=zf.namelist()
            self.assertIn('research/results.sqlite3',contents)
            self.assertIn('tags/tags.sqlite3',contents)
            self.assertNotIn('root/passwords',contents)
            self.assertNotIn(str(self.root),json.dumps(manifest))
            with zf.open('tags/tags.sqlite3') as f:
                self.assertEqual(f.read(16),b'SQLite format 3\x00')
        self.unchanged()

    def test_backup_does_not_duplicate_filename_and_no_overwrite(self):
        one,_=guard.create_backup(self.sources,self.backups)
        two,_=guard.create_backup(self.sources,self.backups)
        self.assertNotEqual(one,two)
        self.assertTrue(one.is_file() and two.is_file())
        self.unchanged()

    def test_missing_tags_reported_and_not_created(self):
        self.sources['tags'].unlink()
        path,manifest=guard.create_backup(self.sources,self.backups)
        self.assertEqual(manifest['missing'],['tags'])
        self.assertFalse(self.sources['tags'].exists())
        self.assertEqual(len(guard.verify_backup(path)['included']),3)
        for name,p in self.sources.items():
            if name!='tags':self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.hashes[name])

    def test_all_missing_refuses_without_creating_source(self):
        fake={k:self.root/'empty'/v.name for k,v in self.sources.items()}
        self.assertEqual({p['status'] for p in guard.preview(fake)},{'MISSING'})
        with self.assertRaisesRegex(ValueError,'No existing'):
            guard.create_backup(fake,self.backups)
        self.assertFalse(self.backups.exists())
        self.assertFalse((self.root/'empty').exists())
        self.unchanged()

    def test_symlink_source_refused(self):
        fake=dict(self.sources)
        fake['tags']=self.root/'link.sqlite3'
        fake['tags'].symlink_to(self.labels.path)
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            guard.create_backup(fake,self.backups)
        self.assertFalse(self.backups.exists())
        self.unchanged()

    def test_bad_zip_detected(self):
        path,_=guard.create_backup(self.sources,self.backups)
        path.write_bytes(b'NOT ZIP')
        with self.assertRaises(zipfile.BadZipFile):guard.verify_backup(path)
        self.unchanged()

    def test_tampered_manifest_hash_detected(self):
        path,_=guard.create_backup(self.sources,self.backups)
        with zipfile.ZipFile(path) as zf:
            payload={x.filename:zf.read(x) for x in zf.infolist()}
        manifest=json.loads(payload['manifest.json'])
        manifest['included'][0]['sha256']='0'*64
        payload['manifest.json']=json.dumps(manifest).encode()
        changed=self.backups/'BLACKSWARM-VAULT-GUARD-CHANGED.zip'
        with zipfile.ZipFile(changed,'w') as zf:
            for name,data in payload.items():zf.writestr(name,data)
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            guard.verify_backup(changed)
        self.unchanged()

    def test_zip_unexpected_paths_refused(self):
        path,_=guard.create_backup(self.sources,self.backups)
        with zipfile.ZipFile(path) as zf:
            payload={x.filename:zf.read(x) for x in zf.infolist()}
        strange=self.backups/'BLACKSWARM-VAULT-GUARD-UNEXPECTED.zip'
        with zipfile.ZipFile(strange,'w') as zf:
            for name,data in payload.items():zf.writestr(name,data)
            zf.writestr('unknown/secret.txt','x')
        with self.assertRaisesRegex(ValueError,'Unexpected'):
            guard.verify_backup(strange)
        self.unchanged()

    def test_read_only_verification_does_not_touch_source_db(self):
        path,_=guard.create_backup(self.sources,self.backups)
        guard.verify_backup(path)
        self.unchanged()

    def execute_menu(self,commands):
        with patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected network')), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('Unexpected browser')), \
             redirect_stdout(io.StringIO()) as buf:
            moves=iter(commands)
            guard.guard_desk(Neon('never'),input_fn=lambda prompt='':next(moves),sources=self.sources,backup_dir=self.backups)
        return buf.getvalue()

    def test_menu_preview_cancel_and_exit(self):
        result=self.execute_menu(['1','2','no','0'])
        self.assertIn('READY',result)
        self.assertIn('Canceled',result)
        self.assertFalse(self.backups.exists())
        self.unchanged()

    def test_menu_confirm_backup_and_verify(self):
        result=self.execute_menu(['2','BACKUP','3','1','0'])
        self.assertIn('VERIFIED PRIVATE BACKUP CREATED',result)
        self.assertIn('BACKUP VERIFIED: 4 SQLite snapshots',result)
        self.assertEqual(len(guard.list_backups(self.backups)),1)
        self.unchanged()

    def test_direct_mode_argparse_supported(self):
        with patch.object(guard,'guard_desk') as fn:
            app.main(['--vault-guard','--color','never'])
        fn.assert_called_once()
        self.unchanged()

    def test_sqlite_copy_is_readable_and_has_expected_rows(self):
        path,_=guard.create_backup(self.sources,self.backups)
        with zipfile.ZipFile(path) as zf, tempfile.TemporaryDirectory() as tmp:
            for archive,table in [('research/results.sqlite3','runs'),
                                  ('favorites/bookmarks.sqlite3','bookmarks'),
                                  ('collections/collections.sqlite3','collections'),
                                  ('tags/tags.sqlite3','tags')]:
                output=Path(tmp)/('test-'+archive.rsplit('/',1)[-1])
                output.write_bytes(zf.read(archive))
                with closing(sqlite3.connect(output)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],1)
        self.unchanged()

if __name__=='__main__': unittest.main()
