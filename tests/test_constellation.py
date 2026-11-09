"""SWARM CONSTELLATION offline regressions: no browser, no external requests, no vault mutations."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from blackswarm import app, core, intel
from blackswarm.neon import Neon


def row(url, title, source, relevance='high', score=45):
    return {'url':url,'title':title,'snippet':'published public metadata',
            'sources':[source],'score':score,'relevance':relevance}


class ConstellationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault=core.Vault(self.temp.name)
        self.r1=self.vault.store('cybersecurity research','live',500,[
            row('https://example.org/a','Defensive Security Research','Wikipedia'),
            row('https://journal.example.org/b','Security Research Paper','Crossref'),
            {**row('https://example.org/c','Public Security Education','Wikipedia', 'possible'),
             'sources':['Wikipedia','Crossref']}
        ],{'wikipedia':{'status':'ok','found':2}},candidates=[
            {**row('https://example.org/a','Defensive Security Research','Wikipedia'),'selected':True},
            {**row('https://example.org/d','Other','Crossref','low'),'selected':False}])
        self.r2=self.vault.store('cybersecurity research','live',500,[
            row('https://example.org/a','Defensive Security Research','Wikipedia'),
            row('https://example.org/z','New Security Research Guide','Crossref')
        ], {'crossref':{'status':'ok','found':2}})

    def test_aggregates_sources_domains_terms_without_network(self):
        summary=intel.make_constellation(self.vault.run(self.r1),self.vault.results(self.r1),self.vault.candidates(self.r1))
        self.assertEqual(summary['total'],3)
        self.assertEqual(summary['multi_source'],1)
        self.assertEqual(dict(summary['sources'])['Wikipedia'],2)
        self.assertEqual(dict(summary['sources'])['Crossref'],2)
        self.assertEqual(dict(summary['domains'])['example.org'],2)
        self.assertEqual(summary['candidate_count'],2)
        self.assertEqual(summary['unselected_count'],1)
        self.assertIn('security',[t['topic'] for t in summary['topic_signals']])

    def test_deltas_count_only_saved_urls(self):
        diff=intel.compare_sessions(self.vault.run(self.r1),self.vault.results(self.r1),
                                    self.vault.run(self.r2),self.vault.results(self.r2))
        self.assertEqual((diff['added_count'],diff['absent_count'],diff['common_count']),(1,2,1))
        self.assertEqual(diff['added'][0]['url'],'https://example.org/z')
        with self.assertRaises(ValueError):
            intel.compare_sessions(self.vault.run(self.r1),[],self.vault.run(self.r1),[])

    def test_constellation_output_and_no_page_visit(self):
        with patch.object(app,'VAULT',self.vault), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser opened')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network used')), \
             redirect_stdout(io.StringIO()) as stream:
            app._terminal_constellation(Neon('never'),self.r1)
        out=stream.getvalue()
        for value in ('SWARM CONSTELLATION','DOMAIN NEBULA','TOPIC STARS','LINK DNA','Nothing'):
            if value!='Nothing':self.assertIn(value,out)
        self.assertEqual(self.vault.count_runs(),2)

    def test_delta_terminal_remains_read_only(self):
        with patch.object(app,'VAULT',self.vault), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser opened')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network used')), \
             redirect_stdout(io.StringIO()) as stream:
            app._terminal_delta(Neon('never'),self.r1,self.r2)
        out=stream.getvalue()
        self.assertIn('SWARM DELTA',out)
        self.assertIn('not content removed from the web',out)
        self.assertEqual(self.vault.count_runs(),2)

    def test_safe_printing_metadata(self):
        malicious='x\x1b[31m\u202eOTHER\x1b[0m'
        self.assertNotIn('\x1b',intel.safe_line(malicious))
        self.assertNotIn('\u202e',intel.safe_line(malicious))
        self.assertEqual(len(intel.chart_bar(7,10)),22)

    def test_menu_nine_and_ten_no_new_sessions(self):
        with patch.object(app.core,'Vault',return_value=self.vault), \
             patch.object(app.core,'STORE',self.vault.folder), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser opened')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network used')), \
             patch('builtins.input',side_effect=['9',str(self.r1),'10',str(self.r1),str(self.r2),'0']), \
             redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(app.main(['--color','never']),0)
        out=stream.getvalue()
        self.assertIn('SWARM CONSTELLATION',out)
        self.assertIn('SWARM DELTA',out)
        self.assertEqual(self.vault.count_runs(),2)

    def test_cli_view_supports_noninteractive_vault(self):
        with patch.object(app.core,'Vault',return_value=self.vault), \
             patch.object(app.core,'STORE',self.vault.folder), \
             patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser opened')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('network used')), \
             redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(app.main(['--constellation',str(self.r1),'--color','never']),0)
            self.assertEqual(app.main(['--compare',str(self.r1),str(self.r2),'--color','never']),0)
        self.assertIn('TOPIC STARS',stream.getvalue())
        self.assertEqual(self.vault.count_runs(),2)


if __name__=='__main__':
    unittest.main()
