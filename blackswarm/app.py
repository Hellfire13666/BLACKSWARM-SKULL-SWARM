"""BLACKSWARM desktop localhost UI. No third-party Python packages."""
from __future__ import annotations
import argparse
import json
import os
import sys
import threading
import re
from collections import deque
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from . import core, intel, navigator, bookmarks, collections, guard
from .neon import Neon

ROOT = Path(__file__).resolve().parent
JOBS = {'current': None}
JOBS_LOCK = threading.RLock()
VAULT = None
BUDGET = {'wikipedia':150, 'crossref':500, 'gdelt':200, 'openlibrary':200, 'archive':200, 'europepmc':400, 'searxng':200}
# Console-first: browser-launched searches print the same provider activity and
# individual saved links to the *launching terminal*. A bounded copy also feeds
# the dashboard console. Never execute received text or ANSI from data providers.
NEON = Neon('auto')
EVENTS = deque(maxlen=900)
EVENT_LOCK = threading.RLock()
EVENT_SEQ = 0
PRINT_LOCK = threading.RLock()

def terminal_event(kind, message, url=''):
    global EVENT_SEQ
    clean = re.sub(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]', ' ', str(message))[:420]
    valid_url = core.clean_url(url) if url else ''
    with EVENT_LOCK:
        EVENT_SEQ += 1
        EVENTS.append({'seq':EVENT_SEQ,'kind':kind,'text':clean,'url':valid_url})
    colors = {'start':'purple','source':'cyan','ok':'green','error':'red',
              'link':'cyan','saved':'green','note':'yellow'}
    color = colors.get(kind, 'white')
    signs = {'start':'◈','source':'↗','ok':'✓','error':'✗','link':'↳','saved':'▣','note':'·'}
    with PRINT_LOCK:
        print(NEON.fg(f'  {signs.get(kind,"·")} ',color) +
              NEON.fg(clean,color,kind in ('saved','start')),
              flush=True)

def clear_events():
    global EVENT_SEQ
    with EVENT_LOCK:
        EVENTS.clear()
        # Sequence deliberately monotonic; clients do not need to reset cursors.




