"""BLACKSWARM SMART INTENT // offline tests, never calls search providers."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from blackswarm import app, core, intent, quality
from blackswarm.neon import Neon

Q = 'ethical hacking cybersecurity'


def item(title, snippet, path, source='Crossref'):
    row = {'url':'https://example.org'+path, 'title':title, 'snippet':snippet, 'sources':[source], 'source':source}
    score,tier = core.score_record(Q,row)
    return {**row, 'score':score, 'relevance':tier}


class SmartIntentTests(unittest.TestCase):
    def setUp(self):
        self.pop = item('Cybersecurity in popular culture', 'The hack trope', '/wiki/Cybersecurity_in_popular_culture', 'Wikipedia')
        self.chapter = item('CHAPTER X Counterattack/Hackback', 'Includes ethical and hacking', '/doi')
        self.complete = item('Ethical hacking cybersecurity reference', 'Ethical hackers research', '/reference')
        self.session={'id':1, 'query':Q, 'requested':2, 'mode':'live', 'stats':json.dumps({'quality':'focused'})}

    def test_partial_title_missing_term(self):
        a = intent.score_intent(Q,self.pop)
        self.assertEqual(self.pop['score'],39)
        self.assertEqual(a['score'],27)
        self.assertEqual(a['relevance'],'possible')
        self.assertEqual(a['locations']['ethical'],'MISSING')
        self.assertEqual(a['missing_penalty'],12)

    def test_snippet_only_is_demoted(self):
        a=intent.score_intent(Q,self.chapter)
        self.assertEqual(self.chapter['score'],26)
        self.assertEqual(a['score'],6)
        self.assertEqual(a['relevance'],'low')
        self.assertEqual(a['no_title_penalty'],8)

    def test_all_terms_get_boost(self):
        a=intent.score_intent(Q,self.complete)
        self.assertEqual(a['found'],3)
        self.assertEqual(a['missing'],0)
        self.assertEqual(a['all_bonus'],12)
        self.assertEqual(a['relevance'],'high')

    def test_single_term_parity(self):
        for q in ('research','cybersecurity','hacking'):
            a=intent.score_intent(q,self.pop)
            self.assertEqual((a['score'],a['relevance']),core.score_record(q,self.pop))

    def test_no_crash_with_empty_terms(self):
        a=intent.score_intent('the and for',self.pop)
        self.assertEqual(a['score'],core.score_record('the and for',self.pop)[0])

    def test_legacy_modes_unchanged(self):
        rows=[self.pop,self.chapter,self.complete]
        focus,_,stats=core.smart_rank(rows,Q,2,'focused')
        self.assertEqual(stats['quality'],'focused')
        self.assertTrue(all(row['score']==core.score_record(Q,row)[0] for row in focus))
        broad,_,stats=core.smart_rank(rows,Q,3,'broad')
        self.assertEqual(len(broad),3)
        self.assertEqual(stats['quality'],'broad')

    def test_new_intent_only_opt_in(self):
        rows=[self.pop,self.chapter,self.complete]
        out,cands,stats=core.smart_rank(rows,Q,2,'intent')
        self.assertEqual(stats['quality'],'intent')
        self.assertEqual(out[0]['title'],self.complete['title'])
        self.assertEqual(next(r for r in cands if r['title']==self.chapter['title'])['relevance'],'low')
        self.assertTrue(all('selected' in r for r in cands))

    def test_record_not_mutated(self):
        source=dict(self.pop)
        intent.score_intent(Q,source)
        self.assertEqual(source,self.pop)

    def test_preview_is_read_only_and_stable_ids(self):
        with tempfile.TemporaryDirectory() as d:
            v=core.Vault(d)
            rows=[self.complete,self.pop,self.chapter]
            selected=rows[:2]
            sid=v.store(Q,'live',2,selected,{},candidates=[{**r,'selected':i<2} for i,r in enumerate(rows)],stats={'quality':'focused'})
            before=Path(v.dbpath).read_bytes()
            data=intent.preview(v.run(sid),v.results(sid),v.candidates(sid))
            self.assertEqual(before,Path(v.dbpath).read_bytes())
            self.assertEqual(len(data['items']),3)
            self.assertEqual([i['candidate_id'] for i in data['items']],[1,2,3])
            self.assertFalse(next(x for x in data['items'] if x['title']==self.chapter['title'])['preview_selected'])

    def test_old_sessions_without_candidates(self):
        data=intent.preview(self.session,[self.pop],[])
        self.assertFalse(data['full_candidates'])
        self.assertEqual(len(data['items']),1)
        self.assertEqual(data['old_selected'],1)

    def test_preview_display_and_detail(self):
        session={**self.session,'requested':1}
        records=[{**self.pop,'selected':True},{**self.chapter,'selected':False}]
        opts=iter(['4','2','1','b','3','b','0'])
        stream=io.StringIO()
        with redirect_stdout(stream):
            intent.intent_desk(Neon('never'),session,[self.pop],records,input_fn=lambda prompt:next(opts))
        data=stream.getvalue()
        self.assertIn('SMART INTENT',data)
        self.assertIn('CANDIDATE #2',data)
        self.assertIn('PREVIEW ONLY',data)
        self.assertIn('Original session preserved',data)

    def test_quality_lab_uses_intent_for_new_mode(self):
        result=intent.score_intent(Q,self.pop)
        row={**self.pop,'score':result['score'],'relevance':result['relevance'],'selected':True}
        session={**self.session,'stats':json.dumps({'quality':'intent'})}
        report=quality.build_report(session,[row],[row])
        stream=io.StringIO()
        with redirect_stdout(stream):quality._explain_detail(Neon('never'),report,report['items'][0])
        s=stream.getvalue()
        self.assertIn('[INTENT]',s)
        self.assertIn('INTENT ADJUSTMENTS',s)
        self.assertNotIn('saved values differ',s)

    def test_app_cli_and_menu_visible(self):
        s=Path(app.__file__).read_text()
        self.assertIn("elif choice == '17':",s)
        self.assertIn('--intent-lens',s)
        self.assertIn("choices=['focused','broad','intent','precision']",s)
        self.assertIn('SMART INTENT LENS',s)

    def test_run_search_opt_in_with_mock_source(self):
        with tempfile.TemporaryDirectory() as d:
            v=core.Vault(d)
            with patch.object(app,'VAULT',v),patch.object(core,'wikipedia',return_value=[self.pop,self.chapter,self.complete]),patch.object(app.time,'sleep'):
                sid=app.run_search(Q,['wikipedia'],50,quality='intent')
                session=v.run(sid)
                self.assertEqual(json.loads(session['stats'])['quality'],'intent')
                self.assertTrue(v.candidates(sid))
                self.assertTrue(all(r['relevance']!='low' for r in v.results(sid)))

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):core.smart_rank([],Q,50,'surprise')

    def test_no_network_requests_in_preview(self):
        with patch.object(core,'http_get_json',side_effect=AssertionError('network called')):
            intent.preview(self.session,[self.pop],[self.pop,self.chapter])


if __name__=='__main__':
    unittest.main()
