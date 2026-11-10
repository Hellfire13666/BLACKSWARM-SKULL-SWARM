"""Passive public index expansion, offline fixture tests only, no external requests."""
import io
import json
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from blackswarm import app, core

ATOM='http://www.w3.org/2005/Atom'

def atom(title='Ethical research',summary='A research abstract',identifier='http://arxiv.org/abs/2405.12345'):
    return ET.fromstring(f'<feed xmlns="{ATOM}"><entry><id>{identifier}</id><title>{title}</title><summary>{summary}</summary></entry></feed>')

class ExpandedProvidersTests(unittest.TestCase):
    def test_provider_catalog_and_default_choices(self):
        self.assertEqual(core.APP_VERSION,'0.6.4')
        for key in ('arxiv','wikidata','loc','pubmed'):
            self.assertIn(key,core.SOURCES)
            self.assertIn(key,core.DEFAULT_SOURCES)
            self.assertIn(key,app.BUDGET)
        self.assertNotIn('searxng',core.DEFAULT_SOURCES)
        self.assertNotIn('gdelt',core.DEFAULT_SOURCES)
        self.assertTrue(all(x in core.SOURCES for x in core.DEFAULT_SOURCES))

    def test_arxiv_xml_parsing_and_endpoint(self):
        def get(url):
            parts=urllib.parse.urlsplit(url)
            self.assertEqual(parts.hostname,'export.arxiv.org')
            q=urllib.parse.parse_qs(parts.query)
            self.assertIn('all:ethical',q['search_query'][0])
            self.assertEqual(q['max_results'],['20'])
            return atom()
        got=core.arxiv('ethical hacking',20,get=get)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]['source'],'arXiv')
        self.assertEqual(got[0]['url'],'https://arxiv.org/abs/2405.12345')

    def test_arxiv_rejects_arbitrary_url(self):
        self.assertEqual(core.arxiv('test',10,get=lambda url:atom(identifier='https://evil.example.org/abs/2405.12345')),[])
        self.assertEqual(core.arxiv('test',10,get=lambda url:atom(identifier='http://arxiv.org/abs/../../secret')),[])

    def test_wikidata_entities(self):
        data={'search':[{'id':'Q1234','label':'Cybersecurity','description':'Information security'},
                        {'id':'BAD1','label':'Unwanted'}, {'id':'Q1','label':'First item'}]}
        got=core.wikidata('cybersecurity',20,get=lambda url:data)
        self.assertEqual([x['url'] for x in got],['https://www.wikidata.org/wiki/Q1234','https://www.wikidata.org/wiki/Q1'])
        self.assertEqual(got[0]['snippet'],'Information security')

    def test_loc_only_public_official_records(self):
        def get(url):
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual(q['fo'],['json'])
            self.assertEqual(q['c'],['30'])
            self.assertEqual(q['at'], ['results'])
            return {'results':[{'id':'https://www.loc.gov/item/1234567/','title':'Historic cybersecurity',
                                'description':['Some description', 'Another note']},
                               {'id':'https://other.example/item/2','title':'Bad off-domain'},
                               {'id':'http://www.loc.gov/item/3/','title':'Legacy LoC'}]}
        got=core.loc('cybersecurity history',40,get=get)
        self.assertEqual(len(got),2)
        self.assertEqual(got[1]['url'],'https://www.loc.gov/item/3/')
        self.assertIn('Some description',got[0]['snippet'])
        self.assertEqual(got[0]['source'],'Library of Congress')

    def test_pubmed_two_requests_metadata(self):
        called=[]
        def get(url):
            called.append(url)
            if '/esearch.fcgi?' in url:
                return {'esearchresult':{'idlist':['12345678','not-an-id','23456789','12345678']}}
            return {'result':{'12345678':{'title':'Cybersecurity health study','fulljournalname':'Journal','pubdate':'2025'},
                              '23456789':{'title':'Second study','pubdate':'2024'}}}
        with patch.object(core.time,'sleep') as sleep:
            got=core.pubmed('cybersecurity',40,get=get)
        self.assertEqual(len(got),2)
        self.assertEqual(got[0]['url'],'https://pubmed.ncbi.nlm.nih.gov/12345678/')
        self.assertIn('Journal',got[0]['snippet'])
        self.assertEqual(len(called),2)
        self.assertIn('12345678%2C23456789',called[1])
        sleep.assert_called_once()

    def test_pubmed_empty_search_avoids_summary_request(self):
        called=[]
        def get(url):
            called.append(url)
            return {'esearchresult':{'idlist':[]}}
        self.assertEqual(core.pubmed('unknown',50,get=get),[])
        self.assertEqual(len(called),1)

    def test_adapter_limits_and_empty(self):
        for adapt in (core.arxiv,core.wikidata,core.loc,core.pubmed):
            with self.subTest(adapt=adapt.__name__):
                self.assertEqual(adapt('something',0,get=lambda _: self.fail('No provider call expected')),[])

    def test_terminal_preview_labels_and_stored_source(self):
        with tempfile.TemporaryDirectory() as d:
            v=core.Vault(d)
            entries={
                'arxiv':[core.make_record('https://arxiv.org/abs/2405.12345','Ethical hacking research','','arXiv')],
                'wikidata':[core.make_record('https://www.wikidata.org/wiki/Q1234','Ethical security','','Wikidata')],
                'loc':[core.make_record('https://www.loc.gov/item/1234/','Cybersecurity collections','','Library of Congress')],
                'pubmed':[core.make_record('https://pubmed.ncbi.nlm.nih.gov/12345678/','Ethical health research','','PubMed')]}
            saved=io.StringIO()
            with patch.object(app,'VAULT',v), patch.object(app,'NEON',app.Neon('never')):
                with patch.object(core,'arxiv',return_value=entries['arxiv']),\
                     patch.object(core,'wikidata',return_value=entries['wikidata']),\
                     patch.object(core,'loc',return_value=entries['loc']),\
                     patch.object(core,'pubmed',return_value=entries['pubmed']),\
                     patch.object(app.time,'sleep'):
                    with redirect_stdout(saved):
                        sid=app.run_search('ethical cybersecurity',['arxiv','wikidata','loc','pubmed'],100,quality='broad')
            output=saved.getvalue()
            self.assertIn('[ARXIV]',output)
            self.assertIn('[WIKIDATA]',output)
            self.assertIn('[LOC]',output)
            self.assertIn('[PUBMED]',output)
            self.assertIn('https://pubmed.ncbi.nlm.nih.gov/12345678/',output)
            self.assertEqual(len(v.results(sid)),4)
            self.assertEqual(set(json.loads(v.run(sid)['reports']).keys()),set(entries))

    def test_failure_contained_one_provider(self):
        with tempfile.TemporaryDirectory() as d:
            v=core.Vault(d)
            with patch.object(app,'VAULT',v),\
                 patch.object(core,'arxiv',side_effect=TimeoutError('arxiv slow')),\
                 patch.object(core,'wikidata',return_value=[core.make_record('https://www.wikidata.org/wiki/Q42','Research result','','Wikidata')]),\
                 patch.object(app.time,'sleep'):
                sid=app.run_search('research',['arxiv','wikidata'],100,quality='broad')
            self.assertEqual(len(v.results(sid)),1)
            self.assertEqual(json.loads(v.run(sid)['reports'])['arxiv']['status'],'error')

    def test_xml_bounded_and_rejects_dtd(self):
        class Response:
            status=200
            headers={}
            def __init__(self, content):self.content=content
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,count):return self.content[:count]
        with patch.object(core.urllib.request,'urlopen',return_value=Response(b'<!DOCTYPE feed><feed/>')):
            with self.assertRaisesRegex(RuntimeError,'document declarations'):
                core.http_get_xml('https://export.arxiv.org/api/query?test')
        with patch.object(core.urllib.request,'urlopen',return_value=Response(b'<feed/>')):
            self.assertEqual(core.http_get_xml('https://export.arxiv.org/api/query?test').tag,'feed')

    def test_sources_visible_in_optional_dashboard_and_launch(self):
        base=Path(__file__).resolve().parents[1]
        html=(base/'blackswarm/ui.html').read_text()
        for src in ('arxiv','wikidata','loc','pubmed'):
            self.assertIn('value="'+src+'"',html)
        appfile=(base/'blackswarm/app.py').read_text()
        self.assertIn('TERMINAL-FIRST',appfile)
        self.assertIn('SOURCES:',appfile)
        self.assertIn('nine free public indexes',appfile)
        self.assertIn('for preview in found[:3]',appfile)

if __name__=='__main__':unittest.main()
