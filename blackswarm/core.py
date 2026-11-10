"""BLACKSWARM: passive public-source search aggregation (Python stdlib only)."""
from __future__ import annotations
import csv
import html
import ipaddress
import json
import os
import re
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path

APP_VERSION = '0.6.4'
SOURCES = ('wikipedia', 'crossref', 'gdelt', 'openlibrary', 'archive', 'europepmc', 'arxiv', 'wikidata', 'loc', 'pubmed', 'searxng')
STORE = Path(os.getenv('BLACKSWARM_DATA', str(Path.home() / '.local' / 'share' / 'blackswarm-v4-vault')))
USER_AGENT = f'BLACKSWARM/{APP_VERSION} (personal public-source research; no bulk scraping)'
DEFAULT_SOURCES = ('wikipedia', 'crossref', 'openlibrary', 'archive', 'europepmc', 'arxiv', 'wikidata', 'loc', 'pubmed')
TRACKERS = {'fbclid','gclid','msclkid','mc_cid','mc_eid','igshid'}


def clean_url(raw: str) -> str:
    if not isinstance(raw, str) or len(raw) > 4096:
        return ''
    try:
        u = urllib.parse.urlsplit(raw.strip())
        if u.scheme.lower() not in ('https','http') or not u.hostname or u.username or u.password:
            return ''
        host = u.hostname.lower().rstrip('.')
        if not host or any(x.isspace() for x in host):
            return ''
        port = u.port
        if port is not None and port != (443 if u.scheme.lower()=='https' else 80):
            host = f'{host}:{port}'
        q = urllib.parse.parse_qsl(u.query, keep_blank_values=True)
        q = [(k,v) for k,v in q if not k.lower().startswith('utm_') and k.lower() not in TRACKERS]
        path = urllib.parse.quote(urllib.parse.unquote(u.path or '/'), safe='/@:+~!$&\'()*;,=-._')
        return urllib.parse.urlunsplit((u.scheme.lower(),host,path,urllib.parse.urlencode(q),''))
    except (ValueError, UnicodeError):
        return ''


def searx_endpoint(value: str) -> str:
    """Only non-local HTTPS SearXNG endpoints; never fetch arbitrary user URLs."""
    if not value:
        return ''
    try:
        u = urllib.parse.urlsplit(value.strip())
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None,443):
            raise ValueError('Use a public HTTPS SearXNG instance URL, such as https://search.example.org')
        host = u.hostname.lower().rstrip('.')
        if host in ('localhost',) or host.endswith(('.localhost','.local','.internal')):
            raise ValueError('Local/internal instance addresses are not allowed')
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            addr = None
        if addr is not None and not addr.is_global:
            raise ValueError('Private or local network addresses are not allowed')
        if not re.fullmatch(r'[a-z0-9.-]+', host) or '.' not in host:
            raise ValueError('A public HTTPS hostname is required')
        # Ignore any supplied path/query/fragment to enforce fixed /search endpoint.
        return f'https://{host}/search'
    except ValueError as e:
        raise ValueError(f'Invalid SearXNG address: {e}') from e


def http_get_json(url: str, *, timeout=14):
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f'HTTP {response.status}')
        if int(response.headers.get('Content-Length','0') or '0') > 7_000_000:
            raise RuntimeError('Provider response too large')
        body = response.read(7_000_001)
        if len(body) > 7_000_000:
            raise RuntimeError('Provider response exceeded size limit')
        return json.loads(body.decode('utf-8-sig'))


def http_get_xml(url: str, *, timeout=16):
    """Bounded, read-only Atom retrieval; reject DTDs/entities before parsing."""
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT,
                                                'Accept': 'application/atom+xml, application/xml'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f'HTTP {response.status}')
        if int(response.headers.get('Content-Length','0') or '0') > 7_000_000:
            raise RuntimeError('Provider response too large')
        raw=response.read(7_000_001)
    if len(raw)>7_000_000:
        raise RuntimeError('Provider response exceeded size limit')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise RuntimeError('XML document declarations are not supported')
    return ET.fromstring(raw)

