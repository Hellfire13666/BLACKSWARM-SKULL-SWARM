"""Offline tests: no provider network calls or modifications to user projects."""
import json
import io
from contextlib import redirect_stdout
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackswarm import core, app
from blackswarm.neon import Neon

class SearchTests(unittest.TestCase):
    def test_clean_url_and_dedup(self):
        u=core.clean_url('https://EXAMPLE.org/page?utm_campaign=x&a=b#foot')
        self.assertEqual(u,'https://example.org/page?a=b')
        self.assertEqual(core.clean_url('file:///etc/passwd'),'')
        self.assertEqual(core.clean_url('javascript:alert(1)'),'')
        self.assertEqual(core.clean_url('https://user:password@example.org/'),'')
        rows=[core.make_record('https://example.org/item?utm_source=x','A','b','Crossref'),
              core.make_record('https://example.org/item','A2','c','GDELT News')]
        merged=core.combine(rows,100)
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['sources'],['Crossref','GDELT News'])

    def test_searx_guard(self):
        self.assertEqual(core.searx_endpoint('https://search.example.org/any?abc=1'),'https://search.example.org/search')
        for bad in ['http://search.example.org','https://127.0.0.1','https://localhost',
                    'https://example.local','https://10.0.0.2','file:///tmp/x','https://user:pw@example.org']:
            with self.subTest(bad=bad), self.assertRaises(ValueError): core.searx_endpoint(bad)

    def test_wikipedia_adapter(self):
        def getter(url):
            self.assertIn('srsearch=test',url)
            return {'query':{'search':[{'title':'Public page','snippet':'<b>Result</b> text'}]}}
        got=core.wikipedia('test',50,get=getter)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]['url'],'https://en.wikipedia.org/wiki/Public_page')
        self.assertEqual(got[0]['snippet'],'Result text')

    def test_crossref_adapter(self):
        obj={'message':{'items':[{'DOI':'10.1234/test','URL':'https://doi.org/10.1234/test',
                                  'title':['Study title'],'container-title':['Science Journal']}]}}
        got=core.crossref('study',100,get=lambda _:obj)
        self.assertEqual(got[0]['title'],'Study title')
        self.assertEqual(got[0]['source'],'Crossref')

    def test_gdelt_adapter(self):
        obj={'articles':[{'url':'https://news.example.org/story','title':'News',
                          'domain':'news.example.org','seendate':'2026-11-08'}]}
        got=core.gdelt('study',100,get=lambda _:obj)
        self.assertEqual(got[0]['url'],'https://news.example.org/story')

    def test_searx_adapter(self):
        def getter(url):
            return {'results':[{'url':'https://example.org/a','title':'T','content':'<b>notes</b>'}]}
        got=core.searxng('good',5,'https://search.example.org',get=getter)
        self.assertEqual(len(got),4)  # API might return same item on multiple pages; final dedup later
        self.assertEqual(got[0]['snippet'],'notes')

    def test_openlibrary_adapter(self):
        def getter(url):
            self.assertIn('search.json',url)
            self.assertIn('fields=',url)
            return {'docs':[{'key':'/works/OL123W','title':'Public Book',
                             'author_name':['Ada Author'],'first_publish_year':2001},
                            {'key':'/settings/private','title':'Bad'}]}
        result=core.openlibrary('research',25,get=getter)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['url'],'https://openlibrary.org/works/OL123W')
        self.assertIn('Ada Author',result[0]['snippet'])

    def test_archive_catalogue_adapter(self):
        def getter(url):
            self.assertIn('advancedsearch.php',url)
            self.assertIn('fl%5B%5D',url)
            return {'response':{'docs':[{'identifier':'open-research-2026',
                          'title':'Free resource','mediatype':'texts'},
                          {'identifier':'../evil','title':'Reject invalid ID'}]}}
        result=core.archive('public research',40,get=getter)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['source'],'Internet Archive')
        self.assertEqual(result[0]['url'],'https://archive.org/details/open-research-2026')

    def test_europepmc_adapter_and_doi_overlap(self):
        data={'resultList':{'result':[{'id':'ABC123','source':'MED',
             'title':'A research work','doi':'10.5555/test', 'journalTitle':'Journal'},
             {'id':'123456','source':'MED','title':'Second work'}]}}
        result=core.europepmc('research',100,get=lambda url:data)
        self.assertEqual(result[0]['url'],'https://doi.org/10.5555/test')
        self.assertEqual(result[1]['url'],'https://europepmc.org/article/MED/123456')
        merged=core.combine(result+[core.make_record('https://doi.org/10.5555/test','Research','', 'Crossref')],20)
        self.assertEqual(len(merged),2)
        self.assertEqual(merged[0]['sources'],['Europe PMC','Crossref'])

    def test_full_scale_limit_is_1000(self):
        with tempfile.TemporaryDirectory() as d:
            rows=[core.make_record(f'https://research.example.org/item/{i}',f'Title {i}', '', 'Crossref')
                  for i in range(1250)]
            self.assertEqual(len(core.combine(rows,1000)),1000)
            v=core.Vault(d)
            rid=v.store('open science','live',1000,core.combine(rows,1000),{'crossref':{'status':'ok','found':1250}})
            self.assertEqual(v.run(rid)['total'],1000)
            self.assertEqual(len(v.results(rid)),1000)

    def test_new_source_partial_failure_and_success(self):
        with tempfile.TemporaryDirectory() as d:
            v=core.Vault(d)
            with patch.object(app,'VAULT',v),\
                 patch.object(core,'archive',return_value=[core.make_record('https://archive.org/details/gift','Archived item','','Internet Archive')]),\
                 patch.object(core,'openlibrary',side_effect=TimeoutError('provider timed out')):
                rid=app.run_search('open science',['archive','openlibrary'],1000,quality='broad')
                self.assertEqual(v.run(rid)['total'],1)
                self.assertIn('provider timed out',v.run(rid)['reports'])

    def test_vault_and_exports(self):
        with tempfile.TemporaryDirectory() as d:
            v=core.Vault(d)
            rows=core.demo_results(50)
            self.assertEqual(len(rows),7)
            rid=v.store('solar','demo',50,rows,{'Demo':{'status':'sample only'}})
            self.assertEqual(v.run(rid)['total'],7)
            self.assertEqual(len(v.results(rid)),7)
            for fmt in ('csv','json','html'):
                data, ct, ext=core.export_content(v,rid,fmt)
                self.assertGreater(len(data),150)
                self.assertEqual(ext,fmt)
            # malicious-looking content must be treated as text in static report
            rid2=v.store('<img src=x onerror=evil()>','live',50,[{
                'url':'https://example.org/test','title':'<script>alert(1)</script>',
                'snippet':'<img src=x onerror=evil()>', 'sources':['Crossref']}],{})
            output,_,_=core.export_content(v,rid2,'html')
            self.assertNotIn(b'<script>alert(1)</script>',output)
            self.assertIn(b'&lt;script&gt;',output)

    def test_demo_search_integration(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(app,'VAULT',core.Vault(d)):
                rid=app.run_search('demo public topic',[],50,demo=True)
                self.assertEqual(app.VAULT.run(rid)['mode'],'demo')
                self.assertEqual(app.VAULT.run(rid)['total'],7)

    def test_neon_auto_suppresses_non_tty(self):
        stream=io.StringIO()
        n=Neon('auto',stream=stream,environment={'TERM':'xterm-256color'})
        self.assertFalse(n.enabled)
        self.assertNotIn('\x1b[',n.spectrum('BLACKSWARM'))

    def test_neon_honors_no_color(self):
        stream=io.StringIO()
        stream.isatty=lambda: True
        n=Neon('auto',stream=stream,environment={'TERM':'xterm-256color','NO_COLOR':'1'})
        self.assertFalse(n.enabled)
        self.assertEqual(n.fg('OK'),'OK')

    def test_neon_forced_color_in_non_tty(self):
        stream=io.StringIO()
        n=Neon('always',stream=stream,environment={'TERM':'dumb','NO_COLOR':'1'})
        self.assertIn('\x1b[1;38;2;',n.spectrum('BLACKSWARM'))
        self.assertTrue(n.enabled)
        self.assertEqual(Neon('never', stream=stream).fg('OK'),'OK')

    def test_color_test_has_no_vault_side_effect(self):
        with patch.object(app.core, 'Vault', side_effect=AssertionError('must not open vault')):
            sink=io.StringIO()
            with redirect_stdout(sink):
                self.assertEqual(app.main(['--color-test','--color','always']),0)
            self.assertIn('NO_COLOR=',sink.getvalue())
            self.assertIn('\x1b[38;2;',sink.getvalue())

    def test_neon_summary_reports_failures(self):
        stream=io.StringIO()
        n=Neon('never',stream=stream)
        row={'mode':'live','total':100,'reports':{'wikipedia':{'status':'ok','found':100},'gdelt':{'status':'error','found':0,'detail':'SSL timeout'}}}
        with redirect_stdout(stream):
            n.summary(row,'/tmp/example.sqlite3',3)
        out=stream.getvalue()
        self.assertIn('100',out)
        self.assertIn('SSL timeout',out)
        self.assertIn('/tmp/example.sqlite3',out)
        # Vault.run() returns reports as a JSON string in the persisted schema.
        stream2=io.StringIO()
        with redirect_stdout(stream2):
            n.summary({'mode':'live','total':100,'reports':json.dumps(row['reports'])},'/tmp/example.sqlite3',3)
        self.assertIn('SSL timeout',stream2.getvalue())

    def test_live_partial_failure(self):
        with tempfile.TemporaryDirectory() as d:
            v=core.Vault(d)
            with patch.object(app,'VAULT',v),\
                 patch.object(core,'wikipedia',return_value=[core.make_record('https://en.wikipedia.org/wiki/A','A','','Wikipedia')]),\
                 patch.object(core,'crossref',side_effect=RuntimeError('HTTP 429')):
                rid=app.run_search('test topic',['wikipedia','crossref'],50,quality='broad')
                self.assertEqual(v.run(rid)['total'],1)
                self.assertIn('error',v.run(rid)['reports'])
                self.assertIn('HTTP 429',v.run(rid)['reports'])


    def test_terminal_default_never_launches_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(app.core,'Vault', return_value=core.Vault(folder)), \
                 patch('blackswarm.app.webbrowser.open', side_effect=AssertionError('browser auto-open forbidden')), \
                 patch('builtins.input', side_effect=['0']), \
                 redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.main(['--color','never']),0)
                self.assertIn('TERMINAL-FIRST',output.getvalue())
                self.assertIn('SWARM COMMAND DECK',output.getvalue())

    def test_demo_is_terminal_only_and_saves_a_session(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            with patch.object(app.core,'Vault', return_value=vault), \
                 patch('blackswarm.app.webbrowser.open', side_effect=AssertionError('browser auto-open forbidden')), \
                 redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.main(['--demo','--color','never']),0)
                self.assertIn('DEMO ONLY',output.getvalue())
                self.assertEqual(vault.count_runs(),1)
                self.assertEqual(vault.runs()[0]['total'],7)

    def test_dashboard_requires_explicit_mode_and_defaults_to_no_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            with patch.object(app.core,'Vault', return_value=vault), \
                 patch.object(app,'run_dashboard',return_value=0) as server:
                self.assertEqual(app.main(['--dashboard']),0)
                self.assertEqual(server.call_args.kwargs['open_browser'],False)
                self.assertEqual(app.main(['--open-dashboard']),0)
                self.assertEqual(server.call_args.kwargs['open_browser'],True)

    def test_menu_history_and_full_url_view(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            saved=vault.store('public documents','demo',50,core.demo_results(50),{'Demo':{'status':'sample only'}})
            with patch.object(app.core,'Vault',return_value=vault), \
                 patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser auto-open forbidden')), \
                 patch('builtins.input',side_effect=['3','4',str(saved),'0']), \
                 redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.main(['--color','never']),0)
                txt=output.getvalue()
                self.assertIn('SAVED SESSIONS',txt)
                self.assertIn('https://en.wikipedia.org/wiki/Solar_energy',txt)

    def test_menu_export_file_is_opt_in_and_non_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder+'/vault')
            saved=vault.store('public documents','demo',50,core.demo_results(50),{})
            home=Path(folder)/'home'
            home.mkdir()
            with patch.object(app.core,'Vault',return_value=vault), \
                 patch('blackswarm.app.Path.home',return_value=home), \
                 patch('builtins.input',side_effect=['5',str(saved),'csv','5',str(saved),'csv','0']), \
                 redirect_stdout(io.StringIO()) as output:
                self.assertEqual(app.main(['--color','never']),0)
                report=home/'Documents'/'BLACKSWARM-EXPORTS'/f'BLACKSWARM-run-{saved}.csv'
                self.assertTrue(report.exists())
                self.assertIn('Solar energy',report.read_text())
                self.assertIn('File already exists. Nothing overwritten.',output.getvalue())


