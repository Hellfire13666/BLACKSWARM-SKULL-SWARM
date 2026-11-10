"""BLACKSWARM v0.6.0 // SMART INTENT.

Optional whole-query metadata ranking for future searches, plus read-only previews
of historical candidate pools. No network clients, filesystem writes or browser.
"""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit

from . import core
from .intel import safe_line


def score_intent(query, record):
    """Score matched query-term *coverage* without judging a page's truth/safety.

    The legacy base remains byte-for-byte compatible. Multiword searches can
    reward full coverage and down-weight partial/metadata-only matches.
    """
    base_score, base_tier = core.score_record(query, record)
    terms = core._terms(query)
    title = core._terms(str(record.get('title', ''))[:320])
    snippet = core._terms(str(record.get('snippet', ''))[:700])
    path = core._terms(urlsplit(str(record.get('url', ''))).path[:1000])
    locations = {}
    for term in sorted(terms):
        if term in title:
            locations[term] = 'TITLE'
        elif term in snippet:
            locations[term] = 'SNIPPET'
        elif term in path:
            locations[term] = 'URL PATH'
        else:
            locations[term] = 'MISSING'
    found = sum(place != 'MISSING' for place in locations.values())
    title_hits = sum(place == 'TITLE' for place in locations.values())
    missing = len(terms) - found
    # With one term, do not change long-standing ranking decisions.
    all_terms_bonus = 12 if len(terms) >= 2 and missing == 0 else 0
    missing_penalty = min(24, 4 + 8 * missing) if len(terms) >= 2 and missing else 0
    no_title_penalty = 8 if len(terms) >= 2 and found and title_hits == 0 else 0
    adjusted = max(0, min(100, base_score + all_terms_bonus - missing_penalty - no_title_penalty))
    high_threshold = 50 if len(terms) >= 2 else 30
    possible_threshold = 20 if len(terms) >= 2 else 16
    tier = 'high' if adjusted >= high_threshold else 'possible' if adjusted >= possible_threshold else 'low'
    return {
        'score': adjusted, 'relevance': tier, 'legacy_score': base_score,
        'legacy_relevance': base_tier, 'locations': locations, 'found': found,
        'total_terms': len(terms), 'title_hits': title_hits, 'missing': missing,
        'all_bonus': all_terms_bonus, 'missing_penalty': missing_penalty,
        'no_title_penalty': no_title_penalty,
        'high_threshold': high_threshold, 'possible_threshold': possible_threshold,
    }


def preview(session, selected, candidates):
    """Compare old saved selection against hypothetical new selection in memory."""
    base = list(candidates or []) if candidates else list(selected or [])
    full_candidates = bool(candidates)
    selected_urls = {r.get('url') for r in selected or []}
    items = []
    for idx, item in enumerate(base, 1):
        if not isinstance(item, dict):
            continue
        info = score_intent(str(session.get('query', '')), item)
        saved = bool(item.get('selected', False)) if full_candidates else item.get('url') in selected_urls
        items.append({**item, 'candidate_id': idx, 'saved_selected': saved,
                      'intent': info, 'preview_selected': False})
    # Keep provider order as a deterministic tiebreaker.
    ranked = sorted(items, key=lambda r: -r['intent']['score'])
    try:
        cap = min(1000, max(0, int(session.get('requested') or len(selected or []))))
    except (ValueError, TypeError):
        cap = len(selected or [])
    eligible = [row for row in ranked if row['intent']['relevance'] != 'low']
    for row in eligible[:cap]:
        row['preview_selected'] = True
    old_count = sum(row['saved_selected'] for row in items)
    new_count = sum(row['preview_selected'] for row in items)
    return {
        'session': session, 'items': items, 'ranked': ranked,
        'full_candidates': full_candidates,
        'old_selected': old_count, 'preview_selected': new_count,
        'newly_included': sum(row['preview_selected'] and not row['saved_selected'] for row in items),
        'would_exclude': sum(row['saved_selected'] and not row['preview_selected'] for row in items),
        'counts': Counter(row['intent']['relevance'] for row in items),
    }


def _show_detail(neon, row):
    x = row['intent']
    print('\n' + neon.fg('  ★ SMART INTENT // SIDE-BY-SIDE EXPLANATION', 'purple', True))
    print(neon.fg('  CANDIDATE #', 'cyan') + str(row['candidate_id']) + '  ' + safe_line(row.get('title',''), 125))
    print(neon.fg('  URL ', 'blue') + safe_line(row.get('url',''), 240))
    print(neon.fg('  ORIGINAL SAVED ', 'cyan') + str(row.get('score', '?')) + '/100 ' + str(row.get('relevance', '?')).upper())
    print(neon.fg('  INTENT PREVIEW ', 'green') + f"{x['score']}/100 {x['relevance'].upper()}")
    print(neon.fg('  QUERY COVERAGE ', 'purple') + f"{x['found']}/{x['total_terms']} terms; {x['title_hits']} in title")
    for term, place in x['locations'].items():
        print('  ' + neon.fg(safe_line(term,28).ljust(29), 'green' if place != 'MISSING' else 'yellow') + place)
    print(neon.fg('  WHOLE QUERY BONUS ', 'green') + f"+{x['all_bonus']}")
    print(neon.fg('  MISSING TERM PENALTY ', 'yellow') + f"-{x['missing_penalty']}")
    print(neon.fg('  NO TITLE MATCH PENALTY ', 'yellow') + f"-{x['no_title_penalty']}")
    print(neon.fg('  SAVED SELECTION ', 'cyan') + ('YES' if row['saved_selected'] else 'NO') +
          neon.fg('  | PREVIEW SELECTION ', 'purple') + ('YES' if row['preview_selected'] else 'NO'))
    if x['legacy_score'] != row.get('score'):
        print(neon.fg('  NOTE: prior stored score differs from recalculated legacy rules.', 'yellow'))
    print(neon.fg('  Metadata heuristic only. Not a factual, safety or credibility check.', 'yellow'))
    print(neon.fg('  PREVIEW ONLY. Saved session, links and scores unchanged.', 'green'))