def run_search(query, sources, limit, instance='', demo=False, update=None, quality='focused'):
    global VAULT
    if not query.strip() or len(query)>180:
        raise ValueError('Enter a search phrase of up to 180 characters')
    limit = int(limit)
    if quality not in ('focused','broad'):
        raise ValueError('Choose focused or broad quality mode')
    if limit not in (50,100,250,500,1000):
        raise ValueError('Choose a supported result limit')
    if not demo and not sources:
        raise ValueError('Choose at least one search source')
    if not demo and 'searxng' in sources:
        core.searx_endpoint(instance)
    terminal_event('start', f"{'DEMO' if demo else 'LIVE'}  |  {query}  |  maximum {limit} unique URLs  |  {'sample' if demo else quality.upper()}")
    if demo:
        entries = core.demo_results(limit)
        reports = {'Demo':{'status':'sample only','found':len(entries)}}
        rid = VAULT.store(query,'demo',limit,entries,reports)
        for i, entry in enumerate(entries, 1):
            terminal_event('link', f"{i:03d}  [DEMO] {entry['url']}", entry['url'])
        terminal_event('saved', f'DEMO ONLY  |  {len(entries)} illustrative links  |  session #{rid}')
        if update: update('Demo saved', reports, rid)
        return rid
    batches = []
    reports = {}
    for source in sources:
        if source not in core.SOURCES:
            continue
        terminal_event('source', f'Checking {source.upper()} public index…')
        if update: update(f'Checking {source}…',reports,None)
        try:
            get = {'wikipedia': lambda:core.wikipedia(query,min(limit,BUDGET[source])),
                   'crossref':lambda:core.crossref(query,min(limit,BUDGET[source])),
                   'gdelt':lambda:core.gdelt(query,min(limit,BUDGET[source])),
                   'openlibrary':lambda:core.openlibrary(query,min(limit,BUDGET[source])),
                   'archive':lambda:core.archive(query,min(limit,BUDGET[source])),
                   'europepmc':lambda:core.europepmc(query,min(limit,BUDGET[source])),
                   'searxng':lambda:core.searxng(query,min(limit,BUDGET[source]),instance)}[source]
            found = get()
            batches.append(found)
            reports[source] = {'status':'ok','found':len(found)}
            terminal_event('ok', f'{source.upper()} returned {len(found)} candidate URLs')
        except Exception as exc:
            message = str(exc)
            if len(message)>160: message = message[:160]+'…'
            reports[source] = {'status':'error','found':0,'detail':message}
            terminal_event('error', f'{source.upper()} unavailable: {message}')
        if update: update(f'Checked {source}',reports,None)
        time.sleep(0.3)
    # Rotate across sources so one large provider does not bury the others.
    from itertools import zip_longest
    interleaved = [r for group in zip_longest(*batches) for r in group if r is not None] if batches else []
    entries,candidates,stats=core.smart_rank(interleaved,query,limit,quality)
    rid = VAULT.store(query,'live',limit,entries,reports,candidates=candidates,stats=stats)
    terminal_event('note', f"SMART SWARM  |  {stats['candidates']} unique candidates  |  {stats['high']} high  |  {stats['possible']} possible  |  {stats['filtered_low']} low")
    terminal_event('note', f"SELECTED {len(entries)}  |  mode {quality.upper()}  |  every candidate retained in vault")
    for i, entry in enumerate(entries, 1):
        source_list = ', '.join(entry['sources'])
        terminal_event('link', f"{i:03d}  [{entry['relevance'].upper():8s} {entry['score']:02d}] [{source_list}] {entry['title'][:105]}")
        terminal_event('link', f"      {entry['url']}", entry['url'])
    terminal_event('saved', f'VAULT SAVED  |  session #{rid}  |  {len(entries)} ranked public URLs')
    if update: update('Search finished',reports,rid)
    return rid