class SmartSwarmTests(unittest.TestCase):
    def test_title_metadata_outweighs_unrelated_results(self):
        rows=[
            core.make_record('https://example.org/med/one','Clinical cardiology research','medical journal','Europe PMC'),
            core.make_record('https://example.org/sec/intro','Ethical hacking cybersecurity fundamentals','penetration testing and security','Crossref'),
            core.make_record('https://example.org/med/two','Materials and polymers study','science research','Europe PMC'),
            core.make_record('https://example.org/sec/red-team','Penetration testing for ethical hackers','defensive security research','Internet Archive'),
        ]
        chosen,allrows,stats=core.smart_rank(rows,'ethical hacking cybersecurity',250)
        self.assertEqual(len(allrows),4)
        self.assertEqual(len(chosen),2)
        self.assertIn('fundamentals',chosen[0]['title'])
        self.assertEqual(stats['filtered_low'],2)
        self.assertEqual(stats['candidates'],4)
        self.assertEqual(sum(bool(r['selected']) for r in allrows),2)

    def test_broad_mode_keeps_low_ranked_candidates(self):
        rows=[core.make_record('https://example.org/med','Cancer trial','','Europe PMC'),
              core.make_record('https://example.org/sec','Hacker cybersecurity guide','','Wikipedia')]
        focus,_,_=core.smart_rank(rows,'hacker cybersecurity',250,'focused')
        wide,allrows,stats=core.smart_rank(rows,'hacker cybersecurity',250,'broad')
        self.assertEqual(len(focus),1)
        self.assertEqual(len(wide),2)
        self.assertEqual(wide[-1]['relevance'],'low')
        self.assertEqual(stats['selected'],2)

    def test_rank_uses_full_set_before_capping_and_merges_sources(self):
        rows=[core.make_record('https://example.org/weak','Off-topic archive art','','Internet Archive'),
              core.make_record('https://example.org/strong?utm_source=x','Cybersecurity ethical hacking','security','Crossref'),
              core.make_record('https://example.org/strong','Cybersecurity ethical hacking','','Wikipedia')]
        chosen,allrows,stats=core.smart_rank(rows,'ethical hacking cybersecurity',1)
        self.assertEqual(len(chosen),1)
        self.assertEqual(chosen[0]['url'],'https://example.org/strong')
        self.assertEqual(len(chosen[0]['sources']),2)
        self.assertEqual(len(allrows),2)
        self.assertEqual(stats['candidates'],2)

    def test_audit_vault_retains_excluded_and_raw_exports(self):
        rows=[core.make_record('https://example.org/book','Ethical hacking cybersecurity handbook','','Open Library'),
              core.make_record('https://example.org/other','Veterinary medicine','','Europe PMC')]
        chosen,allrows,stats=core.smart_rank(rows,'ethical hacking cybersecurity',100)
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            sid=vault.store('ethical hacking cybersecurity','live',100,chosen,{'openlibrary':{'status':'ok','found':2}},allrows,stats)
            self.assertEqual(vault.run(sid)['total'],1)
            self.assertEqual(len(vault.results(sid)),1)
            self.assertEqual(len(vault.candidates(sid)),2)
            self.assertEqual(vault.candidates(sid,only_excluded=True)[0]['url'],'https://example.org/other')
            data,_,ext=core.export_content(vault,sid,'rawcsv')
            self.assertEqual(ext,'raw.csv')
            self.assertIn(b'Veterinary medicine',data)
            data,_,ext=core.export_content(vault,sid,'rawjson')
            self.assertEqual(ext,'raw.json')
            self.assertEqual(len(json.loads(data)['candidates']),2)
            compact,_,_=core.export_content(vault,sid,'csv')
            self.assertNotIn(b'Veterinary medicine',compact)
            self.assertIn(b'relevance',compact)

    def test_search_prints_title_relevance_and_url_no_browser(self):
        rows=[core.make_record('https://example.org/research','Ethical hacking cybersecurity field guide','cybersecurity', 'Crossref'),
              core.make_record('https://example.org/irrelevant','Unrelated oncology','medicine','Europe PMC')]
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            with patch.object(app,'VAULT',vault), \
                 patch.object(core,'crossref',return_value=rows), \
                 patch.object(app,'NEON',Neon('never')), \
                 patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser not allowed')), \
                 redirect_stdout(io.StringIO()) as output:
                sid=app.run_search('ethical hacking cybersecurity',['crossref'],100,quality='focused')
            t=output.getvalue()
            self.assertIn('field guide',t)
            self.assertIn('https://example.org/research',t)
            self.assertIn('HIGH',t)
            self.assertEqual(vault.run(sid)['total'],1)
            self.assertEqual(len(vault.candidates(sid)),2)

    def test_sanitized_report_and_storage_of_untrusted_titles(self):
        rows=[core.make_record('https://example.org/cyber','<script>Ethical hacking cybersecurity</script>','','Crossref')]
        selected,allrows,stats=core.smart_rank(rows,'ethical hacking cybersecurity',50)
        with tempfile.TemporaryDirectory() as folder:
            v=core.Vault(folder)
            rid=v.store('ethical hacking cybersecurity','live',50,selected,{},allrows,stats)
            output,_,_=core.export_content(v,rid,'html')
            self.assertNotIn(b'<script>',output)
            self.assertIn(b'relevance:',output)

if __name__=='__main__':
    unittest.main()
