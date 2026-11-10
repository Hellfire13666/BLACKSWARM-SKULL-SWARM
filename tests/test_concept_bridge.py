"""Offline, synthetic tests only; no live provider calls or personal vault."""
import contextlib
import copy
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from blackswarm import concept, core
from blackswarm.neon import Neon

class ConceptBridgeTests(unittest.TestCase):
    def row(self,title,snippet='',url='https://example.org/research'):
        return {'title':title,'snippet':snippet,'url':url,'sources':['arxiv'],
                'score':19,'relevance':'low','selected':False}

    def test_cybersecurity_topic_is_supported(self):
        self.assertTrue(concept.query_supported('cybersecurity'))
        self.assertTrue(concept.query_supported('cyber security research'))
        self.assertTrue(concept.query_supported('ethical hacking'))
        self.assertFalse(concept.query_supported('life hacks for hiring'))

    def test_malware_title_lift(self):
        x=concept.score_concept('cybersecurity', self.row('Siamese Denoising Autoencoder for Malware Classification','cybersecurity method'))
        self.assertTrue(x['eligible'])
        self.assertEqual(x['relevance'],'possible')
        self.assertGreater(x['score'],x['precision_score'])
        self.assertEqual(x['matches'][0][0],'MALWARE RESEARCH')
        self.assertEqual(x['matches'][0][1],'malware')

    def test_life_hacks_no_false_cyber_claim(self):
        x=concept.score_concept('cybersecurity',self.row('Ten life hacks for managers','cybersecurity related term'))
        self.assertEqual(x['lift'],0)
        self.assertFalse(x['eligible'])
        self.assertNotEqual(x['reason'],'RELATED TOPIC IN TITLE')

    def test_snippet_only_never_promoted(self):
        x=concept.score_concept('cybersecurity',self.row('Siamese Denoising Autoencoder','malware classification'))
        self.assertFalse(x['eligible'])
        self.assertEqual(x['lift'],0)

    def test_unrelated_query_no_concept_boost(self):
        x=concept.score_concept('hiring strategies',self.row('Malware Classification'))
        self.assertFalse(x['eligible'])
        self.assertEqual(x['reason'],'QUERY OUTSIDE CYBER TOPIC')

    def test_exact_title_anchor_already_meets_precision(self):
        x=concept.score_concept('cybersecurity',self.row('Cybersecurity Policy and Networks'))
        self.assertFalse(x['eligible'])
        self.assertEqual(x['score'],x['precision_score'])

    def test_focused_query_blocks_unrelated_malware(self):
        x=concept.score_concept('ethical hacking cybersecurity',self.row('Malware Classification'))
        self.assertFalse(x['eligible'])
        self.assertEqual(x['reason'],'ETHICAL-TESTING QUERY CONSTRAINT')

    def test_focused_query_accepts_testing_related(self):
        x=concept.score_concept('ethical hacking cybersecurity',self.row('White Hat Hacker Research'))
        self.assertTrue(x['eligible'])
        self.assertEqual(x['relevance'],'possible')

    def test_multi_family_cap_remains_possible(self):
        x=concept.score_concept('cybersecurity',self.row('Malware and Intrusion Detection, Vulnerabilities and Cryptography'))
        self.assertTrue(x['eligible'])
        self.assertLessEqual(x['score'],35)
        self.assertEqual(x['relevance'],'possible')
        self.assertGreaterEqual(len(x['matches']),2)

    def test_hyphenated_phrase_equivalent(self):
        self.assertTrue(concept.phrase_found('Zero-Day Exploit','zero day exploit'))
        self.assertFalse(concept.phrase_found('hacksaw','hack'))
        self.assertTrue(concept.phrase_found('INTRUSION-DETECTION system','intrusion detection'))

    def test_preview_preserves_record_and_ids(self):
        selected=[dict(self.row('Cybersecurity in education',url='https://example.org/a'),score=49,relevance='high')]
        candidates=[dict(selected[0],selected=True),self.row('Malware few-shot classification',url='https://example.org/b'),self.row('Hacks for hiring',url='https://example.org/c')]
        original=copy.deepcopy(candidates)
        d=concept.preview({'query':'cybersecurity','requested':3,'id':1},selected,candidates)
        self.assertEqual(candidates,original)
        self.assertEqual([r['candidate_id'] for r in d['items']],[1,2,3])
        self.assertEqual(d['related'],1)
        self.assertTrue(d['items'][1]['concept']['eligible'])
        self.assertFalse(d['items'][2]['concept']['eligible'])

    def test_without_candidate_pool(self):
        r=self.row('Malware Classification')
        d=concept.preview({'query':'cybersecurity','requested':50},[r],[])
        self.assertFalse(d['has_full_pool'])
        self.assertEqual(len(d['items']),1)

    def test_desk_readonly_display_and_exit(self):
        sample=self.row('Malware Classification')
        session={'id':3,'query':'cybersecurity','requested':50}
        inputs=iter(['1','1','b','4','1','0'])
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            concept.concept_desk(Neon('never'),session,[],[sample],input_fn=lambda prompt:next(inputs))
        self.assertIn('CONCEPT BRIDGE',out.getvalue())
        self.assertIn('TITLE: malware',out.getvalue())
        self.assertIn('Research vault unchanged',out.getvalue())

    def test_main_command_deck_wiring_and_cli(self):
        from blackswarm import app
        import inspect
        src=inspect.getsource(app.terminal_menu)
        self.assertIn("[19] ",src)
        self.assertIn("_terminal_concept_bridge(neon)",src)
        main=inspect.getsource(app.main)
        self.assertIn("--concept-bridge",main)
        self.assertIn('args.concept_bridge',main)

    def test_db_snapshot_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'sample.sqlite3'
            con=sqlite3.connect(db)
            con.execute('CREATE TABLE records (title TEXT)')
            con.execute('INSERT INTO records VALUES (?)',('Malware Classification',))
            con.commit();con.close()
            data=db.read_bytes()
            concept.preview({'query':'cybersecurity'},[],[self.row('Malware Classification')])
            self.assertEqual(db.read_bytes(),data)
            self.assertEqual(list(Path(td).iterdir()),[db])

if __name__=='__main__':unittest.main()
