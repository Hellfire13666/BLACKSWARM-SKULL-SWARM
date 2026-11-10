"""SOURCE PULSE offline tests: no public endpoint calls or user's vault access."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
from blackswarm import app, core, pulse
from blackswarm.neon import Neon


def row(url, sources):
    return {'url': url, 'title': 'Public research', 'snippet': '', 'sources': list(sources), 'score': 30, 'relevance':'possible'}


class PulseTests(unittest.TestCase):
    def setUp(self):
        self.reports = {'crossref': {'status': 'ok', 'found': 3, 'elapsed_ms': 125},
                        'wikipedia': {'status': 'empty', 'found': 0, 'elapsed_ms': 85},
                        'gdelt': {'status': 'error', 'found': 0, 'detail': 'HTTP 429', 'elapsed_ms': 300}}
        self.selected = [row('https://example.org/one', ['Crossref']), row('https://example.org/shared', ['Crossref','Wikipedia'])]
        self.candidates = self.selected + [row('https://example.org/third', ['Crossref','GDELT News'])]
        self.session = {'id':7, 'query':'public research', 'mode':'live', 'reports':json.dumps(self.reports)}

    def test_provider_unique_exclusive_overlap_and_selected(self):
        r=pulse.analyze(self.session,self.selected,self.candidates)
        self.assertEqual((r['candidate_count'],r['selected_count'],r['shared_count']),(3,2,2))
        x={row['key']:row for row in r['rows']}
        self.assertEqual(x['crossref']['contributed'],3)
        self.assertEqual(x['crossref']['exclusive'],1)
        self.assertEqual(x['crossref']['overlap'],2)
        self.assertEqual(x['crossref']['selected'],2)
        self.assertEqual(x['wikipedia']['selected'],1)
        self.assertEqual(x['gdelt']['elapsed_ms'],300)

    def test_tracking_duplicate_not_double_counted(self):
        rows=[row('https://example.org/a?utm_source=x',['Crossref']),row('https://example.org/a',['Crossref'])]
        r=pulse.analyze(self.session,rows,rows)
        self.assertEqual(r['candidate_count'],1)
        self.assertEqual(next(x for x in r['rows'] if x['key']=='crossref')['contributed'],1)

    def test_demo_not_mislabeled_as_live(self):
        r=pulse.analyze({'mode':'demo','reports':{'Demo':{'status':'sample only','found':7}}},[row('https://example.org/a',['Demo'])],[])
        self.assertEqual(r['rows'][0]['status'],'demo')
        self.assertEqual(r['candidate_basis'],'saved selected links only')
        with redirect_stdout(io.StringIO()) as output:pulse.display(Neon('never'),r)
        self.assertIn('DEMO ONLY',output.getvalue())

    def test_legacy_reports_no_timing(self):
        r=pulse.analyze({'id':1,'mode':'live','query':'test','reports':'{"crossref":{"status":"ok","found":12}}'},
                        [row('https://example.org/a',['Crossref'])],[])
        self.assertIsNone(r['rows'][0]['elapsed_ms'])
        with redirect_stdout(io.StringIO()) as o:pulse.display(Neon('never'),r)
        self.assertIn('n/a (old session)',o.getvalue())

    def test_malformed_reports_no_crash(self):
        for bad in ('{notjson', None, [], 12):
            with self.subTest(bad=bad):
                r=pulse.analyze({'mode':'live','reports':bad},[],[])
                self.assertEqual(r['rows'],[])

    def test_error_controls_sanitized(self):
        r=pulse.analyze({'mode':'live','reports':{'Crossref':{'status':'error','detail':'Oops\x1b[2J\x1b[1G'}}},[],[])
        with redirect_stdout(io.StringIO()) as o:pulse.display(Neon('never'),r)
        self.assertNotIn('\x1b[',o.getvalue())

    def test_empty_provider_status_reported(self):
        found={x['key']:x for x in pulse.analyze(self.session,[],[])['rows']}
        self.assertEqual(found['wikipedia']['status'],'empty')

    def test_readonly_session_and_no_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            v=core.Vault(tmp)
            sid=v.store('public research','live',50,self.selected,self.reports,candidates=self.candidates)
            before=Path(v.dbpath).read_bytes()
            with patch.object(app,'VAULT',v),patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('no browser')),redirect_stdout(io.StringIO()) as o:
                app._terminal_source_pulse(Neon('never'),sid)
            self.assertIn('SOURCE PULSE',o.getvalue())
            self.assertEqual(before,Path(v.dbpath).read_bytes())

    def test_cli_pulse_no_browser_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            v=core.Vault(tmp)
            sid=v.store('public research','live',50,self.selected,self.reports,candidates=self.candidates)
            with patch.object(app.core,'STORE',Path(tmp)),patch.object(app.core,'Vault',return_value=v),\
                patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('no browser')),\
                patch('blackswarm.core.http_get_json',side_effect=AssertionError('no network')),\
                redirect_stdout(io.StringIO()) as o:
                self.assertEqual(app.main(['--source-pulse',str(sid),'--color','never']),0)
            self.assertIn('SOURCE PULSE',o.getvalue())

    def test_live_search_records_latency_success_empty_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            v=core.Vault(tmp)
            with patch.object(app,'VAULT',v),patch.object(core,'crossref',return_value=[core.make_record('https://doi.org/10.1/test','Study','', 'Crossref')]),\
                patch.object(core,'wikipedia',return_value=[]),patch.object(core,'gdelt',side_effect=TimeoutError('slow')) ,\
                patch.object(app.time,'sleep',return_value=None),redirect_stdout(io.StringIO()):
                sid=app.run_search('public research',['crossref','wikipedia','gdelt'],50,quality='broad')
            r=json.loads(v.run(sid)['reports'])
            self.assertEqual([r[k]['status'] for k in ('crossref','wikipedia','gdelt')],['ok','empty','error'])
            self.assertTrue(all(isinstance(r[k]['elapsed_ms'],int) for k in r))

    def test_main_menu_option_15(self):
        with tempfile.TemporaryDirectory() as tmp:
            v=core.Vault(tmp)
            sid=v.store('public research','live',50,self.selected,self.reports,candidates=self.candidates)
            with patch.object(app.core,'Vault',return_value=v),patch('builtins.input',side_effect=['15',str(sid),'0']),\
                patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('no browser')),\
                redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.main(['--color','never']),0)
            self.assertIn('SOURCE PULSE',output.getvalue())
            self.assertIn('SWARM COMMAND DECK',output.getvalue())

if __name__=='__main__': unittest.main()