def _list(neon, data, rows, input_fn):
    if not rows:
        print(neon.fg('  No items in this preview group.', 'yellow'))
        return
    page = 0
    size = 9
    pages = (len(rows) + size - 1) // size
    while True:
        print('\n' + neon.fg(f'  ✦ INTENT LIST · {len(rows)} RESULTS · PAGE {page+1}/{pages}', 'purple', True))
        for row in rows[page*size:(page+1)*size]:
            info = row['intent']
            print(neon.fg(f"  [#{row['candidate_id']}] ", 'cyan') + safe_line(row.get('title',''), 96))
            print(neon.fg('     ', 'purple') + f"{row.get('score','?')} → {info['score']}/100 {info['relevance'].upper()}" +
                  '  |  ' + ('PREVIEW ✓' if row['preview_selected'] else 'PREVIEW NO'))
        answer = input_fn(neon.fg('  n next | p previous | candidate # details | b back: ', 'cyan')).strip().lower()
        if answer in ('b','0','q','quit',''):
            return
        if answer == 'n':
            page = min(pages-1,page+1)
        elif answer == 'p':
            page = max(0,page-1)
        else:
            try:
                candidate_id = int(answer.lstrip('#'))
            except ValueError:
                print(neon.fg('  Enter n, p, a displayed candidate number, or b.', 'yellow'))
                continue
            row = next((r for r in rows[page*size:(page+1)*size] if r['candidate_id'] == candidate_id), None)
            if row is None:
                print(neon.fg('  Select a candidate number visible on this page.', 'yellow'))
            else:
                _show_detail(neon,row)


def intent_desk(neon, session, selected, candidates, input_fn=None):
    """Read-only intent comparison over a saved session; no network or disk write."""
    input_fn = input_fn or input
    data = preview(session, selected, candidates)
    print('\n' + neon.fg('  ╔════ BLACKSWARM // SMART INTENT LENS ════╗', 'purple', True))
    print(neon.fg('  ║ WHOLE-QUERY RANKING · PREVIEW · NO RESCAN ║', 'cyan'))
    print(neon.fg('  ╚═══════════════════════════════════════╝', 'purple'))
    print(neon.fg('  SESSION ', 'cyan') + str(session.get('id','?')) + '  ' + neon.fg('QUERY ', 'purple') + safe_line(session.get('query',''),140))
    print(neon.fg('  SOURCE ', 'purple') + ('All stored candidates' if data['full_candidates'] else 'Saved links only (legacy session)'))
    print(neon.fg('  '+str(len(data['items']))+' CANDIDATES', 'green') +
          f"  | SAVED {data['old_selected']}  | PREVIEW {data['preview_selected']}")
    print(neon.fg('  SELECTION CHANGES ', 'cyan') +
          f"{data['newly_included']} WOULD ENTER  |  {data['would_exclude']} WOULD LEAVE")
    for label,col in (('high','green'),('possible','cyan'),('low','yellow')):
        n = data['counts'].get(label, 0)
        blocks = '█'*min(32,round(32*n/max(1,len(data['items'])))) if n else '·'
        print(neon.fg(f'  {label.upper():<10}',col) + neon.fg(blocks,col) + '  '+str(n))
    print(neon.fg('  No research changed. Nothing was re-ranked or resaved.', 'yellow'))
    while True:
        print('\n'+neon.fg('  ═════ INTENT CONTROL ═════','purple',True))
        for num,col,title in (('1','green','PREVIEW TOP RE-RANKED LINKS'),
                              ('2','cyan','SHOW LINKS WITH CHANGED TIERS'),
                              ('3','yellow','SHOW CHANGED SELECTIONS'),
                              ('4','purple','EXPLAIN BY CANDIDATE NUMBER'),
                              ('0','red','BACK TO COMMAND DECK')):
            print(neon.fg(f'  [{num}] ',col)+title)
        answer = input_fn(neon.fg('  INTENT ❯ ','green',True)).strip().lower()
        if answer in ('0','b','q','quit',''):
            print(neon.fg('  Intent Lens closed. Original session preserved.', 'green'))
            return
        if answer == '1':
            _list(neon,data,data['ranked'][:min(100,len(data['ranked']))],input_fn)
        elif answer == '2':
            _list(neon,data,[r for r in data['ranked'] if r.get('relevance') != r['intent']['relevance']],input_fn)
        elif answer == '3':
            _list(neon,data,[r for r in data['ranked'] if r['saved_selected'] != r['preview_selected']],input_fn)
        elif answer == '4':
            v = input_fn(neon.fg('  Candidate number (Enter = cancel): ', 'cyan')).strip()
            if not v:
                continue
            try:
                num = int(v.lstrip('#'))
            except ValueError:
                num = -1
            row = next((r for r in data['items'] if r['candidate_id'] == num),None)
            if row:
                _show_detail(neon,row)
            else:
                print(neon.fg('  Candidate number not found. See [1] or [2] for IDs.', 'yellow'))
        else:
            print(neon.fg('  Choose a number from 0 through 4.', 'yellow'))
