"""BLACKSWARM // CONSTELLATION NAVIGATOR.

Read-only terminal exploration of previously saved public search metadata.
Never fetches URLs, modifies the vault or opens a browser.
"""
from __future__ import annotations
from collections import Counter
from urllib.parse import urlsplit
import re

from .intel import NOISE, safe_line, chart_bar


def terms(title):
    return {word for word in re.findall(r"[a-z][a-z0-9-]{3,}", safe_line(title, 2000).casefold())
            if word not in NOISE and not word.isdigit()}


def index_rows(rows):
    """Return source/domain/topic counts and searchable lists from the selected rows."""
    sources, domains, topics = Counter(), Counter(), Counter()
    for row in rows:
        for source in set(str(x) for x in row.get('sources', []) if x):
            sources[source] += 1
        domain = (urlsplit(str(row.get('url',''))).hostname or '(unknown)').casefold()
        domains[domain] += 1
        topics.update(terms(row.get('title','')))
    return {'sources':sources.most_common(), 'domains':domains.most_common(),
            'topics':[(s,n) for s,n in topics.most_common() if n >= 2]}


def match_rows(rows, dimension, value):
    """Select from existing records only; query is NOT sent to any provider."""
    val = str(value).casefold().strip()
    if not val:
        return []
    if dimension == 'source':
        chosen = [r for r in rows if val in {str(x).casefold() for x in r.get('sources',[])}]
    elif dimension == 'domain':
        chosen = [r for r in rows if (urlsplit(str(r.get('url',''))).hostname or '').casefold() == val]
    elif dimension == 'topic':
        chosen = [r for r in rows if val in terms(r.get('title',''))]
    elif dimension == 'relevance':
        chosen = [r for r in rows if str(r.get('relevance','')).casefold() == val]
    elif dimension == 'text':
        chosen = [r for r in rows if val in ' '.join(str(r.get(k,'')) for k in ('title','url','snippet')).casefold()]
    else:
        raise ValueError('Unknown navigator filter')
    return sorted(chosen, key=lambda r:(-int(r.get('score',0)),str(r.get('title','')).casefold(),str(r.get('url',''))))


def choose(neon, label, options, input_fn=None, limit=12):
    """Pick a category by number. 0 or Enter returns without side effects."""
    if not options:
        print(neon.fg('  No matching categories in this session.', 'yellow'))
        return None
    input_fn = input_fn or input
    shown = options[:limit]
    print(neon.fg('  '+label.upper(), 'purple', True))
    for i,(value,n) in enumerate(shown, 1):
        print(neon.fg(f'  [{i:>2}] ', 'cyan')+safe_line(value,38).ljust(38)+neon.fg(str(n), 'green'))
    while True:
        selection = input_fn(neon.fg('  Pick number (0/Enter = back): ', 'yellow')).strip()
        if not selection or selection == '0':
            return None
        if selection.isdecimal() and 1 <= int(selection) <= len(shown):
            return shown[int(selection)-1][0]
        print(neon.fg('  Choose one of the numbers shown, or Enter to return.', 'yellow'))


def show_detail(neon, row, number=None):
    if number is not None:
        print(neon.fg(f'  LINK #{number} // SAVED METADATA', 'purple', True))
    else:
        print(neon.fg('  LINK DETAIL // SAVED METADATA', 'purple', True))
    print('  '+neon.fg('TITLE ', 'yellow')+safe_line(row.get('title'),240))
    print('  '+neon.fg('SOURCE ', 'blue')+safe_line(', '.join(row.get('sources',[])),120))
    print('  '+neon.fg('SCORE ', 'green')+str(row.get('score',0))+'  '+safe_line(row.get('relevance','unscored'),20).upper())
    snippet=safe_line(row.get('snippet'),350)
    if snippet: print('  '+neon.fg('TEXT ', 'pink')+snippet)
    print('  '+neon.fg('URL ', 'cyan')+safe_line(row.get('url'),800))
    print(neon.fg('  Metadata only. No website was opened.','yellow'))


