"""Rainbow output and one-provider failure behavior, offline only."""
import io
import re
import json
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout
from unittest.mock import patch
from blackswarm import core, app
from blackswarm.neon import Neon, PALETTE

class RainbowSignalsTests(unittest.TestCase):
    def test_truecolor_word_cycle_with_all_six_colors(self):
        neon=Neon('always')
        text='search results streaming over public research sources now'
        painted=neon.rainbow_words(text)
        codes={f'38;2;{r};{g};{b}m' for r,g,b in PALETTE}
        self.assertTrue(all(c in painted for c in codes))
        self.assertEqual(re.sub(r'\x1b\[[0-9;]*m','',painted),text)
        self.assertIn('▰',neon.rainbow_band())

    def test_color_never_plain(self):
        neon=Neon('never')
        self.assertEqual(neon.rainbow_words('Public Links'),'Public Links')
        self.assertEqual(neon.rainbow_band(),'')

    def test_terminal_events_rainbow_and_untrusted_control_clean(self):
        out=io.StringIO()
        with patch.object(app,'NEON',Neon('always')):
            with redirect_stdout(out):
                app.terminal_event('link','[#1] Lots of source words to paint every color in this rainbow 🌈')
                app.terminal_event('source','Checking LOC public index')
                app.terminal_event('error','LOC unavailable from a request timeout')
                app.terminal_event('link','malicious\x1b[2J title')
        got=out.getvalue()
        self.assertIn('\x1b[38;2;',got)
        self.assertIn('▰',got)
        self.assertIn('LOC unavailable',got)
        self.assertNotIn('\x1b[2J',got)
        self.assertTrue(all(f'38;2;{r};{g};{b}m' in got for r,g,b in PALETTE))

    def test_terminal_events_plain_no_ansi(self):
        buf=io.StringIO()
        with patch.object(app,'NEON',Neon('never')), redirect_stdout(buf):
            app.terminal_event('link','a useful result')
        self.assertEqual(buf.getvalue().strip(),'↳ a useful result')
        self.assertNotIn('\x1b',buf.getvalue())

    def test_loc_uses_documented_slim_json_not_arbitrary_hosts(self):
        seen=[]
        def get(url):
            seen.append(url)
            return {'results':[{'id':'http://loc.gov/item/123/','title':'Archive example'},
                               {'id':'https://untrusted.example.test/data','title':'Not LoC'}]}
        got=core.loc('historical public libraries',100,get=get)
        self.assertEqual(len(seen),1)
        args=urllib.parse.parse_qs(urllib.parse.urlsplit(seen[0]).query)
        self.assertEqual(args['c'],['30'])
        self.assertEqual(args['at'],['results'])
        self.assertEqual(got[0]['url'],'https://www.loc.gov/item/123/')
        self.assertEqual(len(got),1)

    def test_timeout_skips_provider_but_saves_other_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=core.Vault(folder)
            item=core.make_record('https://arxiv.org/abs/2405.12345','Cybersecurity study','', 'arXiv')
            stdout=io.StringIO()
            with patch.object(app,'VAULT',vault), patch.object(app,'NEON',Neon('never')), \
                 patch.object(core,'loc',side_effect=TimeoutError('The read operation timed out')), \
                 patch.object(core,'arxiv',return_value=[item]),patch.object(app.time,'sleep'), redirect_stdout(stdout):
                session=app.run_search('cybersecurity research',['loc','arxiv'],50,quality='broad')
            report=json.loads(vault.run(session)['reports'])
            self.assertEqual(report['loc']['status'],'error')
            self.assertIn('timed out',report['loc']['detail'])
            self.assertEqual(report['arxiv']['status'],'ok')
            self.assertEqual(len(vault.results(session)),1)
            self.assertIn('LOC TIMED OUT',stdout.getvalue())
            self.assertIn('1 UNAVAILABLE',stdout.getvalue())
            self.assertIn('https://arxiv.org/abs/2405.12345',stdout.getvalue())

    def test_rainbow_color_test_doesnt_open_store(self):
        buf=io.StringIO()
        with patch('blackswarm.app.webbrowser.open',side_effect=AssertionError('browser')) ,\
             patch.object(app.core,'Vault',side_effect=AssertionError('vault')),redirect_stdout(buf):
            self.assertEqual(app.main(['--color-test','--color','always']),0)
        self.assertIn('BLACKSWARM',buf.getvalue())
        self.assertIn('\x1b[',buf.getvalue())

if __name__=='__main__':unittest.main()