def make_record(url, title, snippet, source):
    url = clean_url(str(url or ''))
    if not url:
        return None
    # Providers may embed HTML in titles/snippets; only keep readable plain text.
    def clean_text(s, length):
        s = re.sub(r'<[^>]+>', ' ', str(s or ''))
        return re.sub(r'\s+', ' ', html.unescape(s)).strip()[:length]
    return {'url': url, 'title': clean_text(title, 320) or url,
            'snippet': clean_text(snippet, 700), 'source': source}


def wikipedia(query: str, limit: int, get=http_get_json):
    """English Wikipedia full-text pages; up to 100 per request, at most two pages."""
    results = []
    for offset in range(0, min(limit, 150), 50):
        take = min(50, limit-len(results))
        params = {'action':'query','list':'search','srsearch':query,'srnamespace':0,
                  'srlimit':take,'sroffset':offset,'format':'json','formatversion':2}
        url = 'https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode(params)
        data = get(url)
        page = data.get('query',{}).get('search',[])
        for item in page:
            title = item.get('title','')
            link = 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(title.replace(' ','_'),safe='()_:')
            rec = make_record(link, title, item.get('snippet',''), 'Wikipedia')
            if rec: results.append(rec)
        if len(page) < take or len(results) >= limit:
            break
        time.sleep(0.8)
    return results[:limit]


def crossref(query: str, limit: int, get=http_get_json):
    take = min(limit,500)
    url = 'https://api.crossref.org/works?' + urllib.parse.urlencode({
        'query':query,'rows':take,'select':'DOI,title,URL,container-title,published',
    })
    data = get(url)
    output = []
    for item in data.get('message',{}).get('items',[]):
        doi = item.get('DOI','')
        link = item.get('URL') or ('https://doi.org/' + doi if doi else '')
        t = item.get('title') or []
        title = t[0] if isinstance(t,list) and t else str(t)
        journal = item.get('container-title') or []
        snippet = journal[0] if isinstance(journal,list) and journal else ''
        rec = make_record(link,title,snippet,'Crossref')
        if rec: output.append(rec)
    return output


def gdelt(query: str, limit: int, get=http_get_json):
    take = min(limit, 200)
    params = {'query':query, 'mode':'artlist','format':'json','maxrecords':take,'timespan':'3months'}
    url = 'https://api.gdeltproject.org/api/v2/doc/doc?' + urllib.parse.urlencode(params)
    data = get(url)
    output = []
    for item in data.get('articles',[]):
        rec = make_record(item.get('url'), item.get('title'),
                          f"{item.get('domain','')} · {item.get('seendate','')}", 'GDELT News')
        if rec: output.append(rec)
    return output



def openlibrary(query: str, limit: int, get=http_get_json):
    """Published book work records; documented Open Library Search API."""
    results = []
    for page_no in range(1, 4):
        take = min(100, limit-len(results))
        if take <= 0:
            break
        params = {'q': query, 'fields': 'key,title,author_name,first_publish_year',
                  'limit': take, 'offset': (page_no-1)*100}
        data = get('https://openlibrary.org/search.json?' + urllib.parse.urlencode(params))
        docs = data.get('docs', [])
        for row in docs:
            key = str(row.get('key', ''))
            # Only canonical, documented work identifiers: no arbitrary web fetching.
            if not re.fullmatch(r'/works/OL[0-9]+W', key):
                continue
            author = row.get('author_name') or []
            authors = ', '.join(str(a) for a in author[:3]) if isinstance(author, list) else str(author)
            year = row.get('first_publish_year') or ''
            rec = make_record('https://openlibrary.org' + key, row.get('title'),
                              f'{authors} · {year}'.strip(' ·'), 'Open Library')
            if rec: results.append(rec)
        if len(docs) < take or len(results) >= limit:
            break
        time.sleep(0.9)
    return results[:limit]