class Handler(BaseHTTPRequestHandler):
    server_version='BLACKSWARM/0.5.7'
    def log_message(self, fmt, *args):
        if os.getenv('BLACKSWARM_VERBOSE'):
            super().log_message(fmt, *args)

    def send_data(self, data:bytes, content_type='application/json', status=200, extra=None):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data, status=200):
        self.send_data(json.dumps(data,ensure_ascii=False).encode('utf-8'),status=status)

    def do_GET(self):
        u=urllib.parse.urlsplit(self.path)
        args=urllib.parse.parse_qs(u.query)
        if u.path=='/':
            self.send_data((ROOT/'ui.html').read_bytes(),'text/html; charset=utf-8')
        elif u.path=='/ui.css':
            self.send_data((ROOT/'ui.css').read_bytes(),'text/css; charset=utf-8')
        elif u.path=='/ui.js':
            self.send_data((ROOT/'ui.js').read_bytes(),'text/javascript; charset=utf-8')
        elif u.path=='/api/state':
            with JOBS_LOCK:
                self.send_json(JOBS.get('current') or {'phase':'idle'})
        elif u.path=='/api/events':
            try:
                after=max(0,int(args.get('after',['0'])[0]))
                with EVENT_LOCK:
                    items=[e for e in EVENTS if e['seq']>after]
                    self.send_json({'events':items[-120:], 'latest':EVENT_SEQ})
            except ValueError: self.send_json({'error':'Invalid cursor'},400)
        elif u.path=='/api/compare':
            try:
                current=int(args.get('current',['0'])[0]); previous=int(args.get('previous',['0'])[0])
                if current==previous: raise ValueError('Select two different sessions')
                if not VAULT.run(current) or not VAULT.run(previous): raise ValueError('Unknown session')
                now=VAULT.results(current); before=VAULT.results(previous)
                present={r['url']:r for r in now}; older={r['url']:r for r in before}
                new=[r for r in now if r['url'] not in older]
                missing=[r for r in before if r['url'] not in present]
                self.send_json({'current':current,'previous':previous,'added':len(new),
                                'removed':len(missing),'unchanged':len(set(present)&set(older)),
                                'new_links':new[:60],'missing_links':missing[:60]})
            except (ValueError,TypeError) as e: self.send_json({'error':str(e)},400)
        elif u.path=='/api/runs':
            self.send_json({'runs':VAULT.runs(),'count':VAULT.count_runs()})
        elif u.path=='/api/results':
            try:
                rid=int(args.get('id',['0'])[0])
                row=VAULT.run(rid)
                if not row: raise ValueError('Not found')
                self.send_json({'run':row,'results':VAULT.results(rid)})
            except (ValueError,TypeError): self.send_json({'error':'Unknown session'},404)
        elif u.path=='/api/export':
            try:
                rid=int(args.get('id',['0'])[0]); fmt=args.get('format',['json'])[0]
                if fmt not in ('json','csv','html','rawcsv','rawjson'): raise ValueError('Unsupported format')
                data,ct,ext=core.export_content(VAULT,rid,fmt)
                self.send_data(data,ct,extra={'Content-Disposition':f'attachment; filename="BLACKSWARM-run-{rid}.{ext}"'})
            except (ValueError,TypeError) as e: self.send_json({'error':str(e)},400)
        else:
            self.send_json({'error':'Not found'},404)

    def do_POST(self):
        if self.path!='/api/start':
            self.send_json({'error':'Not found'},404); return
        origin=self.headers.get('Origin','')
        host=self.headers.get('Host','')
        # Reject browser cross-origin form posts and non-JSON requests.
        if origin not in ('',f'http://{host}') or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            self.send_json({'error':'Local same-origin JSON request required'},403);return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<1 or n>4096: raise ValueError('Request too large')
            payload=json.loads(self.rfile.read(n))
            query=str(payload.get('query','')).strip()
            limit=int(payload.get('limit',100))
            sources=payload.get('sources',[])
            if not isinstance(sources,list) or any(s not in core.SOURCES for s in sources):
                raise ValueError('Invalid sources')
            if not query or len(query)>180 or limit not in (50,100,250,500,1000):
                raise ValueError('Enter a short search and valid result limit')
            demo = payload.get('demo') is True
            instance = str(payload.get('instance',''))[:200]
            quality = str(payload.get('quality','focused'))
            if quality not in ('focused','broad'): raise ValueError('Invalid quality mode')
            if not demo and not sources: raise ValueError('Choose a source')
            if not demo and 'searxng' in sources: core.searx_endpoint(instance)
        except (ValueError,TypeError,AttributeError,json.JSONDecodeError) as e:
            self.send_json({'error':str(e)},400);return
        with JOBS_LOCK:
            if JOBS.get('current',{}) and JOBS['current'].get('phase')=='running':
                self.send_json({'error':'A search is already running'},409);return
            JOBS['current']={'phase':'running','message':'Starting public-source search',
                             'reports':{},'run_id':None,'query':query}
        def update(message,reports,rid):
            with JOBS_LOCK:
                JOBS['current'].update({'message':message,'reports':dict(reports),'run_id':rid})
        def work():
            try:
                rid=run_search(query,sources,limit,instance,demo,update,quality)
                with JOBS_LOCK: JOBS['current'].update({'phase':'done','run_id':rid})
            except Exception as e:
                terminal_event('error', str(e)[:200])
                with JOBS_LOCK: JOBS['current'].update({'phase':'error','message':str(e)[:200]})
        threading.Thread(target=work,daemon=True,name='BLACKSWARM search').start()
        self.send_json({'started':True},202)



