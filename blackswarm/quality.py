"""BLACKSWARM SEARCH QUALITY LAB: read-only explanation of saved metadata scores.

Does not fetch webpages, change scores, write databases, open a browser, or
modify system settings. Uses the same rule constants as SMART SWARM.
"""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit
from . import core, intent
from .intel import safe_line


def _label(value, limit=160):
    return safe_line(str(value or ''), limit)


def explain_score(query, record):
    """Reproduce the currently installed ranking rules with per-term explanation.

    A saved score may differ if it came from a different version. Neither score
    is a credibility judgment or an assessment of actual webpage contents.
    """
    terms=core._terms(query)
    title=str(record.get('title',''))[:320].casefold()
    snippet=str(record.get('snippet',''))[:700].casefold()
    urlpath=urlsplit(str(record.get('url',''))).path.casefold()[:1000]
    title_words, snippet_words, path_words=core._terms(title),core._terms(snippet),core._terms(urlpath)
    terms_found=[]
    total=0
    for word in sorted(terms):
        if word in title_words:
            terms_found.append((word,'TITLE',21)); total+=21
        elif word in snippet_words:
            terms_found.append((word,'SNIPPET',8)); total+=8
        elif word in path_words:
            terms_found.append((word,'URL PATH',5)); total+=5
        else:
            terms_found.append((word,'NOT FOUND',0))
    matched=sum(points>0 for _,_,points in terms_found)
    two_bonus=10 if len(terms)>1 and matched>=2 else 0
    full_bonus=10 if len(terms)>1 and matched==len(terms) else 0
    phrase=' '.join(str(query).casefold().strip().split())
    phrase_bonus=16 if len(phrase)>8 and phrase in title else 0
    related=0
    if terms & {'hack','cybersecurity','security','pentest','infosec'}:
        related=sum(9 if word in title else 3 if word in snippet else 0 for word in core.CYBER_TERMS)
    related_bonus=min(related,18)
    total+=two_bonus+full_bonus+phrase_bonus+related_bonus
    score=min(100,total)
    threshold=30 if len(terms)<=1 else 40
    tier='high' if score>=threshold else 'possible' if score>=16 else 'low'
    return {'score':score,'relevance':tier,'terms':terms_found,
            'matched':matched,'term_count':len(terms),
            'two_bonus':two_bonus,'full_bonus':full_bonus,
            'phrase_bonus':phrase_bonus,'related_bonus':related_bonus,
            'raw_score':total,'threshold':threshold}


def build_report(session, selected, candidates):
    """Produce a read-only, stable indexed view of a stored candidate pool."""
    base=list(candidates or []) if candidates else list(selected or [])
    full=bool(candidates)
    selected_urls={core.clean_url(x.get('url','')) for x in (selected or [])}
    items=[]
    for i,row in enumerate(base,1):
        if not isinstance(row,dict):continue
        result={**row}
        result['lab_id']=i
        result['selected']=bool(row.get('selected',False)) if full else core.clean_url(row.get('url','')) in selected_urls
        result['saved_relevance']=str(row.get('relevance','unscored')).casefold()
        result['saved_score']=row.get('score')
        items.append(result)
    tally=Counter(row['saved_relevance'] for row in items)
    try:
        import json
        quality_mode = json.loads(session.get('stats','{}')).get('quality','focused')
    except (TypeError,ValueError,AttributeError):
        quality_mode = 'focused'
    return {'session_id':session.get('id','?'), 'quality_mode':quality_mode, 'mode':_label(session.get('mode','unknown'),22),
            'query':_label(session.get('query',''),180), 'query_raw':str(session.get('query','')), 'full_candidates':full,
            'items':items, 'selected':sum(bool(x['selected']) for x in items),
            'counts':tally}