def archive(query: str, limit: int, get=http_get_json):
    """Internet Archive public item catalogue; this is NOT Wayback URL crawling."""
    results = []
    for page_no in range(1, 4):
        if len(results) >= limit:
            break
        take = 100  # Fixed page size: the catalogue's page number depends on rows.
        params = [('q',query),('output','json'),('rows',str(take)),('page',str(page_no)),
                  ('fl[]','identifier'),('fl[]','title'),('fl[]','mediatype')]
        data = get('https://archive.org/advancedsearch.php?' + urllib.parse.urlencode(params))
        docs = data.get('response',{}).get('docs',[])
        for row in docs:
            identifier = str(row.get('identifier',''))
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,170}',identifier):
                continue
            rec = make_record('https://archive.org/details/' + urllib.parse.quote(identifier),
                              row.get('title') or identifier,
                              str(row.get('mediatype','')),'Internet Archive')
            if rec: results.append(rec)
        if len(docs)<take or len(results)>=limit:
            break
        time.sleep(0.9)
    return results[:limit]


def europepmc(query: str, limit: int, get=http_get_json):
    """Public scholarly records. Prefer DOI for cross-source dedup with Crossref."""
    take = min(limit,400)
    params = {'query':query,'format':'json','resultType':'lite','pageSize':take}
    data = get('https://www.ebi.ac.uk/europepmc/webservices/rest/search?' + urllib.parse.urlencode(params))
    output=[]
    for item in data.get('resultList',{}).get('result',[]):
        doi = str(item.get('doi') or '').strip()
        if doi and not re.search(r'\s',doi) and len(doi)<400:
            link = 'https://doi.org/' + doi
        else:
            source=str(item.get('source',''))
            uid=str(item.get('id',''))
            if not re.fullmatch(r'[A-Za-z]{2,6}',source) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}',uid):
                continue
            link = f'https://europepmc.org/article/{source}/{uid}'
        note = ' · '.join(filter(None,[str(item.get('journalTitle','')),
                                        str(item.get('firstPublicationDate',''))]))
        rec=make_record(link,item.get('title'),note,'Europe PMC')
        if rec: output.append(rec)
    return output


def arxiv(query: str, limit: int, get=http_get_xml):
    """One documented Atom search, capped at 100 academic-paper records."""
    take=min(100, max(0,limit))
    if not take:return []
    # all: searches arXiv metadata. This is not full web indexing.
    term=' AND '.join('all:'+word for word in query.split()[:8] if word.strip())
    params={'search_query':term, 'start':0, 'max_results':take,
            'sortBy':'relevance', 'sortOrder':'descending'}
    root=get('https://export.arxiv.org/api/query?' + urllib.parse.urlencode(params))
    ns='{http://www.w3.org/2005/Atom}'
    out=[]
    for entry in root.findall(ns+'entry')[:take]:
        original=(entry.findtext(ns+'id') or '').strip()
        # Accept only identifiers on the official arXiv abstract host.
        match=re.fullmatch(r'https?://(?:www\.)?arxiv\.org/abs/([A-Za-z0-9./-]+)',original)
        if not match:continue
        arxiv_id=match.group(1)
        if '..' in arxiv_id or len(arxiv_id)>70:continue
        rec=make_record('https://arxiv.org/abs/'+arxiv_id,
                        entry.findtext(ns+'title'),entry.findtext(ns+'summary'),'arXiv')
        if rec:out.append(rec)
    return out


def wikidata(query: str, limit: int, get=http_get_json):
    """Public entity label search (max 50 items); not general web pages."""
    take=min(50,max(0,limit))
    if not take:return []
    params={'action':'wbsearchentities','search':query,'language':'en',
            'format':'json','type':'item','limit':take}
    data=get('https://www.wikidata.org/w/api.php?' + urllib.parse.urlencode(params))
    out=[]
    for item in data.get('search',[])[:take]:
        identifier=str(item.get('id',''))
        if not re.fullmatch(r'Q[1-9][0-9]{0,15}',identifier):continue
        rec=make_record('https://www.wikidata.org/wiki/'+identifier,
                        item.get('label') or identifier,
                        item.get('description',''),'Wikidata')
        if rec:out.append(rec)
    return out


