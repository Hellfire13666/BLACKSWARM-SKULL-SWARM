"""BLACKSWARM v0.6.4 // CONCEPT BRIDGE.

Conservative *read-only* concept suggestions from stored public search metadata.
No network operations, model, web browsing, database changes, or OS alterations.

Not a synonym engine: the curated concept phrases below are bounded to an
explicit cybersecurity-intent query. A title match is required for a lift.
"""
from __future__ import annotations
from collections import Counter
import re
from .precision import score_precision
from .intel import safe_line

# Deliberately explicit domain phrases, not broad generic keywords like
# 'hack', 'hacks', 'attack', 'risk', 'software' or 'security' alone.
FAMILIES = (
    ('MALWARE RESEARCH', ('malware', 'ransomware', 'malicious software',
                         'malware classification', 'malware detection',
                         'botnet', 'trojan malware', 'malicious code')),
    ('VULNERABILITY RESEARCH', ('vulnerability', 'vulnerabilities', 'cve-',
                                'bug bounty', 'vulnerability disclosure',
                                'security flaw', 'zero day exploit',
                                'zero-day exploit', 'patch management')),
    ('DEFENSIVE OPERATIONS', ('intrusion detection', 'incident response',
                              'threat intelligence', 'threat hunting',
                              'digital forensics', 'security operations',
                              'intrusion prevention', 'phishing detection',
                              'endpoint detection')),
    ('SECURITY TESTING', ('penetration testing', 'pentesting',
                          'penetration test', 'ethical hacking',
                          'red team', 'blue team', 'white hat hacker',
                          'security assessment', 'web security testing')),
    ('SECURE SYSTEMS', ('information security', 'network security',
                        'application security', 'cloud security',
                        'cyber security', 'cybersecurity',
                        'software security', 'computer security',
                        'secure coding', 'zero trust', 'identity management')),
    ('CRYPTOGRAPHY', ('cryptography', 'cryptographic protocol',
                      'encryption algorithm', 'secure encryption',
                      'public key infrastructure')),
)
# Only explicit cybersecurity-intent searches enable this specialist bridge.
TRIGGERS = ('cybersecurity', 'cyber security', 'cyber-security',
            'information security', 'computer security', 'network security',
            'infosec', 'cyber defense', 'cyber defence',
            'ethical hacking', 'penetration testing', 'pentesting')
ETHICAL_FOCUS = ('ethical hacking', 'penetration testing', 'pentesting',
                 'pen testing', 'white hat', 'red team')


def phrase_found(text, phrase):
    """Require phrase boundaries. Match hyphen/space variants transparently."""
    normalized = str(text).casefold()[:2000]
    pieces = [re.escape(x) for x in re.split(r'[-\s]+', phrase) if x]
    if not pieces: return False
    pat = r'(?<![a-z0-9])' + r'[-\s]+'.join(pieces) + r'(?![a-z0-9])'
    return re.search(pat, normalized) is not None


def query_supported(query):
    return any(phrase_found(query, trigger) for trigger in TRIGGERS)


def family_matches(title):
    matches = []
    for name, phrases in FAMILIES:
        for p in phrases:
            if phrase_found(title, p):
                matches.append((name, p))
                break
    return matches


def score_concept(query, record):
    """Return transparent suggestions; never replace stored scores.

    Exact title anchors retain the current Precision score. In a cybersecurity
    query, specific *title* concept phrases may lift unanchored material to a
    modest POSSIBLE (20–35), never HIGH. Extra ethical-testing constraints stop
    the generic cybersecurity family from overriding explicit query intent.
    """
    parent = score_precision(query, record)
    title = str(record.get('title', ''))[:320]
    snippet = str(record.get('snippet', ''))[:700]
    supported = query_supported(query)
    matches = family_matches(title) if supported else []
    focused = any(phrase_found(query, x) for x in ETHICAL_FOCUS)
    # Long queries containing 'ethical' and 'hacking' separately count too.
    focused = focused or (phrase_found(query, 'ethical') and phrase_found(query, 'hacking'))
    specific_testing = any(name == 'SECURITY TESTING' for name, _ in matches)
    explicit_focus = (phrase_found(title, 'ethical') or phrase_found(snippet, 'ethical')
                      or phrase_found(title, 'penetration') or phrase_found(snippet, 'penetration'))
    eligible = (supported and bool(matches) and not parent['anchored']
                and (not focused or specific_testing or explicit_focus))
    # No title-based evidence => no bonus, even when the snippet says cyber.
    proposed = min(35, 26 + max(0,len(matches)-1)*4) if eligible else parent['score']
    score = max(parent['score'],proposed) if eligible else parent['score']
    tier = 'high' if score >= 40 else 'possible' if score >= 20 else 'low'
    return {
        'score': score, 'relevance': tier, 'precision_score': parent['score'],
        'precision_relevance': parent['relevance'], 'title_anchored': parent['anchored'],
        'query_supported': supported, 'ethics_focus': focused,
        'matches': matches, 'eligible': eligible,
        'lift': score - parent['score'],
        'reason': ('RELATED TOPIC IN TITLE' if eligible else
                   'QUERY OUTSIDE CYBER TOPIC' if not supported else
                   'EXACT TITLE ANCHOR ALREADY MET' if parent['anchored'] else
                   'ETHICAL-TESTING QUERY CONSTRAINT' if focused and matches else
                   'NO CURATED TITLE CONCEPT MATCH')
    }


