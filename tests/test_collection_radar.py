"""Offline Collection Radar tests: search, mini-chart and vault safety."""
import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from blackswarm import bookmarks, collections, core
from blackswarm.neon import Neon


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.vault=core.Vault(self.root/'research')
        self.shelf=bookmarks.BookmarkShelf(self.root/'bookmarks')
        self.store=collections.IntelCollections(self.root/'bookmarks')
        self.first=self.store.create('Cybersecurity Reads','cybersecurity')
        self.second=self.store.create('Cloud Library','technical notes')
        row={'url':'https://openlibrary.org/works/OSINT','title':'Linux Hacking Toolkit Guide',
             'sources':['Open Library'],'relevance':'high','score':85,'snippet':'Linux guide'}
        self.sid=self.vault.store('ethical hacking cybersecurity','live',50,[row],
                                  {'openlibrary':{'status':'ok','found':1}})
        self.bid,_=self.shelf.add(row,self.sid,'ethical hacking cybersecurity',
                                  'Offline cybersecurity reading')
        self.assertTrue(self.store.add(self.first,self.shelf.find(self.bid)))
        self.assertTrue(self.store.add(self.second,self.shelf.find(self.bid)))
        self.snapshots={file:hashlib.sha256(file.read_bytes()).hexdigest()
                        for file in [self.vault.dbpath,self.shelf.dbpath,self.store.path]}

    def assert_unchanged(self):
        for path,sha in self.snapshots.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),sha,str(path))

    def test_search_title_word(self):
        data=self.store.radar_search('toolkit')
        self.assertEqual(len(data),2)
        self.assertEqual({d['collection_id'] for d in data},{self.first,self.second})
        self.assertEqual(data[0]['sources'],['Open Library'])
        self.assert_unchanged()

    def test_search_multiple_terms_across_fields(self):
        self.assertEqual(len(self.store.radar_search('linux cybersecurity')),2)
        self.assertEqual(len(self.store.radar_search('Linux ReadS')),1)
        self.assertEqual(len(self.store.radar_search('cloud security')),1) # cloud folder + note
        self.assert_unchanged()

    def test_search_case_insensitive_unicode_and_sources(self):
        self.assertEqual(len(self.store.radar_search('OPEN LIBRARY')),2)
        self.assertEqual(len(self.store.radar_search('openlibrary.org')),2)
        self.assertEqual(len(self.store.radar_search('HIGH')),2)
        self.assert_unchanged()

    def test_scoped_search_and_missing_collection(self):
        self.assertEqual(len(self.store.radar_search('linux',cid=self.first)),1)
        self.assertEqual(len(self.store.radar_search('cloud',cid=self.first)),0)
        with self.assertRaises(ValueError):self.store.radar_search('linux',cid=938282)
        self.assert_unchanged()

    def test_no_matches_blank_and_metadata_only(self):
        self.assertEqual(self.store.radar_search('not-in-these-records'),[])
        self.assertEqual(self.store.radar_search('   '),[])
        self.assert_unchanged()

    def test_pulse_unique_and_cross_collection_counts(self):
        data=self.store.radar_pulse()
        self.assertEqual(data['total_links'],2)
        self.assertEqual(data['unique_urls'],1)
        self.assertEqual(data['cross_collection_copies'],1)
        self.assertEqual(len(data['folders']),2)
        self.assert_unchanged()

    def test_interactive_radar_search_detail_no_network(self):
        prompts=['7','cybersecurity','', '1','b','0']
        with patch('builtins.input',side_effect=prompts),\
             patch('urllib.request.urlopen',side_effect=AssertionError('network accessed')),\
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser opened')),\
             redirect_stdout(io.StringIO()) as output:
            collections.collection_desk(Neon('never'),self.store,self.shelf)
        text=output.getvalue()
        self.assertIn('RADAR: 2 MATCHES',text)
        self.assertIn('RADAR ITEM #1',text)
        self.assertIn('Stored metadata only',text)
        self.assert_unchanged()

    def test_interactive_radar_filter_and_no_match(self):
        prompts=['7','toolkit',str(self.first),'b','7','no-such-keyword','', '0']
        with patch('builtins.input',side_effect=prompts),redirect_stdout(io.StringIO()) as output:
            collections.collection_desk(Neon('never'),self.store,self.shelf)
        self.assertIn('RADAR: 1 MATCHES',output.getvalue())
        self.assertIn('NO SAVED LINKS MATCH',output.getvalue())
        self.assert_unchanged()

    def test_interactive_invalid_scope_does_not_search(self):
        prompts=['7','linux','not-an-id','0']
        with patch('builtins.input',side_effect=prompts),redirect_stdout(io.StringIO()) as output:
            collections.collection_desk(Neon('never'),self.store,self.shelf)
        self.assertIn('Invalid collection ID',output.getvalue())
        self.assert_unchanged()

    def test_pulse_rainbow_terminal_no_network(self):
        with patch('builtins.input',side_effect=['8','0']),\
             patch('urllib.request.urlopen',side_effect=AssertionError('network accessed')),\
             redirect_stdout(io.StringIO()) as output:
            collections.collection_desk(Neon('always'),self.store,self.shelf)
        text=output.getvalue()
        self.assertIn('COLLECTION PULSE',text)
        self.assertIn('2 FOLDERS',text)
        self.assertIn('1 UNIQUE URLs',text)
        self.assertIn('1 CROSS-COLLECTION COPIES',text)
        self.assertIn('\x1b[',text)
        self.assert_unchanged()

    def test_empty_pulse_and_radar(self):
        empty=collections.IntelCollections(self.root/'empty')
        with redirect_stdout(io.StringIO()) as a:
            collections._collection_pulse(Neon('never'),empty)
        self.assertIn('0 FOLDERS',a.getvalue())
        with redirect_stdout(io.StringIO()) as b:
            collections._collection_radar(Neon('never'),empty,lambda p: 'ignored')
        self.assertIn('No collections yet',b.getvalue())
        self.assert_unchanged()

    def test_existing_collection_export_untouched(self):
        payload=self.store.export(self.first,'json')
        self.assertIn(b'Linux Hacking Toolkit Guide',payload)
        self.assert_unchanged()


if __name__=='__main__': unittest.main()
