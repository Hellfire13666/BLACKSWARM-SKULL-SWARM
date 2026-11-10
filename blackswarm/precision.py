"""BLACKSWARM // PRECISION LENS.

Optional title-first metadata ranking, with offline read-only saved-session preview.
No internet requests, webpage inspection, database mutation, or OS changes.
"""
from __future__ import annotations
from collections import Counter
from urllib.parse import urlsplit
from .core import _terms
from .intent import score_intent
from .intel import safe_line


def score_precision(query, record):
    """Return title-anchored ranking metrics using existing public metadata.

    Unlike the default ranking this deliberately *excludes* snippet-only and
    partially related records. It cannot determine factual validity or safety.
    """
    parent = score_intent(query, record)
    wanted = _terms(query)
    title = _terms(str(record.get('title',''))[:320])
    hits = len(wanted & title)
    covered = int(parent['found'])
    total = len(wanted)
    required_total = 0 if total == 0 else 1 if total == 1 else 2 if total <= 3 else (total * 2 + 2) // 3
    required_title = 0 if total == 0 else 1 if total <= 2 else 2
    anchored = total > 0 and covered >= required_total and hits >= required_title
    bonus = min(12, hits * 4) if anchored else 0
    # A record lacking sufficient query anchors is deliberately LOW in this
    # *optional* mode. Its original intent score is kept for audit.
    score = min(100, parent['score'] + bonus) if anchored else min(19, parent['score'])
    high = 50 if total >= 2 else 30
    label = 'high' if score >= high else 'possible' if score >= 20 else 'low'
    return dict(parent, score=score, relevance=label, title_hits=hits,
                matched=covered, total_terms=total,
                required_title=required_title, required_total=required_total,
                title_bonus=bonus, anchored=anchored, prior_intent=parent['score'])


def preview(session, selected, candidates):
    full = bool(candidates)
    rows = list(candidates) if candidates else list(selected)
    old_urls = {item.get('url') for item in selected}
    items=[]
    for index,row in enumerate(rows,1):
        if not isinstance(row,dict):continue
        insight=score_precision(session.get('query',''),row)
        was_selected=bool(row.get('selected')) if full else row.get('url') in old_urls
        items.append({**row,'candidate_id':index,'precision':insight,
                      'saved_selected':was_selected,'preview_selected':False})
    ranked=sorted(items,key=lambda x:-x['precision']['score'])
    try:
        cap=min(1000,max(0,int(session.get('requested') or len(selected))))
    except (TypeError,ValueError):cap=len(selected)
    eligible=[r for r in ranked if r['precision']['relevance']!='low']
    for row in eligible[:cap]:row['preview_selected']=True
    return {'items':items,'ranked':ranked,'old_selected':sum(x['saved_selected'] for x in items),
            'new_selected':sum(x['preview_selected'] for x in items),
            'newly_included':sum(x['preview_selected'] and not x['saved_selected'] for x in items),
            'would_exclude':sum(x['saved_selected'] and not x['preview_selected'] for x in items),
            'anchored':sum(x['precision']['anchored'] for x in items),
            'full_candidates':full,'counts':Counter(x['precision']['relevance'] for x in items)}


def detail(neon,row):
    x=row['precision']
    print('\n'+neon.fg('  ☣ PRECISION // TITLE ANCHOR EXPLANATION','purple',True))
    print(neon.fg('  CANDIDATE #','cyan')+str(row['candidate_id'])+'  '+safe_line(row.get('title',''),120))
    print(neon.fg('  URL ','blue')+safe_line(row.get('url',''),240))
    print(neon.fg('  STORED SCORE ','yellow')+f"{row.get('score','?')}/100 {str(row.get('relevance','?')).upper()}")
    print(neon.fg('  PRECISION PREVIEW ','green')+f"{x['score']}/100 {x['relevance'].upper()}")
    print(neon.fg('  QUERY COVERAGE ','cyan')+f"{x['matched']}/{x['total_terms']} (minimum {x['required_total']})")
    print(neon.fg('  TITLE MATCHES ','purple')+f"{x['title_hits']} (minimum {x['required_title']})")
    for word,where in x['locations'].items():
        print('  '+neon.fg(safe_line(word,28).ljust(28),'green' if where!='MISSING' else 'yellow')+where)
    print(neon.fg('  TITLE ANCHOR ','green' if x['anchored'] else 'yellow')+('PASS' if x['anchored'] else 'NOT MET'))
    print(neon.fg('  TITLE BONUS ','cyan')+f"+{x['title_bonus']}")
    print(neon.fg('  SAVED ','purple')+('YES' if row['saved_selected'] else 'NO')+
          '  |  '+neon.fg('PRECISION PREVIEW ','green')+('YES' if row['preview_selected'] else 'NO'))
    print(neon.fg('  Heuristic query match only; not page verification or credibility scoring.','yellow'))
    print(neon.fg('  PREVIEW ONLY. Saved sessions and scores unchanged.','green'))