# BLACKSWARM 0.3.1: the interactive terminal is the primary interface.
# No graphical application or browser is launched without explicit request.
def _terminal_history(neon):
    rows = VAULT.runs(limit=15)
    if not rows:
        print(neon.fg('  No saved sessions yet.', 'yellow'))
        return
    print(neon.fg('  SAVED SESSIONS  (latest 15)', 'purple', True))
    for row in rows:
        query = str(row['query']).replace('\n', ' ')[:65]
        print(neon.fg(f"  #{row['id']:>4}  ", 'cyan') +
              neon.fg(str(row['mode']).upper().ljust(5), 'purple') +
              neon.fg(f"  {row['total']:>4} URLs  ", 'green') + query)



def _terminal_examples(neon):
    """Terminal-only built-in help. No network calls, exports or browser."""
    print('\n' + neon.fg('  ╔══════════ BLACKSWARM // EXAMPLE DESK ══════════╗', 'purple', True))
    print(neon.fg('  ║      SESSION IDs  ·  SEARCHES  ·  EXPORTS       ║', 'cyan'))
    print(neon.fg('  ╚═══════════════════════════════════════════════╝', 'purple'))
    print(neon.fg('  SAMPLE ONLY: What a saved session looks like', 'yellow', True))
    print(neon.fg('    #1 ', 'cyan', True) + ' ethical hacking cybersecurity  |  500 saved links')
    print(neon.fg('    #2 ', 'cyan', True) + ' open source research           |  100 saved links')
    print(neon.fg('    These two lines are examples, NOT your actual sessions.', 'yellow'))
    print(neon.fg('  YOUR ACTUAL SAVED SESSION IDs', 'green', True))
    if VAULT is None:
        print(neon.fg('    No local vault opened.', 'yellow'))
    else:
        actual=VAULT.runs(limit=8)
        if not actual:
            print(neon.fg('    None yet. Run [1] Live Search or [2] Offline Demo first.', 'yellow'))
        else:
            for item in actual:
                phrase=re.sub(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]', ' ', str(item['query']))[:43]
                print(neon.fg(f"    #{item['id']:<4}", 'cyan') +
                      neon.fg(f"{item['total']:>5} links  ", 'green') + phrase)
    print(neon.fg('  WHERE TO USE THE SESSION ID', 'purple', True))
    print('    [3] Find your saved session numbers and searches')
    print('    [4] View every saved link in a session')
    print('    [5] Export that session to CSV, JSON or HTML FILE')
    print('    [7] Review its unselected / excluded candidates')
    print(neon.fg('  EXAMPLE SEARCH (NOT executed)', 'green', True))
    print(neon.fg('    Menu: ', 'pink') + '1  |  Search: ethical hacking cybersecurity')
    print(neon.fg('    Sources: ', 'pink') + 'press Enter (five free public indexes)')
    print(neon.fg('    Limit: ', 'pink') + '250  |  Quality: focused')
    print(neon.fg('  TIP: When prompted for Session ID, type ?', 'cyan', True))
    print(neon.fg('  No web browser is opened by this help screen.\n', 'green'))


def _ask_session_id(neon):
    """Show actual session IDs beside the input, with ? for examples."""
    recent=VAULT.runs(limit=5)
    if recent:
        numbers=', '.join('#'+str(item['id']) for item in recent)
        print(neon.fg('  YOUR RECENT SESSION IDs: '+numbers, 'green'))
        print(neon.fg('  Menu [3] shows each session with its search and link count.', 'purple'))
    else:
        print(neon.fg('  No saved sessions yet; use [1] or [2] to make one.', 'yellow'))
    while True:
        answer=input(neon.fg('  Session ID (? = examples; Enter = cancel): ', 'cyan')).strip()
        if not answer:
            print(neon.fg('  Returning to menu; nothing changed.', 'purple'))
            return None
        if answer.lower() in ('?', 'help', 'h'):
            _terminal_examples(neon)
            continue
        try:
            number=int(answer)
        except ValueError:
            print(neon.fg('  Enter a number from [3] Session History, or ? for examples.', 'yellow'))
            continue
        if number<=0 or not VAULT.run(number):
            print(neon.fg(f'  Session #{number} is not in this vault; check menu [3].', 'yellow'))
            continue
        return number