def preview(session, selected, candidates):
    """Compute a hypothetical new selection in memory; no DB writes."""
    full = bool(candidates)
    rows = list(candidates) if candidates else list(selected)
    selected_urls = {r.get('url') for r in selected}
    items = []
    for i, row in enumerate(rows,1):
        if not isinstance(row,dict): continue
        x = score_concept(session.get('query',''),row)
        was = bool(row.get('selected')) if full else row.get('url') in selected_urls
        items.append({**row, 'candidate_id':i, 'concept':x,
                      'saved_selected':was, 'preview_selected':False})
    # Preserve candidate IDs even after the in-memory ranking.
    ranked = sorted(items,key=lambda r:-r['concept']['score'])
    try: cap=min(1000,max(0,int(session.get('requested') or len(selected))))
    except (TypeError,ValueError): cap=len(selected)
    for row in [r for r in ranked if r['concept']['relevance']!='low'][:cap]:
        row['preview_selected']=True
    return {
        'items':items,'ranked':ranked,'has_full_pool':full,
        'related':sum(r['concept']['eligible'] for r in items),
        'old_selected':sum(r['saved_selected'] for r in items),
        'preview_selected':sum(r['preview_selected'] for r in items),
        'would_enter':sum(r['preview_selected'] and not r['saved_selected'] for r in items),
        'would_leave':sum(r['saved_selected'] and not r['preview_selected'] for r in items),
        'tiers':Counter(r['concept']['relevance'] for r in items),
    }


def detail(neon,row):
    x=row['concept']
    print('\n'+neon.fg('  ☣ CONCEPT BRIDGE // EXPLANATION FROM STORED METADATA','purple',True))
    print(neon.fg('  CANDIDATE #','cyan')+str(row['candidate_id'])+'  '+safe_line(row.get('title',''),125))
    print(neon.fg('  URL ','blue')+safe_line(row.get('url',''),240))
    print(neon.fg('  ORIGINAL STORED ','yellow')+f"{row.get('score','?')}/100 {str(row.get('relevance','?')).upper()}")
    print(neon.fg('  PRECISION BASE ','pink')+f"{x['precision_score']}/100 {x['precision_relevance'].upper()}")
    print(neon.fg('  CONCEPT PREVIEW ','green')+f"{x['score']}/100 {x['relevance'].upper()}")
    print(neon.fg('  CONCEPT REASON ','cyan')+x['reason'])
    print(neon.fg('  MATCHED TITLE CONCEPTS ','purple')+str(len(x['matches'])))
    for name,phrase in x['matches']:
        print('  '+neon.fg(safe_line(name,24).ljust(26),'green')+neon.fg('TITLE: '+safe_line(phrase,50),'cyan'))
    print(neon.fg('  CONSERVATIVE LIFT ','yellow')+f"+{x['lift']} (concept-only results never boosted into HIGH)")
    print(neon.fg('  STORED SELECTED ','pink')+('YES' if row['saved_selected'] else 'NO')+
          neon.fg(' | PREVIEW SELECTED ','green')+('YES' if row['preview_selected'] else 'NO'))
    print(neon.fg('  Curated topical phrases, not synonym truth or a credibility check.','yellow'))
    print(neon.fg('  PREVIEW ONLY. No search, browser, score or database changes.','green'))