def browse(neon, matched, label, input_fn=None, page_size=8, bookmark_factory=None, session_id=None, query=""):
    """Paged view of selected URLs. Exact URL selection prints detail, no browsing."""
    if not matched:
        print(neon.fg('  No saved links match this filter. Try another category.', 'yellow'))
        return
    input_fn = input_fn or input
    page = 0
    shelf = None  # never touch bookmark storage unless explicitly requested
    total = len(matched)
    while True:
        start = page * page_size
        ending = min(total,start+page_size)
        print('\n'+neon.fg('  ✦ SWARM LINK VIEW // '+safe_line(label,85),'purple',True))
        print(neon.fg(f'  {total} MATCHES  |  PAGE {page+1}/{(total+page_size-1)//page_size}  |  SAVED LINKS ONLY','green'))
        for index in range(start,ending):
            item=matched[index]
            color={'high':'green','possible':'yellow','low':'red'}.get(str(item.get('relevance','')).lower(),'cyan')
            flag = '★ ' if shelf is not None and shelf.by_url(item.get('url', '')) else ''
            print('    '+neon.fg(f'[{index+1:>3}] ', 'cyan') + neon.fg(flag, 'yellow')+
                  neon.fg(f"{safe_line(item.get('relevance','?'),8).upper():8} ",color)+
                  safe_line(item.get('title',''),85))
            print('          '+neon.fg(safe_line(item.get('url',''),180),'blue'))
        hint='n next | p previous | # details | f ★ star | b back: ' if bookmark_factory else 'n next | p previous | # details | b back: '
        command=input_fn(neon.fg('  '+hint,'yellow')).strip().lower()
        if command in ('','b','back','q','0'):
            return
        if command in ('n','next'):
            if ending < total: page+=1
            else: print(neon.fg('  Already on the last page.', 'yellow'))
        elif command in ('p','prev','previous'):
            if page: page-=1
            else: print(neon.fg('  Already on the first page.', 'yellow'))
        elif bookmark_factory is not None and (command == 'f' or re.fullmatch(r'f\s+[0-9]+', command)):
            # Both flows work: f 1 + Enter, or f + Enter then 1 + Enter.
            # Keep this separate from any terminal or desktop key bindings.
            if command == 'f':
                n=input_fn(neon.fg('  ★ Select displayed result number (Enter = cancel): ', 'cyan')).strip()
            else:
                n=command.split(None, 1)[1]
            if not n:
                print(neon.fg('  ★ Bookmark canceled. No changes made.', 'yellow'))
                continue
            if n.isdecimal() and start < int(n) <= ending and session_id is not None:
                shelf = shelf or bookmark_factory()
                # Show the choice first to avoid starring the wrong result.
                selected=matched[int(n)-1]
                print(neon.fg('  ★ SELECTED: ', 'yellow')+safe_line(selected.get('title',''),115))
                print('    '+neon.fg(safe_line(selected.get('url',''),180),'cyan'))
                note=input_fn(neon.fg('  Note (optional): press ENTER to skip, or type a note: ', 'cyan'))
                # People sometimes repeat 'f 1' here instead of writing a note.
                # Detect it once rather than silently saving an accidental command.
                if re.fullmatch(r'\s*f\s+\d+\s*',note,flags=re.I):
                    print(neon.fg('  That looks like a favorite command, not a note. Press Enter to skip.', 'yellow'))
                    note=input_fn(neon.fg('  Note (optional, Enter = none): ', 'cyan'))
                number,created=shelf.add(selected,session_id,query,note)
                if created:
                    print(neon.fg(f'  ★ SAVED to BOOKMARKED INTEL #{number} (separate bookmark database).', 'green'))
                else:
                    print(neon.fg(f'  ★ Already bookmarked as #{number}. Existing note was preserved.', 'yellow'))
            else:
                print(neon.fg('  Choose a number currently displayed on THIS page.', 'yellow'))
        elif command.isdecimal() and 1 <= int(command) <= total:
            show_detail(neon,matched[int(command)-1],int(command))
        else:
            print(neon.fg('  Enter n, p, a displayed result number, f (star), f #, or b.', 'yellow'))


def navigate(neon, run, rows, input_fn=None, bookmark_factory=None):
    """Interactive, terminal-only graph drilldown for one saved session."""
    input_fn = input_fn or input
    stats=index_rows(rows)
    neon.banner()
    print(neon.fg('  ✦ SWARM CONSTELLATION NAVIGATOR // RESEARCH READ-ONLY', 'purple',True))
    print(neon.fg(f"  SESSION #{run['id']}  ",'cyan')+safe_line(run.get('query',''),120))
    print(neon.fg(f'  {len(rows)} SAVED PUBLIC LINKS  |  NO NETWORK / NO BROWSER','green'))
    while True:
        print('\n'+neon.fg('  ═════ PICK A CONSTELLATION ═════','purple'))
        print(neon.fg('  [1] ','green')+'SOURCES  // Wikipedia, Crossref, Archive...')
        print(neon.fg('  [2] ','pink')+'TOPIC STARS  // keywords in saved titles')
        print(neon.fg('  [3] ','cyan')+'DOMAIN NEBULA  // group links by host')
        print(neon.fg('  [4] ','yellow')+'RELEVANCE  // high, possible, low')
        print(neon.fg('  [5] ','blue')+'QUICK FIND  // search local titles, URLs and snippets')
        print(neon.fg('  [0] ','red')+'RETURN TO COMMAND DECK')
        selection=input_fn(neon.fg('  CONSTELLATION ❯ ','green',True)).strip().lower()
        if selection in ('0','q','quit','exit',''):
            print(neon.fg('  ◈ Navigator closed; saved vault unchanged.','purple'))
            return
        options={'1':('source','DISCOVERY SOURCES',stats['sources']),
                 '2':('topic','TOPIC STARS',stats['topics']),
                 '3':('domain','DOMAIN NEBULA',stats['domains']),
                 '4':('relevance','RELEVANCE',[('high',sum(r.get('relevance')=='high' for r in rows)),
                       ('possible',sum(r.get('relevance')=='possible' for r in rows)),
                       ('low',sum(r.get('relevance')=='low' for r in rows))])}
        if selection in options:
            dimension,label,entries=options[selection]
            target=choose(neon,label,entries,input_fn)
            if target is not None:
                browse(neon,match_rows(rows,dimension,target),f'{label}: {target}',input_fn,bookmark_factory=bookmark_factory,session_id=run['id'],query=run['query'])
        elif selection=='5':
            term=input_fn(neon.fg('  Search SAVED titles/URLs/snippets (Enter = back): ','cyan')).strip()[:100]
            if term:
                browse(neon,match_rows(rows,'text',term),f'QUICK FIND: {term}',input_fn,bookmark_factory=bookmark_factory,session_id=run['id'],query=run['query'])
        else:
            print(neon.fg('  Choose a menu number from 0 through 5.','yellow'))