def _explain_detail(neon, report, row):
    e=explain_score(report['query_raw'],row)
    saved_intent = report.get('quality_mode') == 'intent'
    intent_info = intent.score_intent(report['query_raw'],row) if saved_intent else None
    stored=row.get('saved_score')
    stored_label=row.get('saved_relevance','unscored')
    print('\n'+neon.fg('  ★ QUALITY EXPLANATION // STORED METADATA', 'purple',True))
    print(neon.fg('  CANDIDATE #', 'cyan')+str(row['lab_id'])+
          neon.fg('   SELECTED ', 'green')+('YES' if row['selected'] else 'NO'))
    print(neon.fg('  TITLE ', 'cyan')+_label(row.get('title'),180))
    print(neon.fg('  URL ', 'blue')+_label(row.get('url'),300))
    print(neon.fg('  SOURCES ', 'purple')+_label(', '.join(row.get('sources',[]) if isinstance(row.get('sources'),list) else []),160))
    print(neon.fg('  STORED SCORE ', 'green')+str(stored)+' / 100 ('+stored_label.upper()+')')
    print(neon.fg('  EXPLANATION BY CURRENT RULES ', 'cyan')+
          (f"{intent_info['score']} / 100 ({intent_info['relevance'].upper()}) [INTENT]" if saved_intent
           else f"{e['score']} / 100 ({e['relevance'].upper()})"))
    if stored!=(intent_info['score'] if saved_intent else e['score']) or stored_label!=(intent_info['relevance'] if saved_intent else e['relevance']):
        print(neon.fg('  NOTE: saved values differ from current rules or are missing; nothing was re-ranked.', 'yellow'))
    print(neon.fg('  QUERY TERM MATCHES ', 'purple')+f"{e['matched']}/{e['term_count']}")
    if not e['terms']:
        print(neon.fg('  No searchable query terms after common-word filtering.', 'yellow'))
    for term,position,points in e['terms']:
        tone='green' if points else 'yellow'
        print('  '+neon.fg(_label(term,28).ljust(30),tone)+_label(position,12).ljust(14)+f'+{points}')
    print(neon.fg('  BONUSES ', 'cyan')+
          f"2+ matches +{e['two_bonus']} | all terms +{e['full_bonus']} | "+
          f"exact title phrase +{e['phrase_bonus']} | cyber-topic hints +{e['related_bonus']}")
    if e['raw_score']>100:print(neon.fg('  Score capped at 100.', 'purple'))
    if saved_intent:
        print(neon.fg('  INTENT ADJUSTMENTS ', 'purple')+
              f"full coverage +{intent_info['all_bonus']} | missing terms -{intent_info['missing_penalty']} | no title matches -{intent_info['no_title_penalty']}")
    print(neon.fg('  HIGH threshold ', 'cyan')+str(intent_info['high_threshold'] if saved_intent else e['threshold'])+
          neon.fg('  | POSSIBLE threshold ', 'cyan')+str(intent_info['possible_threshold'] if saved_intent else 16))
    print(neon.fg('  Heuristic search relevance only. Not verified, endorsed, or live-checked.', 'yellow'))
    print(neon.fg('  No browser, network request, or database changes.', 'green'))


def _browse(neon, report, subset, input_fn):
    if not subset:
        print(neon.fg('  No matching saved candidates.', 'yellow'));return
    page=0; per_page=10
    while True:
        count=(len(subset)+per_page-1)//per_page
        print('\n'+neon.fg(f'  ✦ QUALITY LIST · {len(subset)} MATCHES · PAGE {page+1}/{count}', 'purple',True))
        for row in subset[page*per_page:(page+1)*per_page]:
            level=row['saved_relevance'].upper()
            color='green' if level=='HIGH' else 'cyan' if level=='POSSIBLE' else 'yellow'
            print(neon.fg(f"  [#{row['lab_id']}] ",color)+_label(row.get('title'),94))
            print(neon.fg('       ','purple')+f"{row.get('score','?')}/100 {level}  |  "+
                  ('SELECTED' if row['selected'] else 'NOT SELECTED')+
                  '  |  '+_label(row.get('url'),140))
        answer=input_fn(neon.fg('  n next | p previous | candidate # explain | b back: ', 'cyan')).strip().lower()
        if answer in ('b','0','q','quit',''):return
        if answer=='n':page=min(count-1,page+1);continue
        if answer=='p':page=max(0,page-1);continue
        try: idx=int(answer.lstrip('#'))
        except ValueError:
            print(neon.fg('  Use n, p, a displayed candidate number, or b.', 'yellow'));continue
        chosen=next((x for x in subset if x['lab_id']==idx),None)
        if chosen is None:
            print(neon.fg('  Choose a displayed candidate number from this result list.', 'yellow'));continue
        _explain_detail(neon,report,chosen)


