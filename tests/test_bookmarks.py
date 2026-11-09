"""BLACKSWARM bookmark shelf tests: local-only and isolated from research vault."""
import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from blackswarm import app, core, navigator, bookmarks
from blackswarm.neon import Neon


def entry(url, title='Defensive Security Reference'):
    return dict(url=url,title=title,snippet='A public document description',
                sources=['Crossref','Wikipedia'],relevance='high',score=81)


class BookmarkTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.vault=core.Vault(self.root/'research')
        self.rows=[entry('https://example.org/first'),entry('https://example.org/second','Open source cyber defense'),
                   entry('https://example.org/third','Public cyber research report')]
        self.id=self.vault.store('ethical hacking cybersecurity','live',100,self.rows,{'crossref':{'status':'ok','found':3}})
        self.shelf=bookmarks.BookmarkShelf(self.root/'favorites')

    def test_save_reopen_and_duplicate_preserves_note(self):
        id1,new=self.shelf.add(self.rows[0],self.id,'ethical hacking cybersecurity','top choice')
        self.assertTrue(new)
        id2,new=self.shelf.add(self.rows[0],self.id,'different search','overwrite?')
        self.assertFalse(new)
        self.assertEqual(id1,id2)
        self.assertEqual(self.shelf.find(id1)['note'],'top choice')
        self.assertEqual(len(bookmarks.BookmarkShelf(self.root/'favorites').all()),1)
        self.assertEqual(self.shelf.find(id1)['session_id'],self.id)

    def test_note_edit_and_remove_with_confirmation(self):
        bid,_=self.shelf.add(self.rows[0],self.id,'ethical hacking cybersecurity')
        with patch('builtins.input',side_effect=['4',str(bid),'NO','0']),redirect_stdout(io.StringIO()):
            bookmarks.bookmark_desk(Neon('never'),self.vault,self.shelf)
        self.assertIsNotNone(self.shelf.find(bid))
        self.assertTrue(self.shelf.update_note(bid,'edited note'))
        self.assertEqual(self.shelf.find(bid)['note'],'edited note')
        with patch('builtins.input',side_effect=['4',str(bid),'REMOVE','0']),redirect_stdout(io.StringIO()):
            bookmarks.bookmark_desk(Neon('never'),self.vault,self.shelf)
        self.assertIsNone(self.shelf.find(bid))
        self.assertEqual(len(self.vault.results(self.id)),3)

    def test_navigator_favorite_no_network_or_browser(self):
        initial=hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest()
        with patch('urllib.request.urlopen',side_effect=AssertionError('network')), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser')), \
             patch('builtins.input',side_effect=['1','1','f 1','An excellent source','b','0']), \
             redirect_stdout(io.StringIO()) as out:
            navigator.navigate(Neon('never'),self.vault.run(self.id),self.vault.results(self.id),
                bookmark_factory=lambda:self.shelf)
        self.assertIn('SAVED to BOOKMARKED INTEL',out.getvalue())
        self.assertEqual(len(self.shelf.all()),1)
        self.assertEqual(self.shelf.all()[0]['note'],'An excellent source')
        self.assertEqual(hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest(),initial)

    def test_bookmark_desk_add_filtered_and_list(self):
        with patch('builtins.input',side_effect=['2',str(self.id),'cyber defense','f 1','useful','b','1','1','b','0']), \
             redirect_stdout(io.StringIO()) as output:
            bookmarks.bookmark_desk(Neon('never'),self.vault,self.shelf)
        self.assertIn('STAR LINKS',output.getvalue())
        self.assertIn('★',output.getvalue())
        self.assertEqual(self.shelf.all()[0]['title'],'Open source cyber defense')

    def test_search_bookmarks_offline(self):
        self.shelf.add(self.rows[0],self.id,'ethical hacking cybersecurity','purple research note')
        with patch('builtins.input',side_effect=['6','purple','0']),redirect_stdout(io.StringIO()) as out:
            bookmarks.bookmark_desk(Neon('never'),self.vault,self.shelf)
        self.assertIn('1 SAVED FAVORITES MATCH',out.getvalue())

    def test_exports_json_csv_and_spreadsheet_formula_guard(self):
        row=entry('https://example.org/formula','=cmd()')
        self.shelf.add(row,self.id,'search','@SUM(1,1)')
        data=json.loads(self.shelf.export('json'))
        self.assertEqual(data['count'],1)
        self.assertEqual(data['items'][0]['title'],'=cmd()')
        records=list(csv.DictReader(io.StringIO(self.shelf.export('csv').decode('utf-8-sig'))))
        self.assertEqual(records[0]['title'],"'=cmd()")
        self.assertEqual(records[0]['note'],"'@SUM(1,1)")
        with self.assertRaises(ValueError):self.shelf.export('html')

    def test_reject_unusable_urls_and_escape_untrusted_metadata(self):
        with self.assertRaises(ValueError):
            self.shelf.add(entry('javascript:alert(1)'),self.id,'search')
        bid,_=self.shelf.add(entry('https://example.org/clean','Bad\x1b[31m\u202eTITLE'),self.id,'test','line\n2\x1b[0m')
        value=self.shelf.find(bid)
        self.assertNotIn('\x1b',value['title'])
        self.assertNotIn('\u202e',value['title'])
        self.assertNotIn('\n',value['note'])

    def test_previous_sessions_unchanged_and_no_auto_browser(self):
        initial=hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest()
        with patch.object(app,'VAULT',self.vault), \
             patch('blackswarm.app.bookmarks.BookmarkShelf',return_value=self.shelf), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network')), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser')), \
             patch('builtins.input',side_effect=['0']), redirect_stdout(io.StringIO()) as out:
            app._terminal_bookmarks(Neon('never'))
        self.assertIn('BOOKMARKED INTEL',out.getvalue())
        self.assertEqual(hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest(),initial)

    def test_menu_12_available_and_no_html(self):
        with patch.object(app.core,'Vault',return_value=self.vault), \
             patch('blackswarm.app.bookmarks.BookmarkShelf',return_value=self.shelf), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser')), \
             patch('builtins.input',side_effect=['12','0','0']), \
             redirect_stdout(io.StringIO()) as out:
            self.assertEqual(app.main(['--color','never']),0)
        self.assertIn('[12]',out.getvalue())
        self.assertIn('BOOKMARKED INTEL',out.getvalue())

    def test_export_from_menu_never_overwrites(self):
        self.shelf.add(self.rows[0],self.id,'ethical hacking')
        with patch('pathlib.Path.home',return_value=self.root), \
             patch('builtins.input',side_effect=['5','json','5','json','0']), \
             redirect_stdout(io.StringIO()) as out:
            bookmarks.bookmark_desk(Neon('never'),self.vault,self.shelf)
        path=self.root/'Documents'/'BLACKSWARM-EXPORTS'
        files=sorted(path.glob('BLACKSWARM-BOOKMARKS-*.json'))
        self.assertEqual(len(files),2)
        self.assertEqual(json.loads(files[0].read_text())['count'],1)
        self.assertEqual(json.loads(files[1].read_text())['count'],1)


if __name__=='__main__':unittest.main()