def loc(query: str, limit: int, get=None):
    """Library of Congress public collection search, single capped request."""
    take=min(100,max(0,limit))
    if not take:return []
    # The full LoC search JSON contains heavyweight facets and nested records.
    # Official 'at=results' returns only the result list, reducing payload size
    # and the chance of a slow request. A small one-page batch is intentional.
    take=min(take, 30)
    params={'q':query,'fo':'json','at':'results','c':take,'sp':1}
    url='https://www.loc.gov/search/?' + urllib.parse.urlencode(params)
    # A shorter socket timeout limits stalls in this slower public index.
    # No retries or parallel calls; other selected sources continue on failure.
    data=get(url) if get is not None else http_get_json(url, timeout=8)
    out=[]
    for item in data.get('results',[])[:take]:
        raw=str(item.get('id',''))
        parsed=urllib.parse.urlsplit(raw)
        if parsed.scheme not in ('http','https') or parsed.hostname not in ('loc.gov','www.loc.gov'):
            continue
        # LoC's API sometimes emits older http:// identifiers. Upgrade only
        # official loc.gov URLs to HTTPS, never follow arbitrary hosts.
        raw=urllib.parse.urlunsplit(('https','www.loc.gov',parsed.path,
                                     parsed.query,parsed.fragment))
        desc=item.get('description') or []
        if isinstance(desc,list): desc='; '.join(str(x) for x in desc[:2])
        rec=make_record(raw,item.get('title'),desc,'Library of Congress')
        if rec:out.append(rec)
    return out


def pubmed(query: str, limit: int, get=http_get_json):
    """NCBI PubMed ESearch + ESummary; no API key, two rate-aware GETs."""
    take=min(100,max(0,limit))
    if not take:return []
    search_params={'db':'pubmed','term':query,'retmode':'json','retmax':take,'sort':'relevance'}
    found=get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?'+urllib.parse.urlencode(search_params))
    ids=[]
    for raw in found.get('esearchresult',{}).get('idlist',[])[:take]:
        uid=str(raw)
        if re.fullmatch(r'[1-9][0-9]{0,12}',uid) and uid not in ids: ids.append(uid)
    if not ids:return []
    # The key-free NCBI API allows at most three requests per second.
    time.sleep(0.38)
    summary_params={'db':'pubmed','id':','.join(ids),'retmode':'json'}
    data=get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?'+urllib.parse.urlencode(summary_params))
    info=data.get('result',{})
    out=[]
    for uid in ids:
        item=info.get(uid,{})
        if not isinstance(item,dict):continue
        notes=' · '.join(str(x) for x in (item.get('fulljournalname',''),item.get('pubdate','')) if x)
        rec=make_record('https://pubmed.ncbi.nlm.nih.gov/'+uid+'/',
                        item.get('title') or 'PubMed record '+uid,notes,'PubMed')
        if rec:out.append(rec)
    return out

def searxng(query: str, limit: int, instance: str, get=http_get_json):
    endpoint = searx_endpoint(instance)
    if not endpoint:
        raise ValueError('No SearXNG instance configured')
    output = []
    for p in range(1,5):  # at most four pages, no unbounded pagination
        url = endpoint + '?' + urllib.parse.urlencode({'q':query,'format':'json',
                                                       'pageno':p, 'safesearch':'1'})
        data = get(url)
        page = data.get('results',[])
        for item in page:
            rec = make_record(item.get('url'),item.get('title'),item.get('content',''),'SearXNG')
            if rec: output.append(rec)
            if len(output) >= limit:
                return output[:limit]
        if not page:
            break
        if p < 4:
            time.sleep(1.25)
    return output[:limit]


