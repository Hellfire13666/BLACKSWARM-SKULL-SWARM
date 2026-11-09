"""Offline terminal navigator tests. No external sites, browser or data writes."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from blackswarm import app, core, navigator
from blackswarm.neon import Neon


def row(url,title,sources=('Wikipedia',),score=65,relevance='high'):
    return dict(url=url,title=title,snippet='Public metadata about defensive security research',
                sources=list(sources),score=score,relevance=relevance)


class NavigatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault=core.Vault(self.temp.name)
        self.rid=self.vault.store('ethical hacking cybersecurity','live',250,[
            row('https://example.org/a','Ethical Cybersecurity Research',('Wikipedia','Crossref')),
            row('https://example.org/b','Ethical Network Defense',('Crossref',),score=50,relevance='possible'),
            row('https://docs.example.net/c','Security Research Guide',('Internet Archive',)),
            row('https://docs.example.net/d','Unrelated Medical Article',('Europe PMC',),12,'low'),
            row('https://docs.example.net/e','Security Ethics and Network Defense',('Crossref',)),
            row('https://another.example/f','Security Research for Education',('Wikipedia',))
        ],{'crossref':{'status':'ok','found':3}})

    def test_index_and_matching(self):
        rows=self.vault.results(self.rid)
        idx=navigator.index_rows(rows)
        self.assertEqual(dict(idx['sources'])['Crossref'],3)
        self.assertEqual(dict(idx['domains'])['docs.example.net'],3)
        self.assertEqual(dict(idx['topics'])['security'],3)
        self.assertEqual(len(navigator.match_rows(rows,'source','Crossref')),3)
        self.assertEqual(len(navigator.match_rows(rows,'domain','docs.example.net')),3)
        self.assertEqual(len(navigator.match_rows(rows,'relevance','high')),4)
        self.assertEqual(len(navigator.match_rows(rows,'topic','ethical')),2)
        self.assertEqual(len(navigator.match_rows(rows,'text','medical')),1)
        self.assertEqual(navigator.match_rows(rows,'source','NONEXISTENT'),[])
        with self.assertRaises(ValueError):
            navigator.match_rows(rows,'unknown','test')

    def test_interactive_drill_down_paging_detail_and_back(self):
        rows=self.vault.results(self.rid)
        with patch('urllib.request.urlopen',side_effect=AssertionError('network')), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser')), \
             redirect_stdout(io.StringIO()) as out:
            with patch('builtins.input',side_effect=['1','1','1','n','p','b','5','medical','1','b','0']):
                navigator.navigate(Neon('never'),self.vault.run(self.rid),rows)
        result=out.getvalue()
        self.assertIn('SWARM CONSTELLATION NAVIGATOR',result)
        self.assertIn('DISCOVERY SOURCES',result)
        self.assertIn('LINK #1',result)
        self.assertIn('QUICK FIND',result)
        self.assertIn('Navigator closed',result)
        self.assertEqual(self.vault.count_runs(),1)

    def test_navigation_via_menu_reads_vault_without_writes(self):
        with patch.object(app.core,'Vault',return_value=self.vault), \
             patch.object(app.core,'STORE',self.vault.folder), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network')), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser')), \
             patch('builtins.input',side_effect=['11',str(self.rid),'2','1','b','0','0']), \
             redirect_stdout(io.StringIO()) as stdout:
            code=app.main(['--color','never'])
        self.assertEqual(code,0)
        self.assertIn('CONSTELLATION NAVIGATOR',stdout.getvalue())
        self.assertIn('TOPIC STARS',stdout.getvalue())
        self.assertEqual(self.vault.count_runs(),1)

    def test_cli_navigation(self):
        with patch.object(app.core,'Vault',return_value=self.vault), \
             patch.object(app.core,'STORE',self.vault.folder), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network')), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser')), \
             patch('builtins.input',side_effect=['0']), \
             redirect_stdout(io.StringIO()) as stdout:
            code=app.main(['--navigate',str(self.rid),'--color','never'])
        self.assertEqual(code,0)
        self.assertIn('SAVED PUBLIC LINKS',stdout.getvalue())

    def test_paging_over_eight_saved_links(self):
        records=[row(f'https://example.org/{n}',f'Security Topic {n}',score=100-n) for n in range(19)]
        with patch('builtins.input',side_effect=['n','n','p','10','b']), \
             redirect_stdout(io.StringIO()) as stdout:
            navigator.browse(Neon('never'),records,'SAVED SOURCE: Wikipedia')
        out=stdout.getvalue()
        self.assertIn('PAGE 1/3',out)
        self.assertIn('PAGE 2/3',out)
        self.assertIn('PAGE 3/3',out)
        self.assertIn('LINK #10',out)

    def test_vault_bytes_identical_after_read_only_navigation(self):
        import hashlib
        before=hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest()
        with patch.object(app,'VAULT',self.vault), \
             patch('builtins.input',side_effect=['3','1','b','0']), \
             redirect_stdout(io.StringIO()):
            app._terminal_navigator(Neon('never'),self.rid)
        after=hashlib.sha256(self.vault.dbpath.read_bytes()).hexdigest()
        self.assertEqual(before,after)

    def test_safe_output_for_untrusted_stored_titles(self):
        row_bad=row('https://example.org/x','Danger\x1b[31m\u202eRESET')
        with redirect_stdout(io.StringIO()) as stdout:
            navigator.show_detail(Neon('never'),row_bad)
        self.assertNotIn('\x1b',stdout.getvalue())
        self.assertNotIn('\u202e',stdout.getvalue())


if __name__=='__main__': unittest.main()