def quality_desk(neon, session, selected, candidates, input_fn=None):
    """Explore a stored search offline. No persistence or side effects."""
    input_fn=input_fn or input
    report=build_report(session,selected,candidates)
    print('\n'+neon.fg('  ╔════════ BLACKSWARM // SEARCH QUALITY LAB ════════╗', 'purple',True))
    print(neon.fg('  ║  RANK REASONS · CANDIDATE REVIEW · NO RESCAN  ║', 'cyan'))
    print(neon.fg('  ╚════════════════════════════════════════════╝', 'purple'))
    print(neon.fg('  SESSION ', 'cyan')+str(report['session_id'])+'  '+neon.fg('QUERY ', 'purple')+report['query'])
    print(neon.fg('  SOURCE POOL ', 'purple')+('All stored candidates' if report['full_candidates'] else 'Saved results only (legacy session)'))
    print(neon.fg('  '+str(len(report['items']))+' CANDIDATES', 'green')+
          neon.fg('  | '+str(report['selected'])+' SELECTED', 'cyan'))
    if report['mode'].casefold()=='demo':
        print(neon.fg('  DEMO: illustrative URLs, not live research.', 'yellow'))
    counts=report['counts']
    for name,col in (('high','green'),('possible','cyan'),('low','yellow')):
        n=counts.get(name,0)
        blocks='█'*min(32,round(32*n/max(1,len(report['items'])))) if n else '·'
        print(neon.fg(f'  {name.upper():<10}',col)+neon.fg(blocks,col)+f'  {n}')
    while True:
        print('\n'+neon.fg('  ═════ QUALITY CONTROL ═════', 'purple',True))
        for num,col,name in (('1','green','VIEW HIGH RANKED LINKS'),
                             ('2','cyan','VIEW POSSIBLE MATCHES'),
                             ('3','yellow','VIEW LOW / EXCLUDED CANDIDATES'),
                             ('4','purple','QUICK FIND IN ALL CANDIDATES'),
                             ('5','pink','EXPLAIN BY CANDIDATE NUMBER'),
                             ('0','red','RETURN TO COMMAND DECK')):
            print(neon.fg(f'  [{num}] ',col)+name)
        answer=input_fn(neon.fg('  QUALITY ❯ ', 'green',True)).strip().lower()
        if answer in ('0','b','q','quit',''):
            print(neon.fg('  Quality Lab closed. Research vault unchanged.', 'green'));return
        if answer in ('1','2','3'):
            if answer=='3': matches=[x for x in report['items'] if x['saved_relevance']=='low' or not x['selected']]
            else:matches=[x for x in report['items'] if x['saved_relevance']==('high' if answer=='1' else 'possible')]
            _browse(neon,report,matches,input_fn)
        elif answer=='4':
            term=input_fn(neon.fg('  Find words in title, URL or snippet (Enter = cancel): ', 'cyan')).strip().casefold()[:120]
            if term:
                matches=[x for x in report['items'] if term in ' '.join(str(x.get(k,'')) for k in ('title','url','snippet')).casefold()]
                _browse(neon,report,matches,input_fn)
        elif answer=='5':
            raw=input_fn(neon.fg('  Candidate number (Enter = cancel): ', 'cyan')).strip()
            if not raw:continue
            try: number=int(raw.lstrip('#'))
            except ValueError:number=-1
            item=next((x for x in report['items'] if x['lab_id']==number),None)
            if item:_explain_detail(neon,report,item)
            else:print(neon.fg('  Candidate number not found. View a list to find numbers.', 'yellow'))
        else:
            print(neon.fg('  Choose 0–5.', 'yellow'))