def _terminal_session(neon, selected):
    try:
        sid=int(selected)
    except ValueError:
        print(neon.fg('  Enter a numeric session ID.', 'yellow'))
        return
    row=VAULT.run(sid)
    if not row:
        print(neon.fg('  No saved session with that ID.', 'yellow'))
        return
    neon.summary(row, VAULT.dbpath, sid)
    for number,item in enumerate(VAULT.results(sid),1):
        terminal_event('link', f"{number:03d}  [{item['relevance'].upper()} {item['score']}]  {item['title'][:100]}")
        terminal_event('link', '       '+item['url'], item['url'])


def _terminal_export(neon):
    sid=_ask_session_id(neon)
    if sid is None:
        return
    kind=input(neon.fg('  Format [json/csv/html/rawcsv/rawjson] (default csv): ', 'cyan')).strip().lower() or 'csv'
    if kind not in ('json','csv','html','rawcsv','rawjson'):
        print(neon.fg('  Supported formats: json, csv, html, rawcsv, rawjson.', 'yellow'))
        return
    try:
        data,_,extension=core.export_content(VAULT,sid,kind)
        # Exports are written only when specifically requested, in a local
        # BLACKSWARM folder in the user's home directory.
        folder=Path.home()/'Documents'/'BLACKSWARM-EXPORTS'
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        destination=folder/f'BLACKSWARM-run-{sid}.{extension}'
        if destination.exists():
            print(neon.fg('  File already exists. Nothing overwritten.', 'yellow'))
            return
        with destination.open('xb') as output:
            output.write(data)
        print(neon.fg('  ✓ EXPORTED ', 'green') + str(destination))
    except ValueError as exc:
        print(neon.fg(f'  {exc}', 'yellow'))


def _terminal_excluded(neon):
    sid=_ask_session_id(neon)
    if sid is None: return
    rows=VAULT.candidates(sid,only_excluded=True)
    print(neon.fg(f'  FILTERED / NOT SELECTED: {len(rows)} candidates', 'purple',True))
    for i,row in enumerate(rows,1):
        terminal_event('note',f"{i:03d}  [{row['relevance'].upper()} {row['score']}] {row['title'][:100]}")
        terminal_event('link', '      '+row['url'],row['url'])
    if not rows: print(neon.fg('  No excluded candidates for this session.','green'))



def _terminal_constellation(neon, sid=None):
    if sid is None:
        sid=_ask_session_id(neon)
    if sid is None: return
    run=VAULT.run(sid)
    if not run:
        print(neon.fg('  Session not found in this vault.', 'yellow')); return
    summary=intel.make_constellation(run,VAULT.results(sid),VAULT.candidates(sid))
    intel.show_constellation(neon,summary)


def _terminal_delta(neon, older=None, newer=None):
    if older is None or newer is None:
        history=VAULT.runs(limit=10)
        if len(history)<2:
            print(neon.fg('  Need two saved sessions to compare. No new search has been started.', 'yellow'))
            return
        print(neon.fg('  TWO-SESSION COMPARISON: select older then newer ID.', 'purple'))
        _terminal_history(neon)
        print(neon.fg('  OLDER session ID:', 'cyan'))
        older=_ask_session_id(neon)
        if older is None: return
        print(neon.fg('  NEWER session ID:', 'cyan'))
        newer=_ask_session_id(neon)
        if newer is None: return
    first,second=VAULT.run(older),VAULT.run(newer)
    if not first or not second:
        print(neon.fg('  Both sessions must exist in the current vault.', 'yellow')); return
    try:
        intel.show_delta(neon,intel.compare_sessions(first,VAULT.results(older),second,VAULT.results(newer)))
    except ValueError as error:
        print(neon.fg('  '+str(error), 'yellow'))