def combine(records: list, max_results: int) -> list:
    """Cross-provider dedup while preserving all source labels for a URL."""
    found = {}
    for row in records:
        key = clean_url(row.get('url',''))
        if not key:
            continue
        if key in found:
            if row['source'] not in found[key]['sources']:
                found[key]['sources'].append(row['source'])
            if not found[key]['snippet'] and row.get('snippet'):
                found[key]['snippet'] = row['snippet']
        elif len(found) < max_results:
            found[key] = {'url':key,'title':row['title'],'snippet':row.get('snippet',''),
                          'sources':[row['source']]}
    return list(found.values())



# SMART SWARM ranks metadata only. No webpages are visited or scanned.
# Scores are transparent, heuristic *relevance hints*, not factual verification.
CYBER_TERMS = (
    'white hat', 'penetration testing', 'pentest', 'bug bounty', 'red team',
    'vulnerability', 'infosec', 'malware', 'phishing', 'security research',
    'cyber threat', 'ctf', 'kali linux', 'hackerone', 'wireshark',
)
STOP_TERMS = {'a','an','the','of','for','in','to','at','and','or','is','on','with','by','from',
              'public','about','find','search','resources','links','information'}

def _terms(value):
    words = re.findall(r'[a-z0-9]+',str(value).casefold())
    def norm(word):
        if word in ('hacker','hackers','hacking','hacked','hacks','hack'):
            return 'hack'
        if word in ('cybersecurity','cyber-security','cybersecure'):
            return 'cybersecurity'
        if word in ('pentesting','pentest','pentester'):
            return 'pentest'
        return word
    return {norm(w) for w in words if len(w)>1 and w not in STOP_TERMS}

def score_record(query, record):
    """Return (0..100, 'high'|'possible'|'low') for document metadata."""
    terms = _terms(query)
    title = str(record.get('title',''))[:320].casefold()
    snippet = str(record.get('snippet',''))[:700].casefold()
    url = urllib.parse.urlsplit(record.get('url','')).path.casefold()[:1000]
    title_words, snippet_words, path_words = _terms(title),_terms(snippet),_terms(url)
    score = 0
    seen = set()
    for word in terms:
        if word in title_words:
            score += 21; seen.add(word)
        elif word in snippet_words:
            score += 8; seen.add(word)
        elif word in path_words:
            score += 5; seen.add(word)
    if len(terms)>1 and len(seen)>=2:
        score += 10
    if len(terms)>1 and len(seen)==len(terms):
        score += 10
    phrase = ' '.join(str(query).casefold().strip().split())
    if len(phrase)>8 and phrase in title:
        score += 16
    if terms & {'hack','cybersecurity','security','pentest','infosec'}:
        related = sum(9 if t in title else 3 if t in snippet else 0 for t in CYBER_TERMS)
        score += min(related,18)
    score = min(100,score)
    high = 30 if len(terms)<=1 else 40
    return score, ('high' if score>=high else 'possible' if score>=16 else 'low')


def smart_rank(records, query, max_results, quality='focused'):
    """Rank the complete deduplicated candidate set before applying result limit.

    focused: exclude weak heuristically matched candidates.
    broad: preserve all, best-first. Entire candidate set is returned for audit.
    """
    if quality not in ('focused','broad','intent','precision'):
        raise ValueError('Quality must be focused, broad, intent or precision')
    if not 0 < max_results <= 1000:
        raise ValueError('Result limit must be between 1 and 1000')
    candidates = combine(records,max(1,len(records)))
    for row in candidates:
        if quality == 'intent':
            from .intent import score_intent
            insight = score_intent(query,row)
            row['score'],row['relevance'] = insight['score'],insight['relevance']
        elif quality == 'precision':
            from .precision import score_precision
            insight = score_precision(query,row)
            row['score'],row['relevance'] = insight['score'],insight['relevance']
        else:
            row['score'],row['relevance'] = score_record(query,row)
    # Stable order when scores tie keeps original provider sequence.
    candidates.sort(key=lambda x:x['score'],reverse=True)
    eligible = [r for r in candidates if quality=='broad' or r['relevance']!='low']
    selected = eligible[:max_results]
    selected_urls = {r['url'] for r in selected}
    for row in candidates:
        row['selected'] = row['url'] in selected_urls
    stats = {'quality':quality,'candidates':len(candidates),'eligible':len(eligible),
             'selected':len(selected),'filtered_low':sum(r['relevance']=='low' for r in candidates),
             'high':sum(r['relevance']=='high' for r in candidates),
             'possible':sum(r['relevance']=='possible' for r in candidates)}
    return selected,candidates,stats


