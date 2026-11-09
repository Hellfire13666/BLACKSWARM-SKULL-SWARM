"""STAR CONTROL UX contract: terminal-only, safe bookmark writes, no research DB edits."""
import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from blackswarm import bookmarks, core, navigator
from blackswarm.neon import Neon


def result(url, title):
    return {'url':url, 'title':title, 'snippet':'Public reference',
            'sources':['Crossref'], 'relevance':'high','score':61}


class StarControlTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.vault=core.Vault(self.root/'research')
        self.rows=[result('https://example.org/one','Ethical Hacking Research'),
                   result('https://example.org/two','Network Defense Guide')]
        self.sid=self.vault.store('cybersecurity','live',50,self.rows,
             {'crossref':{'status':'ok','found':2}})
        self.shelf=bookmarks.BookmarkShelf(self.root/'bookmarks')
        self.unchanged=hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest()

    def check_vault_preserved(self):
        self.assertEqual(self.unchanged, hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest())

    def test_f_then_number_then_blank_note(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('network request')),\
             patch('webbrowser.open',side_effect=AssertionError('browser')),\
             patch('builtins.input',side_effect=['f','1','','b']),\
             redirect_stdout(io.StringIO()) as out:
            navigator.browse(Neon('never'),self.vault.results(self.sid),'SOURCES: Crossref',
                             bookmark_factory=lambda:self.shelf,session_id=self.sid,query='cybersecurity')
        self.assertIn('★ SELECTED: Ethical Hacking Research',out.getvalue())
        self.assertIn('★ SAVED',out.getvalue())
        self.assertEqual(self.shelf.all()[0]['note'],'')
        self.assertEqual(self.shelf.all()[0]['url'],'https://example.org/one')
        self.check_vault_preserved()

    def test_legacy_f_number_still_works(self):
        with patch('builtins.input',side_effect=['f 2','great','b']),redirect_stdout(io.StringIO()):
            navigator.browse(Neon('never'),self.vault.results(self.sid),'ALL',
                             bookmark_factory=lambda:self.shelf,session_id=self.sid,query='cybersecurity')
        self.assertEqual(self.shelf.all()[0]['url'],'https://example.org/two')
        self.assertEqual(self.shelf.all()[0]['note'],'great')
        self.check_vault_preserved()

    def test_repeated_command_is_not_silently_recorded_as_note(self):
        with patch('builtins.input',side_effect=['f','1','f 1','','b']),redirect_stdout(io.StringIO()) as out:
            navigator.browse(Neon('never'),self.vault.results(self.sid),'ALL',
                             bookmark_factory=lambda:self.shelf,session_id=self.sid,query='cybersecurity')
        self.assertIn('looks like a favorite command',out.getvalue())
        self.assertEqual(self.shelf.all()[0]['note'],'')
        self.check_vault_preserved()

    def test_single_f_cancellation_no_bookmark_storage(self):
        with patch('builtins.input',side_effect=['f','','b']),redirect_stdout(io.StringIO()) as out:
            navigator.browse(Neon('never'),self.vault.results(self.sid),'ALL',
                             bookmark_factory=lambda:self.shelf,session_id=self.sid,query='cybersecurity')
        self.assertIn('Bookmark canceled',out.getvalue())
        self.assertEqual(self.shelf.all(),[])
        self.check_vault_preserved()

    def test_e_then_id_edits_note_from_favorites_page(self):
        bid,_=self.shelf.add(self.rows[0],self.sid,'cybersecurity','f 1')
        with patch('builtins.input',side_effect=['1','e',str(bid),'Research this later','b','0']),\
             redirect_stdout(io.StringIO()) as out:
            bookmarks.bookmark_desk(Neon('never'),self.vault,self.shelf)
        self.assertIn('Note updated',out.getvalue())
        self.assertEqual(self.shelf.find(bid)['note'],'Research this later')
        self.check_vault_preserved()

    def test_e_id_shortcut_still_works(self):
        bid,_=self.shelf.add(self.rows[0],self.sid,'cybersecurity','old')
        with patch('builtins.input',side_effect=['1',f'e {bid}','fixed','b','0']),\
             redirect_stdout(io.StringIO()):
            bookmarks.bookmark_desk(Neon('never'),self.vault,self.shelf)
        self.assertEqual(self.shelf.find(bid)['note'],'fixed')
        self.check_vault_preserved()

if __name__=='__main__':unittest.main()
