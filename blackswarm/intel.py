"""BLACKSWARM SWARM CONSTELLATION: offline analytics for saved public URLs.

Never fetches webpages or tests hosts. Uses only existing local metadata.
This module is read-only: no vault writes or file outputs.
"""
from collections import Counter, defaultdict
from urllib.parse import urlsplit
import re

NOISE = set("""the and of for from with into under over between using use new study review
research analysis impact role based introduction overview practical complete guide
system systems article articles chapter volume edition part books book report
public open access by a an
in to on at is are not how why what it its this these our your their as
and or via of no using assessing towards case cases results future current
technologies data digital applications methods methodology perspectives issues
approach approaches review literature project study conference journal""".split())


def safe_line(value, limit=110):
    """Prevent copied metadata from printing terminal control sequences."""
    raw = str(value or '')
    raw = re.sub(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]', ' ', raw)
    return ' '.join(raw.split())[:limit]


def chart_bar(number, maximum, width=22):
    if number <= 0 or maximum <= 0:
        return '░' * width
    filled = max(1, round(width * number / maximum))
    return '█' * filled + '░' * (width - filled)


def make_constellation(run, rows, candidates=None):
    """Summarize sources, URL domains, title terms and observed link overlaps."""
    rows=list(rows)
    by_source=Counter()
    by_domain=Counter()
    origin_overlap=0
    domain_sources=defaultdict(set)
    term_counts=Counter()
    term_to_results=defaultdict(list)
    for row in rows:
        url=row.get('url','')
        host=(urlsplit(url).hostname or '(unknown)').casefold()
        sources=[safe_line(s,60) for s in row.get('sources',[]) if s]
        by_domain[host]+=1
        for source in set(sources):
            by_source[source]+=1
            domain_sources[host].add(source)
        if len(set(sources))>1:
            origin_overlap+=1
        title=safe_line(row.get('title',''),320).casefold()
        words={word for word in re.findall(r'[a-z][a-z0-9-]{3,}',title)
               if word not in NOISE and not word.isdigit()}
        # Avoid title-only topic noise from urls, unrelated proper names etc.
        for word in words:
            term_counts[word]+=1
            if len(term_to_results[word])<3:
                term_to_results[word].append(row)
    rank=sorted(term_counts.items(),key=lambda x:(-x[1],x[0]))
    rank=[(k,v) for k,v in rank if v>=2][:9]
    stars=[]
    for term,count in rank:
        stars.append({'topic':term,'count':count,
                      'examples':[{'title':safe_line(r.get('title',''),85),
                                   'url':r.get('url','')} for r in term_to_results[term][:2]]})
    scores=Counter(r.get('relevance','unscored') for r in rows)
    candidates=list(candidates or [])
    return {'session_id':run['id'],'query':safe_line(run['query'],140),
            'stamp':run['stamp'],'total':len(rows),'sources':by_source.most_common(9),
            'domains':by_domain.most_common(9),'multi_source':origin_overlap,
            'topic_signals':stars,'levels':scores,
            'candidate_count':len(candidates),
            'unselected_count':sum(1 for r in candidates if not r.get('selected')),
            'domain_source_counts':[(h,len(domain_sources[h])) for h,_ in by_domain.most_common(9)]}


def compare_sessions(older_run, older_rows, newer_run, newer_rows, limit=12):
    """Observe set differences, not proof a URL was published/removed online."""
    if older_run['id']==newer_run['id']:
        raise ValueError('Choose two different session IDs')
    before={r['url']:r for r in older_rows}
    after={r['url']:r for r in newer_rows}
    added=[after[url] for url in sorted(after.keys()-before.keys())]
    absent=[before[url] for url in sorted(before.keys()-after.keys())]
    return {'older_id':older_run['id'],'newer_id':newer_run['id'],
            'older_query':safe_line(older_run['query'],120),
            'newer_query':safe_line(newer_run['query'],120),
            'older_total':len(before),'newer_total':len(after),
            'added_count':len(added),'absent_count':len(absent),
            'common_count':len(before.keys()&after.keys()),
            'added':added[:limit],'absent':absent[:limit]}