def _terminal_navigator(neon, sid=None, input_fn=None):
    """Interactively navigate one saved session, without writing to the vault."""
    if sid is None:
        sid=_ask_session_id(neon)
    if sid is None:
        return
    run=VAULT.run(sid)
    if not run:
        print(neon.fg('  Session not found in this vault.', 'yellow'))
        return
    navigator.navigate(neon,run,VAULT.results(sid),input_fn=input_fn,
                       bookmark_factory=lambda:bookmarks.BookmarkShelf())



def _terminal_bookmarks(neon, input_fn=None):
    """Optional write access to independent bookmarks ONLY; research vault unchanged."""
    shelf=bookmarks.BookmarkShelf()
    bookmarks.bookmark_desk(neon,VAULT,shelf,input_fn=input_fn,ask_session=_ask_session_id)


def _terminal_collections(neon, input_fn=None):
    """Separate local collection DB made from starred bookmarks only."""
    shelf=bookmarks.BookmarkShelf()
    store=collections.IntelCollections(shelf.folder)
    collections.collection_desk(neon,store,shelf,input_fn=input_fn)


def terminal_menu(neon, default_limit=100):
    neon.banner()
    print(neon.fg('  ● LAB v0.5.7  |  TERMINAL-FIRST VAULT GUARD + TAGS  |  NO AUTO BROWSER', 'green', True))
    print(neon.fg('  ◈ VAULT ', 'purple')+str(VAULT.dbpath))
    print(neon.fg('  Browser stays closed unless YOU explicitly open it.', 'cyan'))
    while True:
        print('\n'+neon.fg('  ══════════════ SWARM COMMAND DECK ══════════════', 'purple'))
        print(neon.fg('  [1] ', 'green') + 'LIVE PUBLIC-INDEX SEARCH')
        print(neon.fg('  [2] ', 'cyan') + 'OFFLINE DEMO (7 illustrative URLs)')
        print(neon.fg('  [3] ', 'purple') + 'SAVED SESSION HISTORY')
        print(neon.fg('  [4] ', 'pink') + 'SHOW ALL LINKS FROM A SESSION')
        print(neon.fg('  [5] ', 'yellow') + 'EXPORT SESSION (CSV / JSON / HTML / RAW)' )
        print(neon.fg('  [6] ', 'blue') + 'OPTIONAL DASHBOARD (prints URL only)')
        print(neon.fg('  [7] ', 'pink') + 'REVIEW ALL EXCLUDED CANDIDATES')
        print(neon.fg('  [8] ', 'cyan') + 'EXAMPLE DESK // SESSION IDs + QUICK HELP')
        print(neon.fg('  [9] ', 'green') + 'SWARM CONSTELLATION // READ-ONLY LINK MAP')
        print(neon.fg(' [10] ', 'pink') + 'SESSION DELTA // COMPARE TWO SEARCHES')
        print(neon.fg(' [11] ', 'cyan') + 'CONSTELLATION NAVIGATOR // INTERACTIVE LINK DRILLDOWN')
        print(neon.fg(' [12] ', 'yellow') + 'BOOKMARKED INTEL // STAR CONTROL + NOTES')
        print(neon.fg(' [13] ', 'green') + 'INTEL COLLECTIONS // RADAR + TAGS + PULSE')
        print(neon.fg(' [14] ', 'cyan') + 'VAULT GUARD // PRIVATE BACKUP + VERIFY')
        print(neon.fg('  [0] ', 'red') + 'QUIT')
        choice=input(neon.fg('  BLACKSWARM ❯ ', 'green', True)).strip()
        if choice == '0' or choice.lower() in ('q','quit','exit'):
            print(neon.fg('  ☣ BLACKSWARM closed.', 'purple'))
            return 0
        if choice == '1':
            query=input(neon.fg('  Search phrase: ', 'cyan')).strip()
            if not query: print(neon.fg('  Search phrase cannot be blank.', 'yellow')); continue
            print(neon.fg('  SOURCES: wikipedia,crossref,gdelt,openlibrary,archive,europepmc,searxng', 'purple'))
            value=input(neon.fg('  Sources [Enter = free public indexes]: ', 'cyan')).strip()
            sources=[x.strip().lower() for x in value.split(',') if x.strip()] if value else ['wikipedia','crossref','openlibrary','archive','europepmc']
            unknown=[x for x in sources if x not in core.SOURCES]
            if unknown:
                print(neon.fg('  Unknown sources: '+', '.join(unknown), 'yellow'));continue
            selection=input(neon.fg('  Max unique links [50/100/250/500/1000; default 100]: ', 'cyan')).strip() or str(default_limit)
            try:
                amount=int(selection)
                if amount not in (50,100,250,500,1000): raise ValueError('Unsupported limit')
                instance=input(neon.fg('  Public HTTPS SearXNG URL: ', 'cyan')).strip() if 'searxng' in sources else ''
                quality=input(neon.fg('  Quality [focused/broad; default focused]: ', 'cyan')).strip().lower() or 'focused'
                rid=run_search(query,sources,amount,instance,quality=quality)
                neon.summary(VAULT.run(rid),VAULT.dbpath,rid)
            except ValueError as exc:
                print(neon.fg('  '+str(exc), 'yellow'))
        elif choice == '2':
            rid=run_search('demo: public research',[],50,demo=True)
            neon.summary(VAULT.run(rid),VAULT.dbpath,rid)
        elif choice == '3':
            _terminal_history(neon)
        elif choice == '4':
            sid=_ask_session_id(neon)
            if sid is not None: _terminal_session(neon,str(sid))
        elif choice == '5':
            _terminal_export(neon)
        elif choice == '7':
            _terminal_excluded(neon)
        elif choice == '8':
            _terminal_examples(neon)
        elif choice == '9':
            _terminal_constellation(neon)
        elif choice == '10':
            _terminal_delta(neon)
        elif choice == '11':
            _terminal_navigator(neon)
        elif choice == '12':
            _terminal_bookmarks(neon)
        elif choice == '13':
            _terminal_collections(neon)
        elif choice == '14':
            guard.guard_desk(neon)
        elif choice == '6':
            print(neon.fg('  DASHBOARD MODE IS OPTIONAL. No browser will open.', 'cyan'))
            print(neon.fg('  You can paste the printed URL into a browser if wanted.', 'yellow'))
            run_dashboard(neon, open_browser=False)
            neon.banner()
        else:
            print(neon.fg('  Select a menu number from 0 to 14.', 'yellow'))


