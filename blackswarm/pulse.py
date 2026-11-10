"""BLACKSWARM SOURCE PULSE: offline, read-only quality and provenance report.

Uses persisted provider reports and saved result/candidate metadata only.
No network, file writing, browser, or OS configuration operations.
"""
from __future__ import annotations

import json
from collections import defaultdict
from .core import clean_url
from .intel import safe_line

SOURCE_NAMES = {
    'wikipedia': 'Wikipedia',
    'crossref': 'Crossref',
    'gdelt': 'GDELT News',
    'openlibrary': 'Open Library',
    'archive': 'Internet Archive',
    'europepmc': 'Europe PMC',
    'searxng': 'SearXNG',
    'demo': 'Demo',
}


def _dictionary(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _label(source):
    key = str(source).casefold().strip()
    for internal, human in SOURCE_NAMES.items():
        if key in (internal, human.casefold()):
            return internal
    return safe_line(str(source), 50).casefold()


def _links_by_provider(rows):
    """One canonical URL per provider, regardless of duplicate entries."""
    result = defaultdict(set)
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = clean_url(row.get('url', ''))
        if not url:
            continue
        names = row.get('sources', [])
        if isinstance(names, str):
            try:
                names = json.loads(names)
            except (ValueError, TypeError):
                names = []
        if not isinstance(names, (list, tuple)):
            continue
        for name in names[:15]:
            provider = _label(name)
            if provider:
                result[provider].add(url)
    return dict(result)


def analyze(session, selected, candidates):
    """Return a model of provenance for one *saved* session, never live health."""
    raw_reports = _dictionary(session.get('reports'))
    stats = _dictionary(session.get('stats'))
    saved = selected if isinstance(selected, list) else []
    full_candidates = candidates if isinstance(candidates, list) else []
    has_candidates = bool(full_candidates)
    base = full_candidates if has_candidates else saved
    contributed = _links_by_provider(base)
    chosen = _links_by_provider(saved)
    sources = {}
    for name, report in raw_reports.items():
        key = _label(name)
        if not key:
            continue
        rep = report if isinstance(report, dict) else {'status': str(report)}
        sources[key] = rep
    # Older demonstration and research sessions can have URLs but no reports.
    all_names = sorted(set(sources) | set(contributed) | set(chosen))
    provider_of_url = defaultdict(set)
    for name, urls in contributed.items():
        for url in urls:
            provider_of_url[url].add(name)
    all_urls = set(provider_of_url)
    shared_urls = {url for url, providers in provider_of_url.items() if len(providers) > 1}
    rows = []
    for key in all_names:
        rep = sources.get(key, {})
        urls = contributed.get(key, set())
        elapsed = rep.get('elapsed_ms')
        if type(elapsed) not in (int, float) or elapsed < 0 or elapsed > 3_600_000:
            elapsed = None
        else:
            elapsed = round(elapsed)
        try:
            returned = max(0, int(rep.get('found', 0)))
        except (TypeError, ValueError, OverflowError):
            returned = 0
        status = str(rep.get('status', 'unknown')).casefold()[:20]
        if status not in ('ok', 'empty', 'error', 'sample only'):
            status = 'unknown'
        rows.append({
            'key': key,
            'name': SOURCE_NAMES.get(key, safe_line(key, 40)),
            'status': 'demo' if status == 'sample only' else status,
            'returned': returned,
            'contributed': len(urls),
            'exclusive': sum(url not in shared_urls for url in urls),
            'overlap': len(urls & shared_urls),
            'selected': len(chosen.get(key, set())),
            'elapsed_ms': elapsed,
            # Error text is truncated and sanitized so terminal control codes are not printed.
            'detail': safe_line(rep.get('detail', ''), 120),
        })
    return {
        'session_id': session.get('id', '?'),
        'mode': str(session.get('mode', 'unknown'))[:24],
        'query': safe_line(session.get('query', ''), 90),
        'candidate_basis': 'full candidates' if has_candidates else 'saved selected links only',
        'candidate_count': len(all_urls),
        'selected_count': len({url for urls in chosen.values() for url in urls}),
        'shared_count': len(shared_urls),
        'quality': safe_line(stats.get('quality', 'not recorded'), 20),
        'relevance_breakdown': {name: stats.get(name) for name in ('high', 'possible', 'filtered_low')},
        'rows': rows,
    }


def display(neon, report):
    print('\n' + neon.fg('  ╔════════ BLACKSWARM // SOURCE PULSE ════════╗', 'purple', True))
    print(neon.fg('  ║  PROVIDER SIGNALS · LINK OVERLAP · TIMINGS  ║', 'cyan'))
    print(neon.fg('  ╚═══════════════════════════════════════════╝', 'purple'))
    print(neon.fg('  SAVED SESSION ', 'pink', True) + str(report['session_id']) +
          neon.fg('  ·  MODE ', 'purple') + report['mode'].upper())
    print(neon.fg('  QUERY ', 'cyan') + report['query'])
    print(neon.fg('  STORED DATA ', 'purple') + report['candidate_basis'])
    print(neon.fg(f"  {report['candidate_count']} UNIQUE OBSERVED URLS", 'green') +
          neon.fg(f"  |  {report['selected_count']} SELECTED", 'cyan') +
          neon.fg(f"  |  {report['shared_count']} CROSS-PROVIDER URLS", 'pink'))
    counts = report.get('relevance_breakdown', {})
    if all(isinstance(counts.get(key), int) and counts[key] >= 0 for key in ('high', 'possible', 'filtered_low')):
        print(neon.fg('  HEURISTIC QUALITY ', 'purple') +
              f"HIGH {counts['high']}  POSSIBLE {counts['possible']}  LOW {counts['filtered_low']}" +
              neon.fg('  ·  ' + report['quality'].upper(), 'cyan'))
    if report['mode'].casefold() == 'demo':
        print(neon.fg('  DEMO ONLY: illustrative sample records, NOT live provider checks.', 'yellow'))
    if not report['rows']:
        print(neon.fg('  No provider records stored for this saved session.', 'yellow'))
    strongest = max((row['contributed'] for row in report['rows']), default=0)
    colors = ('green','cyan','purple','pink','yellow','blue')
    for i, row in enumerate(report['rows']):
        status = row['status'].upper()
        color = 'red' if status == 'ERROR' else ('green' if status == 'OK' else 'yellow')
        timer = f"{row['elapsed_ms']} ms" if row['elapsed_ms'] is not None else 'n/a (old session)'
        bar = '█' * max(1, round(22 * row['contributed'] / strongest)) if row['contributed'] else '·'
        print(neon.fg(f"  {row['name']:<17}", colors[i % len(colors)], True) +
              neon.fg(status.ljust(9), color) +
              neon.fg(bar, colors[i % len(colors)]) + f"  {row['contributed']} URLs")
        print(neon.fg('      ', 'cyan') +
              f"returned {row['returned']} | source-only {row['exclusive']} | " +
              f"overlap {row['overlap']} | selected {row['selected']} | {timer}")
        if status == 'ERROR' and row['detail']:
            print('      ' + neon.fg('Reported error: ' + row['detail'], 'yellow'))
    print(neon.fg('  SOURCE PULSE = SAVED SESSION SNAPSHOT, NOT LIVE UPTIME.', 'yellow'))
    print(neon.fg('  No provider contacted. No vault changes. No browser.', 'green'))
