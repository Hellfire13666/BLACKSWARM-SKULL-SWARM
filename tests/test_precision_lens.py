"""Opt-in title-first ranking and saved-session read-only preview tests."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from blackswarm import core, app, precision
from blackswarm.neon import Neon

Q = 'ethical hacking cybersecurity'


def rec(url, title, snippet=''):
    return core.make_record(url,title,snippet,'Crossref')


class PrecisionLensTests(unittest.TestCase):
    def setUp(self):
        self.strong=rec('https://doi.org/10.9999/strong','Ethical Hacking Cybersecurity Guide','Research work')
        self.two=rec('https://doi.org/10.9999/two','Ethical Hacking Field Manual','Technology book')
        self.weak=rec('https://doi.org/10.9999/weak','Cybersecurity in popular culture', 'History of hacking')
        self.noisy=rec('https://doi.org/10.9999/noisy','Hired People and Employment','Ethical hacks in workplace')

    def test_title_anchors_prefer_full_query(self):
        a=precision.score_precision(Q,self.strong)
        b=precision.score_precision(Q,self.two)
        c=precision.score_precision(Q,self.weak)
        d=precision.score_precision(Q,self.noisy)
        self.assertTrue(a['anchored'])
        self.assertEqual(a['title_hits'],3)
        self.assertTrue(b['anchored'])
        self.assertEqual(b['title_hits'],2)
        self.assertFalse(c['anchored'])
        self.assertFalse(d['anchored'])
        self.assertEqual(c['relevance'],'low')
        self.assertEqual(d['relevance'],'low')
        self.assertLess(c['score'],20)
        self.assertEqual(a['total_terms'],3)

    def test_precision_is_opt_in_and_preserves_legacy_scores(self):
        rows=[self.strong,self.weak,self.noisy]
        legacy=core.smart_rank(rows,Q,50,'focused')
        chosen,candidates,stats=core.smart_rank(rows,Q,50,'precision')
        self.assertEqual(stats['quality'],'precision')
        self.assertLess(len(chosen),len(legacy[0]))
        self.assertEqual(len(candidates),3)
        self.assertEqual(len(legacy[1]),3)
        self.assertEqual(core.score_record(Q,legacy[1][0])[0],core.score_record(Q,legacy[1][0])[0])
        self.assertEqual(len(core.smart_rank(rows,Q,50,'broad')[0]),3)

    def test_preview_does_not_touch_saved_sqlite(self):
        with tempfile.TemporaryDirectory() as root:
            vault=core.Vault(root)
            selected,candidates,stats=core.smart_rank([self.strong,self.two,self.weak,self.noisy],Q,50,'broad')
            sid=vault.store(Q,'live',50,selected,{'crossref':{'status':'ok','found':4}},candidates=candidates,stats=stats)
            before=Path(vault.dbpath).read_bytes()
            d=precision.preview(vault.run(sid),vault.results(sid),vault.candidates(sid))
            self.assertEqual(d['old_selected'],4)
            self.assertTrue(d['would_exclude']>=2)
            self.assertEqual(before,Path(vault.dbpath).read_bytes())
            answer=iter(['4','1','0'])
            out=io.StringIO()
            with redirect_stdout(out):
                precision.precision_desk(Neon('never'),vault.run(sid),vault.results(sid),vault.candidates(sid),input_fn=lambda prompt:next(answer))
            self.assertIn('PRECISION LENS',out.getvalue())
            self.assertIn('TITLE ANCHOR',out.getvalue())
            self.assertEqual(before,Path(vault.dbpath).read_bytes())

    def test_search_saves_new_precision_session_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault=core.Vault(tmp)
            with patch.object(app,'VAULT',vault),patch.object(core,'crossref',return_value=[self.strong,self.weak,self.noisy]),patch.object(app.time,'sleep'):
                with redirect_stdout(io.StringIO()):
                    rid=app.run_search(Q,['crossref'],50,quality='precision')
            self.assertEqual(json.loads(vault.run(rid)['stats'])['quality'],'precision')
            self.assertEqual(len(vault.candidates(rid)),3)
            self.assertEqual(len(vault.results(rid)),1)
            self.assertTrue(all(x['relevance']!='low' for x in vault.results(rid)))

    def test_loc_has_shorter_http_socket_timeout_and_injected_get(self):
        seen=[]
        with patch.object(core,'http_get_json',side_effect=lambda url,timeout=14:seen.append((url,timeout)) or {'results':[]}):
            self.assertEqual(core.loc('history',50),[])
        self.assertEqual(seen[0][1],8)
        self.assertIn('at=results',seen[0][0])
        seen=[]
        core.loc('history',50,get=lambda url:seen.append(url) or {'results':[]})
        self.assertEqual(len(seen),1)

    def test_menu_and_cli_precision_available(self):
        p=Path(app.__file__).read_text()
        self.assertIn('[18]',p)
        self.assertIn('PRECISION LENS',p)
        self.assertIn("'precision'",p)
        out=io.StringIO()
        with patch.object(app,'VAULT',type('FakeVault',(),{'dbpath':'PRIVATE VAULT'})()),patch('builtins.input',side_effect=['0']),redirect_stdout(out):
            app.terminal_menu(Neon('never'))
        self.assertIn('[18]',out.getvalue())
        self.assertIn('TERMINAL-FIRST',out.getvalue())

if __name__=='__main__':unittest.main()