def show_constellation(neon, summary):
    neon.banner()
    print(neon.fg('  ✦ SWARM CONSTELLATION // READ-ONLY SIGNAL MAP', 'purple',True))
    print(neon.fg('  SESSION ', 'cyan')+f"#{summary['session_id']}  " +
          neon.fg('QUERY ', 'yellow')+summary['query'])
    print(neon.fg('  LINKS   ', 'green')+f"{summary['total']} saved public URLs")
    print(neon.fg('  DISCOVERY SOURCES', 'pink',True))
    top=max([v for _,v in summary['sources']] or [1])
    for label,n in summary['sources']:
        print('    '+neon.fg(f'{safe_line(label,19):19s}', 'cyan')+
              neon.fg(chart_bar(n,top), 'green')+f' {n}')
    print(neon.fg('  DOMAIN NEBULA', 'purple',True))
    top=max([v for _,v in summary['domains']] or [1])
    for label,n in summary['domains']:
        print('    '+neon.fg(f'{safe_line(label,31):31s}', 'blue')+
              neon.fg(chart_bar(n,top,15), 'pink')+f' {n}')
    print(neon.fg('  LINK DNA', 'pink',True))
    print('    '+neon.fg(str(summary['multi_source']), 'green',True)+' URLs appeared in multiple source indexes')
    for k in ('high','possible','low'):
        print('    '+neon.fg(f'{k.upper():10s}', {'high':'green','possible':'yellow','low':'red'}[k])+str(summary['levels'].get(k,0)))
    if summary['candidate_count']:
        print('    '+neon.fg('CANDIDATES ', 'cyan')+str(summary['candidate_count'])+
              neon.fg('   UNSELECTED ', 'yellow')+str(summary['unselected_count']))
    print(neon.fg('  TOPIC STARS // WORDS IN SAVED TITLES', 'purple',True))
    if summary['topic_signals']:
        for item in summary['topic_signals']:
            print('    '+neon.fg(f"✦ {safe_line(item['topic'],22):22s}", 'pink')+
                  neon.fg(chart_bar(item['count'],summary['topic_signals'][0]['count'],12),'cyan')+
                  f" {item['count']} titles")
        print(neon.fg('  TOPIC HIGHLIGHTS // TWO EXAMPLE LINKS', 'purple',True))
        for item in summary['topic_signals'][:2]:
            print('    '+neon.fg(item['topic'].upper(), 'green',True))
            for ex in item['examples']:
                print('      '+safe_line(ex['title'],80))
                print('      '+neon.fg(safe_line(ex['url'],180), 'cyan'))
    else:
        print(neon.fg('    No title keyword clusters yet for this session.', 'yellow'))
    print(neon.fg('  Note: topics are repeated title words, not verified facts or webpage scans.', 'yellow'))
    print(neon.fg('  All counts come from saved vault metadata; nothing fetched or modified.\n','green'))


def show_delta(neon, changes):
    neon.banner()
    print(neon.fg('  ◈ SWARM DELTA // SAVED SEARCH COMPARISON','purple',True))
    print(neon.fg(f"  OLDER #{changes['older_id']} ", 'blue')+
          f"{changes['older_total']} links  {changes['older_query']}")
    print(neon.fg(f"  NEWER #{changes['newer_id']} ", 'cyan')+
          f"{changes['newer_total']} links  {changes['newer_query']}")
    print('  '+neon.fg(f" + {changes['added_count']:>5} ", 'green',True)+
          'only in newer  '+neon.fg(f" - {changes['absent_count']:>5} ", 'pink',True)+
          'only in older  '+neon.fg(f" = {changes['common_count']:>5} ", 'purple',True)+'shared')
    for heading,rows,color in [('ONLY IN NEWER',changes['added'],'green'),('ONLY IN OLDER',changes['absent'],'pink')]:
        print(neon.fg('  '+heading,'purple',True))
        if not rows: print(neon.fg('    (none)', 'yellow'))
        for row in rows:
            print('    '+neon.fg('✦ ',color)+safe_line(row.get('title',''),94))
            print('      '+neon.fg(safe_line(row.get('url',''),180),'cyan'))
    print(neon.fg('  Differences describe SAVED search sets, not content removed from the web.', 'yellow'))
    print(neon.fg('  No background monitoring, host scans, or browser windows.\n', 'green'))