def browse(neon,rows,input_fn):
    if not rows:
        print(neon.fg('  No matching stored candidates in this group.','yellow'))
        return
    size=9; pages=(len(rows)+size-1)//size;page=0
    while True:
        print('\n'+neon.fg(f'  ✦ PRECISION LIST · {len(rows)} RESULTS · PAGE {page+1}/{pages}','purple',True))
        for row in rows[page*size:(page+1)*size]:
            x=row['precision']
            print(neon.fg(f"  [#{row['candidate_id']}] ",'cyan')+safe_line(row.get('title',''),95))
            print(neon.fg('    ', 'purple')+f"{row.get('score','?')} → {x['score']}/100 {x['relevance'].upper()}"+
                  '  |  '+('TITLE ✓' if x['anchored'] else 'TITLE NO'))
        choice=input_fn(neon.fg('  n next | p previous | candidate # details | b back: ','cyan')).strip().lower()
        if choice in ('b','0','q','quit',''):return
        if choice=='n':page=min(pages-1,page+1)
        elif choice=='p':page=max(0,page-1)
        else:
            try:target=int(choice.lstrip('#'))
            except ValueError:
                print(neon.fg('  Enter n, p, a visible candidate number, or b.','yellow'));continue
            row=next((x for x in rows[page*size:(page+1)*size] if x['candidate_id']==target),None)
            if row:detail(neon,row)
            else:print(neon.fg('  Select a number shown on this page.','yellow'))


def precision_desk(neon,session,selected,candidates,input_fn=None):
    input_fn=input_fn or input
    d=preview(session,selected,candidates)
    print('\n'+neon.fg('  ╔════ BLACKSWARM // PRECISION LENS ════╗','purple',True))
    print(neon.fg('  ║  TITLE-FIRST RANKING · PREVIEW ONLY   ║','cyan'))
    print(neon.fg('  ╚════════════════════════════════════╝','purple'))
    print(neon.fg('  SESSION ','cyan')+str(session.get('id','?'))+
          '  '+neon.fg('QUERY ','purple')+safe_line(session.get('query',''),140))
    print(neon.fg(f"  {len(d['items'])} CANDIDATES",'green')+
          f"  | STORED {d['old_selected']}  | PRECISION {d['new_selected']}")
    print(neon.fg('  TITLE ANCHOR PASS ','cyan')+str(d['anchored'])+
          neon.fg('  | WOULD LEAVE ', 'yellow')+str(d['would_exclude']))
    print(neon.fg('  Read-only preview. No network, rescans or database changes.','green'))
    while True:
        print('\n'+neon.fg('  ═════ PRECISION CONTROL ═════','purple',True))
        for key,col,title in [('1','green','TOP TITLE-MATCHED RESULTS'),
                              ('2','yellow','WEAK / OFF-TOPIC CANDIDATES'),
                              ('3','cyan','SELECTION CHANGES'),
                              ('4','purple','EXPLAIN BY CANDIDATE NUMBER'),
                              ('0','red','BACK TO COMMAND DECK')]:
            print(neon.fg(f'  [{key}] ',col)+title)
        choice=input_fn(neon.fg('  PRECISION ❯ ','green',True)).strip().lower()
        if choice in ('0','q','quit','b',''):
            print(neon.fg('  Precision Lens closed. Existing vault unchanged.','green'));return
        if choice=='1':browse(neon,[r for r in d['ranked'] if r['precision']['anchored']][:100],input_fn)
        elif choice=='2':browse(neon,[r for r in d['ranked'] if not r['precision']['anchored']][:100],input_fn)
        elif choice=='3':browse(neon,[r for r in d['ranked'] if r['preview_selected']!=r['saved_selected']],input_fn)
        elif choice=='4':
            answer=input_fn(neon.fg('  Candidate number (Enter = cancel): ','cyan')).strip().lstrip('#')
            if answer.isdecimal() and 0<int(answer)<=len(d['items']):detail(neon,d['items'][int(answer)-1])
            elif answer:print(neon.fg('  Candidate number not found.','yellow'))
        else:print(neon.fg('  Choose a menu number from 0 to 4.','yellow'))