def run_dashboard(neon, open_browser=False, demo=False):
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}/'
    neon.startup(url,VAULT.dbpath)
    terminal_event('note','Dashboard is optional; all its searches stream into this terminal.')
    if demo:
        run_search('demo: public research',[],50,demo=True)
    if open_browser:
        # Browser opening is explicitly requested with --open-dashboard.
        threading.Timer(0.5,lambda:webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print('\n' + neon.fg('☣ Local dashboard closed.', 'purple'))
    finally:
        server.server_close()
    return 0


def main(argv=None):
    global VAULT, NEON
    parser=argparse.ArgumentParser(description='BLACKSWARM // terminal-first public link research')
    parser.add_argument('--color',choices=('auto','always','never'),default='auto',help='Terminal neon coloring')
    parser.add_argument('--color-test',action='store_true',help='Read-only rainbow color test')
    parser.add_argument('--examples',action='store_true',help='Show the terminal Example Desk and saved IDs; no browser')
    parser.add_argument('--constellation',type=int,metavar='ID',help='Show read-only terminal constellation for a saved session')
    parser.add_argument('--compare',nargs=2,type=int,metavar=('OLDER','NEWER'),help='Compare two saved sessions without networking')
    parser.add_argument('--navigate',type=int,metavar='ID',help='Interactive navigator for saved metadata; bookmarks are separate')
    parser.add_argument('--bookmarks',action='store_true',help='Open local bookmark shelf in terminal')
    parser.add_argument('--collections',action='store_true',help='Open private Intel Collections in terminal (no browser)')
    parser.add_argument('--vault-guard',action='store_true',help='Open private backup and verification menu; no browser or search')
    parser.add_argument('--demo',action='store_true',help='Print a demo in terminal, then exit; no browser')
    parser.add_argument('--cli',action='store_true',help='Run a one-off terminal search and exit')
    parser.add_argument('--dashboard',action='store_true',help='Start optional localhost dashboard without opening a browser')
    parser.add_argument('--open-dashboard',action='store_true',help='Explicitly request opening the dashboard in your browser')
    parser.add_argument('--no-browser',action='store_true',help='Legacy flag: browser is already off by default')
    parser.add_argument('--query',default='open source intelligence')
    parser.add_argument('--sources',default='wikipedia,crossref,gdelt,openlibrary,archive,europepmc',help='Comma-separated public indexes')
    parser.add_argument('--limit',type=int,default=100,choices=[50,100,250,500,1000])
    parser.add_argument('--searxng',default='',help='Optional public HTTPS instance')
    parser.add_argument('--quality',default='focused',choices=['focused','broad'],help='Filter weak matches (focused), or save all ranked matches (broad)')
    args=parser.parse_args(argv)
    neon=NEON=Neon(args.color)
    if args.color_test:
        neon.test()
        return 0
    if (args.constellation is not None or args.compare is not None or args.navigate is not None) and not (core.STORE/'results.sqlite3').is_file():
        print(neon.fg('  No saved BLACKSWARM v4 research vault found. No new vault created.', 'yellow'))
        return 0
    if args.vault_guard:
        try: guard.guard_desk(neon)
        except (KeyboardInterrupt, EOFError): print('\n'+neon.fg('  Vault Guard closed.', 'purple'))
        return 0
    if args.collections:
        # Direct offline collections mode does not even open the research vault.
        try: _terminal_collections(neon)
        except (KeyboardInterrupt, EOFError): print('\n'+neon.fg('  Collections closed.', 'purple'))
        return 0
    VAULT=core.Vault()
    if args.bookmarks:
        try: _terminal_bookmarks(neon)
        except (KeyboardInterrupt, EOFError): print('\n'+neon.fg('  Bookmark shelf closed.', 'purple'))
        return 0
    if args.examples:
        _terminal_examples(neon)
        return 0
    if args.constellation is not None:
        _terminal_constellation(neon,args.constellation)
        return 0
    if args.compare is not None:
        _terminal_delta(neon,*args.compare)
        return 0
    if args.navigate is not None:
        try:
            _terminal_navigator(neon,args.navigate)
        except (KeyboardInterrupt, EOFError):
            print('\n'+neon.fg('  Navigator closed.','purple'))
        return 0
    if args.cli or args.demo:
        neon.banner()
        sources=[x.strip() for x in args.sources.split(',') if x.strip()]
        rid=run_search(args.query,sources,args.limit,args.searxng,demo=args.demo,quality=args.quality)
        neon.summary(VAULT.run(rid),VAULT.dbpath,rid)
        return 0
    if args.dashboard or args.open_dashboard:
        return run_dashboard(neon,open_browser=args.open_dashboard)
    try:
        return terminal_menu(neon,args.limit)
    except (KeyboardInterrupt, EOFError):
        print('\n'+neon.fg('  ☣ BLACKSWARM closed.', 'purple'))
        return 0

if __name__=='__main__':
    sys.exit(main())