def browse(neon,rows,input_fn):
    if not rows:
        print(neon.fg('  No items in this preview group.','yellow'));return
    page=0;size=9;pages=(len(rows)+size-1)//size
    while True:
        print('\n'+neon.fg(f'  ✦ CONCEPT LIST · {len(rows)} RESULTS · PAGE {page+1}/{pages}','purple',True))
        for row in rows[page*size:(page+1)*size]:
            x=row['concept']
            title=safe_line(row.get('title',''),100)
            print(neon.fg(f"  [#{row['candidate_id']}] ",'cyan')+title)
            marker=('RELATED TITLE' if x['eligible'] else 'UNCHANGED')
            print('    '+neon.fg(str(row.get('score','?'))+' → '+str(x['score'])+'/100', 'pink')+
                  '  '+neon.fg(x['relevance'].upper(),'green' if x['eligible'] else 'yellow')+
                  '  | '+marker)
        choice=input_fn(neon.fg('  n next | p previous | candidate # details | b back: ','cyan')).strip().lower()
        if choice in ('b','0','q','quit',''):return
        if choice=='n':page=min(pages-1,page+1)
        elif choice=='p':page=max(0,page-1)
        else:
            try:n=int(choice.lstrip('#'))
            except ValueError:
                print(neon.fg('  Enter n, p, a displayed candidate number, or b.','yellow'));continue
            row=next((r for r in rows[page*size:(page+1)*size] if r['candidate_id']==n),None)
            if row:detail(neon,row)
            else:print(neon.fg('  Select a number shown on this page.','yellow'))


def concept_desk(neon,session,selected,candidates,input_fn=None):
    input_fn=input_fn or input
    data=preview(session,selected,candidates)
    print('\n'+neon.fg('  ╔═══════ BLACKSWARM // CONCEPT BRIDGE ═══════╗','purple',True))
    print(neon.fg('  ║  RELATED TOPICS · TITLE EVIDENCE · NO RESCAN ║','cyan'))
    print(neon.fg('  ╚════════════════════════════════════════════╝','purple'))
    print(neon.fg('  SESSION ','cyan')+str(session.get('id','?'))+
          neon.fg('  QUERY ','pink')+safe_line(session.get('query',''),135))
    print(neon.fg(f"  {len(data['items'])} CANDIDATES",'green')+
          neon.fg(f"  | RELATED TITLE MATCHES {data['related']}",'purple'))
    print(neon.fg('  SAVED ','pink')+str(data['old_selected'])+
          neon.fg('  | PREVIEW ','green')+str(data['preview_selected'])+
          neon.fg('  | WOULD ENTER ','cyan')+str(data['would_enter'])+
          neon.fg('  | WOULD LEAVE ','yellow')+str(data['would_leave']))
    if not query_supported(session.get('query','')):
        print(neon.fg('  Cybersecurity concept bridge not enabled for this query; preview is unchanged.','yellow'))
    print(neon.fg('  Preview only. No stored records, scores, or results changed.','green'))
    while True:
        print('\n'+neon.fg('  ═════ CONCEPT CONTROL ═════','purple',True))
        for number,color,label in [('1','green','RELATED TOPIC MATCHES'),
                                   ('2','yellow','STILL WEAK / NO TITLE CONCEPT'),
                                   ('3','cyan','SELECTION CHANGES PREVIEW'),
                                   ('4','purple','EXPLAIN BY CANDIDATE NUMBER'),
                                   ('0','red','RETURN TO COMMAND DECK')]:
            print(neon.fg(f'  [{number}] ',color)+label)
        choice=input_fn(neon.fg('  CONCEPT ❯ ','green',True)).strip().lower()
        if choice in ('0','q','quit','b',''):
            print(neon.fg('  Concept Bridge closed. Research vault unchanged.','green'));return
        if choice=='1':browse(neon,[r for r in data['ranked'] if r['concept']['eligible']],input_fn)
        elif choice=='2':browse(neon,[r for r in data['ranked'] if r['concept']['relevance']=='low' and not r['concept']['eligible']][:100],input_fn)
        elif choice=='3':browse(neon,[r for r in data['ranked'] if r['preview_selected']!=r['saved_selected']],input_fn)
        elif choice=='4':
            answer=input_fn(neon.fg('  Candidate number (Enter = cancel): ','cyan')).strip().lstrip('#')
            if answer.isdecimal() and 0<int(answer)<=len(data['items']):detail(neon,data['items'][int(answer)-1])
            elif answer:print(neon.fg('  Candidate number not found.','yellow'))
        else:print(neon.fg('  Choose a number from 0 through 4.','yellow'))
