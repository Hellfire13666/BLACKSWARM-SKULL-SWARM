"""SWARM TAGS: isolation, persistence, terminal menus and adversarial inputs."""
import hashlib
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from blackswarm import bookmarks, collections, core, tags
from blackswarm.neon import Neon


class SwarmTagTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.research=core.Vault(self.root/'research')
        self.shelf=bookmarks.BookmarkShelf(self.root/'bookmarks')
        self.collections=collections.IntelCollections(self.root/'bookmarks')
        row={'url':'https://openlibrary.org/works/Example','title':'Rainbow cybersecurity reference',
             'sources':['Open Library'],'relevance':'high','score':96,'snippet':'Public educational resource'}
        self.sid=self.research.store('cybersecurity','live',50,[row],
                                     {'openlibrary':{'status':'ok','found':1}})
        self.bid,_=self.shelf.add(row,self.sid,'cybersecurity','Read later')
        self.one=self.collections.create('Cybersecurity Reads','research')
        self.two=self.collections.create('Second Shelf','reference')
        self.collections.add(self.one,self.shelf.find(self.bid))
        self.collections.add(self.two,self.shelf.find(self.bid))
        self.item=self.collections.items(self.one)[0]
        self.old_dbs=[self.research.dbpath,self.shelf.dbpath,self.collections.path]
        self.old_hashes={file:hashlib.sha256(file.read_bytes()).hexdigest() for file in self.old_dbs}

    def assert_old_vaults_unchanged(self):
        for file,old in self.old_hashes.items():
            self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),old,str(file))

    def tag_store(self):
        return tags.SwarmTags(self.root/'bookmarks')

    def execute_menu(self,prompts,color='never'):
        with patch('builtins.input',side_effect=prompts), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network!')), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser!')), \
             redirect_stdout(io.StringIO()) as out:
            collections.collection_desk(Neon(color),self.collections,self.shelf)
        return out.getvalue()

    def test_add_list_persist_casefold_dedup(self):
        tagstore=self.tag_store()
        self.assertTrue(tagstore.add(self.item['url'],'Cybersecurity'))
        self.assertFalse(tagstore.add(self.item['url'],'CYBERSECURITY'))
        self.assertTrue(tagstore.add(self.item['url'],'Read later'))
        self.assertEqual(tags.SwarmTags(self.root/'bookmarks').list_for(self.item['url']),
                         ['Cybersecurity','Read later'])
        self.assertEqual(len(tagstore.all()),2)
        self.assert_old_vaults_unchanged()

    def test_remove_only_one_label(self):
        store=self.tag_store()
        store.add(self.item['url'],'Alpha')
        store.add(self.item['url'],'Beta')
        self.assertTrue(store.remove(self.item['url'],'ALPHA'))
        self.assertFalse(store.remove(self.item['url'],'Alpha'))
        self.assertEqual(store.list_for(self.item['url']),['Beta'])
        self.assertEqual(self.collections.get(self.one)['link_count'],1)
        self.assert_old_vaults_unchanged()

    def test_validation_and_limits(self):
        store=self.tag_store()
        for text in ('','a','a,b','bad|tag','bad#tag',r'bad\tag'):
            with self.subTest(text=text),self.assertRaises(ValueError):
                store.add(self.item['url'],text)
        with self.assertRaises(ValueError):store.add('javascript:alert(1)','safe')
        for n in range(20):self.assertTrue(store.add(self.item['url'],f'tag{n:02d}'))
        self.assertFalse(store.add(self.item['url'],'TAG00'))
        with self.assertRaises(ValueError):store.add(self.item['url'],'tag20')
        self.assertEqual(len(store.list_for(self.item['url'])),20)
        self.assert_old_vaults_unchanged()

    def test_directory_permissions_and_no_downgrade(self):
        store=self.tag_store()
        if os.name=='posix':self.assertEqual(store.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(store.path.parent,self.collections.path.parent)
        self.assert_old_vaults_unchanged()

    def test_tags_created_only_when_menu_opened(self):
        self.assertFalse((self.root/'bookmarks'/'tags.sqlite3').exists())
        self.execute_menu(['8','0'])
        self.assertFalse((self.root/'bookmarks'/'tags.sqlite3').exists())
        self.execute_menu(['9','0','0'])
        self.assertTrue((self.root/'bookmarks'/'tags.sqlite3').exists())
        self.assert_old_vaults_unchanged()

    def test_interactive_add_find_and_rainbow(self):
        screen=self.execute_menu(['9','2',str(self.one),str(self.item['id']),
                                  'Reference','4','ref','5','0','0'],color='always')
        self.assertIn('★ TAG ADDED TO SAVED LINK',screen)
        self.assertIn('TAG RADAR: 1 SAVED LINKS',screen)
        self.assertIn('TAG NEBULA',screen)
        self.assertIn('1 UNIQUE LABELS',screen)
        self.assertIn('\x1b[',screen)
        self.assert_old_vaults_unchanged()

    def test_same_url_label_shared_across_two_collections(self):
        store=self.tag_store()
        store.add(self.item['url'],'Investigation')
        screen=self.execute_menu(['9','1','0','0'])
        self.assertIn('Investigation',screen)
        self.assertIn('FOLDERS #1 Cybersecurity Reads, #2 Second Shelf',screen)
        self.assertIn('TAG RADAR: 1 SAVED LINKS',screen)
        self.assert_old_vaults_unchanged()

    def test_interactive_remove_cancel_and_confirm(self):
        self.tag_store().add(self.item['url'],'Source')
        canceled=self.execute_menu(['9','3','1','1','Source','NO','0','0'])
        self.assertIn('Canceled. Nothing removed.',canceled)
        self.assertEqual(self.tag_store().list_for(self.item['url']),['Source'])
        confirmed=self.execute_menu(['9','3','1','1','source','REMOVE','0','0'])
        self.assertIn('TAG REMOVED',confirmed)
        self.assertEqual(self.tag_store().list_for(self.item['url']),[])
        self.assert_old_vaults_unchanged()

    def test_invalid_collection_item_and_blank_cancel(self):
        text=self.execute_menu(['9','2','999','2','1','999','2','1','1','',
                                '3','1','1','0','0'])
        self.assertIn('Collection ID not found.',text)
        self.assertIn('Item ID not found',text)
        self.assertIn('This link has no tags',text)
        self.assertEqual(self.tag_store().all(),[])
        self.assert_old_vaults_unchanged()

    def test_empty_find_and_chart_preserve_old_files(self):
        text=self.execute_menu(['9','4','notfound','5','0','0'])
        self.assertIn('TAG RADAR: 0 SAVED LINKS',text)
        self.assertIn('No active tags yet',text)
        self.assert_old_vaults_unchanged()

    def test_labels_only_chart_current_collection_links(self):
        store=self.tag_store()
        store.add('https://openlibrary.org/works/Example','Relevant')
        store.add('https://example.com/stale','Invisible')
        text=self.execute_menu(['9','5','0','0'])
        self.assertIn('1 UNIQUE LABELS',text)
        self.assertIn('Relevant',text)
        self.assertNotIn('Invisible',text)
        self.assert_old_vaults_unchanged()

    def test_existing_views_exports_unchanged(self):
        store=self.tag_store()
        store.add(self.item['url'],'Reference')
        before=self.collections.export(self.one,'json')
        text=self.execute_menu(['1','1','b','7','cybersecurity','','b','8','0'])
        self.assertIn('Cybersecurity Reads',text)
        self.assertIn('RADAR: 2 MATCHES',text)
        self.assertIn('COLLECTION PULSE',text)
        self.assertEqual(self.collections.export(self.one,'json'),before)
        self.assert_old_vaults_unchanged()


if __name__=='__main__':
    unittest.main()