class Vault:
    def __init__(self, folder=STORE):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.dbpath = self.folder / 'results.sqlite3'
        self.lock = threading.RLock()
        with self._connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stamp TEXT NOT NULL,
                    query TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    requested INTEGER NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    reports TEXT NOT NULL DEFAULT '{}',
                    stats TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS links (
                    run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    sources TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    relevance TEXT NOT NULL DEFAULT 'unscored',
                    PRIMARY KEY (run_id,url),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE INDEX IF NOT EXISTS links_run_idx ON links(run_id);
                CREATE TABLE IF NOT EXISTS candidates (
                    run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    sources TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    relevance TEXT NOT NULL,
                    selected INTEGER NOT NULL,
                    PRIMARY KEY(run_id,url),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE INDEX IF NOT EXISTS candidates_run_idx ON candidates(run_id);
            ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.dbpath, timeout=8)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def store(self, query, mode, requested, results, reports, candidates=None, stats=None):
        with self.lock, self._connect() as c:
            cur = c.execute('INSERT INTO runs(stamp,query,mode,requested,total,reports,stats) VALUES(?,?,?,?,?,?,?)',
                            (datetime.now(timezone.utc).isoformat(timespec='seconds'),query,mode,
                             requested,len(results),json.dumps(reports),json.dumps(stats or {})))
            rid = cur.lastrowid
            c.executemany('INSERT INTO links(run_id,url,title,snippet,sources,score,relevance) VALUES(?,?,?,?,?,?,?)',
                          [(rid,r['url'],r['title'],r['snippet'],json.dumps(r['sources']),
                            r.get('score',0),r.get('relevance','unscored')) for r in results])
            if candidates is not None:
                c.executemany('INSERT INTO candidates(run_id,url,title,snippet,sources,score,relevance,selected) VALUES(?,?,?,?,?,?,?,?)',
                              [(rid,r['url'],r['title'],r['snippet'],json.dumps(r['sources']),
                                r['score'],r['relevance'],int(bool(r.get('selected')))) for r in candidates])
            return rid

    def runs(self, limit=30):
        with self.lock, self._connect() as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute('SELECT id,stamp,query,mode,requested,total,reports,stats FROM runs ORDER BY id DESC LIMIT ?', (limit,))]

    def count_runs(self):
        with self.lock, self._connect() as c:
            return c.execute('SELECT count(*) FROM runs').fetchone()[0]

    def results(self, rid):
        with self.lock, self._connect() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute('SELECT url,title,snippet,sources,score,relevance FROM links WHERE run_id=? ORDER BY rowid', (rid,)).fetchall()
            return [{**dict(r),'sources':json.loads(r['sources'])} for r in rows]

    def candidates(self, rid, only_excluded=False):
        sql = 'SELECT url,title,snippet,sources,score,relevance,selected FROM candidates WHERE run_id=?'
        if only_excluded: sql += ' AND selected=0'
        sql += ' ORDER BY score DESC,rowid'
        with self.lock, self._connect() as c:
            c.row_factory = sqlite3.Row
            return [{**dict(r),'sources':json.loads(r['sources']),'selected':bool(r['selected'])}
                    for r in c.execute(sql,(rid,))]

    def run(self, rid):
        with self.lock, self._connect() as c:
            c.row_factory = sqlite3.Row
            row = c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            return dict(row) if row else None


