"""All offline tests. No external web calls or user vault access."""
import io
import os
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from blackswarm import app, core, quality
from blackswarm.neon import Neon


def item(title, snippet='', path='/sample', selected=False, level=None, query='ethical hacking cybersecurity'):
    row={'title':title,'snippet':snippet,'url':'https://example.org'+path, 'sources':['Crossref']}
    score, tier=core.score_record(query,row)
    row.update(score=score, relevance=level or tier, selected=selected)
    return row


class QualityLabTests(unittest.TestCase):
    QUERY='ethical hacking cybersecurity'

    def setUp(self):
        self.row1=item('Ethical hacking cybersecurity', selected=True)
        self.row2=item('Cybersecurity reference',selected=True,path='/reference')
        self.row3=item('Historical apples',selected=False,path='/apples')
        self.session={'id':1,'query':self.QUERY,'mode':'live'}
        self.n=Neon('never')

    def test_decomposition_matches_original_for_title(self):
        a=quality.explain_score(self.QUERY,self.row1)
        self.assertEqual((a['score'],a['relevance']),core.score_record(self.QUERY,self.row1))
        self.assertGreater(a['phrase_bonus'],0)

    def test_score_parts_for_snippet_and_path(self):
        row=item('Reference',snippet='cybersecurity background',path='/ethical-hacking')
        a=quality.explain_score(self.QUERY,row)
        self.assertEqual(a['score'],core.score_record(self.QUERY,row)[0])
        hits={t:(loc,pts) for t,loc,pts in a['terms']}
        self.assertEqual(hits['cybersecurity'],('SNIPPET',8))
        self.assertEqual(hits['hack'],('URL PATH',5))

    def test_ranking_rule_parity_matrix(self):
        words=['cybersecurity','hacking','ethical','security','pentesting','malware','reference','reading','open','data','network']
        rng=random.Random(2035)
        for q in ['ethical hacking cybersecurity','cybersecurity','open data','kali security', 'hack pentest']:
            for _ in range(100):
                title=' '.join(rng.sample(words, rng.randint(0,len(words))))
                snippet=' '.join(rng.sample(words,rng.randint(0,len(words))))
                url='https://example.org/'+'-'.join(rng.sample(words, rng.randint(1,5)))
                row={'title':title,'snippet':snippet,'url':url}
                self.assertEqual((quality.explain_score(q,row)['score'],quality.explain_score(q,row)['relevance']),core.score_record(q,row))

    def test_empty_query_does_not_crash(self):
        a=quality.explain_score('',self.row1)
        self.assertEqual(a['term_count'],0)

    def test_snapshot_preserves_candidate_selection(self):
        s=quality.build_report(self.session,[self.row1,self.row2],[self.row1,self.row2,self.row3])
        self.assertEqual(len(s['items']),3)
        self.assertEqual(s['selected'],2)
        self.assertFalse(s['items'][2]['selected'])
        self.assertTrue(s['full_candidates'])

    def test_fallback_selected_only_for_legacy_sessions(self):
        s=quality.build_report(self.session,[self.row1,self.row2],[])
        self.assertEqual(s['selected'],2)
        self.assertFalse(s['full_candidates'])

    def test_detail_shows_scores_no_rescan(self):
        r=quality.build_report(self.session,[self.row1],[self.row1,self.row3])
        out=io.StringIO()
        with redirect_stdout(out):quality._explain_detail(self.n,r,r['items'][0])
        self.assertIn('QUERY TERM MATCHES',out.getvalue())
        self.assertIn('STORED SCORE',out.getvalue())
        self.assertIn('No browser, network request, or database changes.',out.getvalue())

    def test_score_difference_flagged_without_change(self):
        row={**self.row1,'score':0,'relevance':'low'}
        r=quality.build_report(self.session,[],[row])
        before=dict(row)
        out=io.StringIO()
        with redirect_stdout(out):quality._explain_detail(self.n,r,r['items'][0])
        self.assertIn('saved values differ',out.getvalue())
        self.assertEqual(row,before)

    def test_user_menu_navigation_and_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            v=core.Vault(d)
            chosen=[self.row1,self.row2]
            candidates=[self.row1,self.row2,self.row3]
            sid=v.store(self.QUERY,'live',100,chosen,{},candidates=candidates,stats={'quality':'focused'})
            original=Path(v.dbpath).read_bytes()
            prompts=iter(['1','1','b','4','hacking','b','5','3','0'])
            out=io.StringIO()
            with redirect_stdout(out):quality.quality_desk(self.n,v.run(sid),v.results(sid),v.candidates(sid),input_fn=lambda p:next(prompts))
            self.assertEqual(Path(v.dbpath).read_bytes(),original)
            self.assertIn('QUALITY CONTROL',out.getvalue())
            self.assertIn('QUALITY EXPLANATION',out.getvalue())

    def test_zero_matches_and_cancel(self):
        out=io.StringIO()
        iter_inputs=iter(['3','0'])
        with redirect_stdout(out):quality.quality_desk(self.n,self.session,[self.row1],[],input_fn=lambda p:next(iter_inputs))
        self.assertIn('No matching saved candidates',out.getvalue())

    def test_demo_label_explicit(self):
        session={**self.session,'mode':'demo'}
        out=io.StringIO()
        with redirect_stdout(out):quality.quality_desk(self.n,session,[self.row1],[],input_fn=lambda p:'0')
        self.assertIn('DEMO: illustrative',out.getvalue())

    def test_no_candidate_unknown_id_safe(self):
        out=io.StringIO()
        prompts=iter(['5','999','0'])
        with redirect_stdout(out):quality.quality_desk(self.n,self.session,[self.row1],[],input_fn=lambda p:next(prompts))
        self.assertIn('Candidate number not found',out.getvalue())

    def test_ansi_unsafe_provider_text_is_sanitized(self):
        r={**self.row1,'title':'HELLO\x1b[31mRED\x1b[0m','sources':['\x1b[8m']}
        report=quality.build_report(self.session,[r],[r])
        out=io.StringIO()
        with redirect_stdout(out):quality._explain_detail(self.n,report,report['items'][0])
        self.assertNotIn('\x1b',out.getvalue())

    def test_existing_app_menu_integrated(self):
        s=Path(app.__file__).read_text()
        self.assertIn("elif choice == '16':",s)
        self.assertIn("--quality-lab",s)
        self.assertIn('SOURCE PULSE',s)
        self.assertIn('VAULT GUARD',s)

if __name__=='__main__':unittest.main()
