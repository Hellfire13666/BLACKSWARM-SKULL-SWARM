"""INTEL COLLECTIONS regression tests: independently stored curation, no browser."""
import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from blackswarm import collections, bookmarks, core
from blackswarm.neon import Neon


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.vault=core.Vault(self.root/'research')
        row={'url':'https://example.org/cybersecurity','title':'Cybersecurity research',
             'sources':['Wikipedia'], 'relevance':'high','score':70,'snippet':'Public reference'}
        self.session=self.vault.store('cybersecurity','live',50,[row],{'wikipedia':{'status':'ok','found':1}})
        self.shelf=bookmarks.BookmarkShelf(self.root/'bookmarks')
        self.bid,_=self.shelf.add(row,self.session,'cybersecurity','Useful reference')
        self.vault_sha=hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest()
        self.bookmark_sha=hashlib.sha256(self.shelf.dbpath.read_bytes()).hexdigest()
        self.store=collections.IntelCollections(self.root/'bookmarks')

    def unchanged(self):
        self.assertEqual(hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest(),self.vault_sha)
        self.assertEqual(hashlib.sha256(self.shelf.dbpath.read_bytes()).hexdigest(),self.bookmark_sha)

    def test_folder_created_and_reopened(self):
        cid=self.store.create('Blue research','Articles I want to read')
        again=collections.IntelCollections(self.root/'bookmarks')
        self.assertEqual(again.get(cid)['name'],'Blue research')
        self.assertEqual(again.get(cid)['description'],'Articles I want to read')
        self.unchanged()

    def test_add_duplicate_does_not_double_count(self):
        cid=self.store.create('Security sources')
        item=self.shelf.find(self.bid)
        self.assertTrue(self.store.add(cid,item))
        self.assertFalse(self.store.add(cid,item))
        self.assertEqual(self.store.get(cid)['link_count'],1)
        self.assertEqual(self.store.items(cid)[0]['bookmark_id'],self.bid)
        self.unchanged()

    def test_same_bookmark_in_two_collections(self):
        a=self.store.create('Research papers')
        b=self.store.create('Reading list')
        self.store.add(a,self.shelf.find(self.bid))
        self.store.add(b,self.shelf.find(self.bid))
        self.assertEqual(len(self.store.items(a)),1)
        self.assertEqual(len(self.store.items(b)),1)
        self.unchanged()

    def test_removal_is_local_only(self):
        a=self.store.create('Reading')
        self.store.add(a,self.shelf.find(self.bid))
        item=self.store.items(a)[0]
        self.assertTrue(self.store.remove_link(a,item['id']))
        self.assertEqual(self.store.items(a),[])
        self.assertEqual(len(self.shelf.all()),1)
        self.unchanged()

    def test_favorite_removal_does_not_damage_collected_snapshot(self):
        a=self.store.create('Preserved')
        self.store.add(a,self.shelf.find(self.bid))
        self.shelf.delete(self.bid)
        self.assertEqual(len(self.store.items(a)),1)
        self.assertEqual(self.store.items(a)[0]['url'],'https://example.org/cybersecurity')
        self.assertEqual(hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest(),self.vault_sha)

    def test_invalid_names_duplicate_and_update(self):
        with self.assertRaises(ValueError):self.store.create('')
        a=self.store.create('Investigation')
        with self.assertRaises(ValueError):self.store.create('INVESTIGATION')
        self.assertTrue(self.store.update(a,name='Published studies',description='Offline notes'))
        self.assertEqual(self.store.get(a)['name'],'Published studies')
        self.unchanged()

    def test_csv_json_exports(self):
        a=self.store.create('Public Papers')
        self.store.add(a,self.shelf.find(self.bid))
        csv_rows=list(csv.DictReader(io.StringIO(self.store.export(a,'csv').decode('utf-8-sig'))))
        self.assertEqual(csv_rows[0]['title'],'Cybersecurity research')
        payload=json.loads(self.store.export(a,'json').decode())
        self.assertEqual(payload['links'][0]['url'],'https://example.org/cybersecurity')
        self.assertEqual(payload['collection']['name'],'Public Papers')
        self.unchanged()

    def test_csv_formula_sanitization(self):
        a=self.store.create('=HYPERLINK(1)')
        self.store.add(a,self.shelf.find(self.bid))
        csv_text=self.store.export(a,'csv').decode('utf-8-sig')
        self.assertIn("'=HYPERLINK(1)",csv_text)
        self.unchanged()

    def test_offline_menu_create_and_add_and_view(self):
        prompts=['2','Technical articles','Useful resources','3','1',str(self.bid),'1','1','b','0']
        with patch('builtins.input',side_effect=prompts),\
             patch('urllib.request.urlopen',side_effect=AssertionError('network accessed')),\
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser opened')),\
             redirect_stdout(io.StringIO()) as output:
            collections.collection_desk(Neon('never'),self.store,self.shelf)
        self.assertIn('COLLECTION #1 CREATED',output.getvalue())
        self.assertIn('LINK ADDED TO COLLECTION',output.getvalue())
        self.assertEqual(self.store.get(1)['link_count'],1)
        self.unchanged()

    def test_export_no_overwrite(self):
        a=self.store.create('Research')
        self.store.add(a,self.shelf.find(self.bid))
        prompts=['6',str(a),'csv','6',str(a),'csv','0']
        folder=self.root/'exports'
        with patch('builtins.input',side_effect=prompts),redirect_stdout(io.StringIO()):
            collections.collection_desk(Neon('never'),self.store,self.shelf,export_root=folder)
        self.assertTrue((folder/'BLACKSWARM-COLLECTION-1-001.csv').is_file())
        self.assertTrue((folder/'BLACKSWARM-COLLECTION-1-002.csv').is_file())
        self.unchanged()

    def test_remove_requires_confirmation(self):
        a=self.store.create('Research')
        self.store.add(a,self.shelf.find(self.bid))
        item=self.store.items(a)[0]['id']
        with patch('builtins.input',side_effect=['5',str(a),str(item),'NO','0']),redirect_stdout(io.StringIO()):
            collections.collection_desk(Neon('never'),self.store,self.shelf)
        self.assertEqual(self.store.get(a)['link_count'],1)
        with patch('builtins.input',side_effect=['5',str(a),str(item),'REMOVE','0']),redirect_stdout(io.StringIO()):
            collections.collection_desk(Neon('never'),self.store,self.shelf)
        self.assertEqual(self.store.get(a)['link_count'],0)
        self.assertEqual(len(self.shelf.all()),1)
        self.unchanged()

    def test_no_new_collection_when_quitting(self):
        with patch('builtins.input',return_value='0'),redirect_stdout(io.StringIO()):
            collections.collection_desk(Neon('never'),self.store,self.shelf)
        self.assertEqual(self.store.all(),[])
        self.unchanged()

if __name__=='__main__':unittest.main()