DEMO = [
    ('https://example.org/solar','Solar energy research overview','Illustrative public web result','SearXNG'),
    ('https://en.wikipedia.org/wiki/Solar_energy','Solar energy','Illustrative encyclopedia result','Wikipedia'),
    ('https://doi.org/10.0000/demo-sample','Sample research publication','Illustrative scholarly result','Crossref'),
    ('https://news.example.org/renewables','Renewable energy headlines','Illustrative news source','GDELT News'),
    ('https://example.org/solar?utm_source=example','Solar energy research overview','Duplicate with tracking parameter','SearXNG'),
    ('https://example.net/datasets','Open data and datasets','Illustrative dataset','SearXNG'),
    ('https://en.wikipedia.org/wiki/Wind_power','Wind power','Illustrative reference page','Wikipedia'),
    ('https://doi.org/10.0000/another-demo','Second research record','Illustrative scholarly record','Crossref'),
]


def demo_results(limit):
    return combine([make_record(*r) for r in DEMO],limit)


def export_content(vault, rid, fmt):
    run = vault.run(rid)
    if not run:
        raise ValueError('Unknown research session')
    rows = vault.results(rid)
    if fmt=='rawjson':
        return json.dumps({'session':run,'candidates':vault.candidates(rid)},indent=2,ensure_ascii=False).encode('utf-8'), 'application/json', 'raw.json'
    if fmt=='rawcsv':
        import io
        buffer=io.StringIO(newline='')
        writer=csv.writer(buffer)
        writer.writerow(['url','title','snippet','sources','score','relevance','selected'])
        def safe(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        for r in vault.candidates(rid):
            writer.writerow([safe(r['url']),safe(r['title']),safe(r['snippet']),
                             safe(' | '.join(r['sources'])),r['score'],r['relevance'],r['selected']])
        return buffer.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', 'raw.csv'
    if fmt=='json':
        return json.dumps({'session':run,'results':rows},indent=2,ensure_ascii=False).encode('utf-8'), 'application/json', 'json'
    if fmt=='csv':
        import io
        io_buf = io.StringIO(newline='')
        writer = csv.writer(io_buf)
        writer.writerow(['url','title','snippet','sources','score','relevance'])
        def spreadsheet_safe(x):
            x = str(x)
            return "'" + x if x.lstrip().startswith(('=','+','-','@')) else x
        for r in rows:
            writer.writerow([spreadsheet_safe(r['url']),spreadsheet_safe(r['title']),
                             spreadsheet_safe(r['snippet']),spreadsheet_safe(' | '.join(r['sources'])),r.get('score',0),r.get('relevance','unscored')])
        return io_buf.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', 'csv'
    if fmt=='html':
        esc=html.escape
        items='\n'.join(f'<article><a href="{esc(r["url"],quote=True)}" target="_blank" rel="noopener noreferrer">{esc(r["title"])}</a><small>{esc(" | ".join(r["sources"]))} · relevance: {esc(r.get("relevance","unscored"))} · heuristic score: {r.get("score",0)}</small><p>{esc(r["snippet"])}</p><code>{esc(r["url"])}</code></article>' for r in rows)
        out=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BLACKSWARM Research Report</title><style>body{{background:#080d14;color:#e9edfb;font:16px system-ui;margin:auto;max-width:900px;padding:30px}}h1{{color:#a6ff5a}}.hint,small,code{{color:#9eacb6}}article{{background:#111c28;border-left:3px solid #9cff50;padding:18px;margin:15px 0;border-radius:9px;overflow-wrap:anywhere}}a{{color:#75deff;font-weight:bold;text-decoration:none}}small{{display:block;margin-top:8px}}p{{color:#c0c9d8}}</style><h1>☣ BLACKSWARM</h1><p class="hint">Local research report · {esc(run['stamp'])} · {len(rows)} unique links</p><h2>{esc(run['query'])}</h2><p class="hint">{esc(run['mode'].upper())} mode. Public indexed metadata only; publication and link availability not independently verified.</p>{items}</html>'''
        return out.encode('utf-8'), 'text/html; charset=utf-8', 'html'
    raise ValueError('Unsupported export format')
