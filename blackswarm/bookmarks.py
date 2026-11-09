"""BLACKSWARM // BOOKMARKED INTEL.

Local, optional, self-contained bookmark database. Preserves the existing
BLACKSWARM research vault: no queries, updates or schema changes to results.sqlite3.
No network access and no browser launches.
"""
from __future__ import annotations
import csv
import io
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .core import clean_url
from .intel import safe_line

BOOKMARKS_HOME = Path(os.getenv('BLACKSWARM_BOOKMARKS', str(Path.home() / '.local' / 'share' / 'blackswarm-bookmarks')))


def note_text(value: str) -> str:
    """Strip control characters and bound the size of user-supplied notes."""
    return safe_line(value, 700)


class BookmarkShelf:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else BOOKMARKS_HOME
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.dbpath = self.folder / 'bookmarks.sqlite3'
        self.lock = threading.RLock()
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                snippet TEXT NOT NULL DEFAULT '',
                sources TEXT NOT NULL DEFAULT '[]',
                relevance TEXT NOT NULL DEFAULT 'unscored',
                score INTEGER NOT NULL DEFAULT 0,
                session_id INTEGER NOT NULL,
                search_phrase TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )''')
        # Restrict the separate bookmark db; do not change user's terminal
        # or any research vault permissions.
        if os.name == 'posix':
            try: self.dbpath.chmod(0o600)
            except OSError: pass

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.dbpath,timeout=8)
        db.row_factory=sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, row, session_id: int, phrase: str, note: str=''):
        url=clean_url(str(row.get('url','')))
        if not url:
            raise ValueError('A valid public http(s) URL is required')
        if not isinstance(session_id,int) or session_id < 1:
            raise ValueError('Choose an existing saved Session ID')
        now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self.lock,self._connect() as db:
            result=db.execute('''INSERT OR IGNORE INTO bookmarks
               (url,title,snippet,sources,relevance,score,session_id,search_phrase,note,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(
                url,safe_line(row.get('title',''),350),safe_line(row.get('snippet',''),700),
                json.dumps([safe_line(s,90) for s in row.get('sources',[])][:12]),
                safe_line(row.get('relevance','unscored'),20),int(row.get('score',0)),
                session_id,safe_line(phrase,180),note_text(note),now,now))
            existing=db.execute('SELECT id FROM bookmarks WHERE url=?',(url,)).fetchone()
            return int(existing['id']),bool(result.rowcount)

    def all(self):
        with self.lock,self._connect() as db:
            return [self._convert(r) for r in db.execute('SELECT * FROM bookmarks ORDER BY id DESC')]

    def find(self, bid):
        with self.lock,self._connect() as db:
            row=db.execute('SELECT * FROM bookmarks WHERE id=?',(bid,)).fetchone()
            return self._convert(row) if row else None

    def by_url(self, url):
        with self.lock,self._connect() as db:
            row=db.execute('SELECT * FROM bookmarks WHERE url=?',(clean_url(url),)).fetchone()
            return self._convert(row) if row else None

    @staticmethod
    def _convert(row):
        if not row: return None
        obj=dict(row)
        obj['sources']=json.loads(obj['sources'])
        return obj

    def update_note(self,bid,note):
        now=datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self.lock,self._connect() as db:
            cur=db.execute('UPDATE bookmarks SET note=?, updated_at=? WHERE id=?',
                           (note_text(note),now,bid))
            return cur.rowcount > 0

    def delete(self,bid):
        with self.lock,self._connect() as db:
            cur=db.execute('DELETE FROM bookmarks WHERE id=?',(bid,))
            return cur.rowcount > 0

    def export(self,format='csv'):
        rows=self.all()
        if format=='json':
            return json.dumps({'app':'BLACKSWARM','kind':'bookmarks','count':len(rows),
                'items':rows},indent=2,ensure_ascii=False).encode('utf-8')
        if format!='csv': raise ValueError('Use CSV or JSON for bookmark exports')
        dest=io.StringIO()
        fields=('id','url','title','snippet','sources','relevance','score','session_id',
                'search_phrase','note','created_at','updated_at')
        writer=csv.DictWriter(dest,fieldnames=fields)
        writer.writeheader()
        for item in rows:
            fieldsafe={**item,'sources':'; '.join(item['sources'])}
            # Prevent formula execution if CSV is later opened in a spreadsheet.
            for field in ('title','snippet','search_phrase','note','sources'):
                val=str(fieldsafe[field])
                if val.lstrip().startswith(('=','+','-','@')):
                    fieldsafe[field]="'"+val
            writer.writerow(fieldsafe)
        return dest.getvalue().encode('utf-8-sig')


def _number(value):
    value=str(value).strip()
    return int(value) if value.isdecimal() and int(value)>0 else None


def _print_item(neon,item,detail=False):
    print(neon.fg(f"  ★ #{item['id']:>3}  ",'yellow',True)+
          neon.fg(safe_line(item['title'],95),'white'))
    print(neon.fg('      '+safe_line(item['url'],180),'cyan'))
    if detail:
        print(neon.fg('      SESSION ', 'purple')+str(item['session_id'])+
              neon.fg('  SOURCE ', 'blue')+', '.join(item['sources']))
        print(neon.fg('      SEARCH  ', 'purple')+safe_line(item['search_phrase'],180))
        print(neon.fg('      RELEVANCE ', 'green')+safe_line(item['relevance'],50))
        if item['note']:
            print(neon.fg('      NOTE  ', 'pink')+safe_line(item['note'],700))
        print(neon.fg('      Saved metadata only. No site opened.', 'yellow'))


def _shelf_list(neon,shelf,input_fn):
    rows=shelf.all()
    if not rows:
        print(neon.fg('  No favorites yet. Use [11] and type f, Enter, then a displayed link number.', 'yellow'))
        return
    page=0
    step=8
    while True:
        start=page*step
        ending=min(len(rows),start+step)
        print('\n'+neon.fg(f'  ★ FAVORITES  |  {len(rows)} TOTAL  |  PAGE {page+1}/{(len(rows)+step-1)//step}', 'green',True))
        for item in rows[start:ending]: _print_item(neon,item)
        answer=input_fn(neon.fg('  n next | p previous | ID details | e edit note | b back: ', 'yellow')).strip().lower()
        if answer in ('','b','0','back'): return
        if answer=='n':
            if ending<len(rows):page+=1
            else: print(neon.fg('  Last page.', 'yellow'))
        elif answer=='p':
            if page: page-=1
            else: print(neon.fg('  First page.', 'yellow'))
        elif answer == 'e' or (answer.startswith('e ') and _number(answer[2:])):
            if answer == 'e':
                edit=_number(input_fn(neon.fg('  ★ Bookmark ID to edit (Enter = cancel): ', 'cyan')))
            else:
                edit=_number(answer[2:])
            if edit is None:
                print(neon.fg('  Note edit canceled.', 'yellow'))
                continue
            item=shelf.find(edit)
            if not item:
                print(neon.fg('  Bookmark ID not found.', 'yellow'))
                continue
            _print_item(neon,item,detail=True)
            updated=input_fn(neon.fg('  New note (Enter = clear note): ', 'pink'))
            shelf.update_note(edit,updated)
            print(neon.fg('  ✓ Note updated in bookmark shelf. Research vault untouched.', 'green'))
        elif _number(answer):
            result=shelf.find(_number(answer))
            if result:_print_item(neon,result,detail=True)
            else:print(neon.fg('  Bookmark ID not found.', 'yellow'))
        else:
            print(neon.fg('  Use n, p, a bookmark ID, e to edit a note, or b.', 'yellow'))


def bookmark_desk(neon,vault,shelf,input_fn=None,ask_session=None):
    """Interactive bookmark management, separate from the research vault.

    Can only add URLs already saved in research sessions. No live web fetches.
    """
    from . import navigator
    input_fn=input_fn or input
    print('\n'+neon.fg('  ╔════════ BLACKSWARM // BOOKMARKED INTEL ════════╗','purple',True))
    print(neon.fg('  ║    FAVORITES  ·  NOTES  ·  PRIVATE COLLECTION ║','cyan'))
    print(neon.fg('  ╚══════════════════════════════════════════════╝','purple'))
    print(neon.fg('  Research vault READ-ONLY; favorites stored separately.', 'green'))
    while True:
        print('\n'+neon.fg('  ═════ BOOKMARK SHELF ═════','purple',True))
        print(neon.fg('  [1] ','green')+'VIEW SAVED FAVORITES')
        print(neon.fg('  [2] ','cyan')+'STAR LINKS FROM A SAVED SESSION')
        print(neon.fg('  [3] ','pink')+'EDIT FAVORITE NOTE')
        print(neon.fg('  [4] ','red')+'REMOVE ONE FAVORITE (CONFIRM FIRST)')
        print(neon.fg('  [5] ','yellow')+'EXPORT FAVORITES (CSV / JSON)')
        print(neon.fg('  [6] ','blue')+'QUICK FIND MY FAVORITES')
        print(neon.fg('  [0] ','purple')+'RETURN TO COMMAND DECK')
        choice=input_fn(neon.fg('  BOOKMARKS ❯ ','green',True)).strip().lower()
        if choice in ('0','q','exit',''):
            print(neon.fg('  Bookmark shelf closed. Your saved research is unchanged.','purple'))
            return
        if choice=='1':
            _shelf_list(neon,shelf,input_fn)
        elif choice=='2':
            if ask_session is not None:
                sid=ask_session(neon)
            else:
                answer=input_fn(neon.fg('  Saved Session ID (Enter = back): ', 'cyan')).strip()
                sid=_number(answer)
            if sid is None:continue
            run=vault.run(sid)
            if not run:
                print(neon.fg('  Session ID not found.', 'yellow'));continue
            phrase=input_fn(neon.fg('  Optional title/URL filter (Enter = all): ', 'cyan')).strip()[:100]
            rows=vault.results(sid)
            if phrase:rows=navigator.match_rows(rows,'text',phrase)
            if not rows:
                print(neon.fg('  No saved matches for that filter.', 'yellow'));continue
            print(neon.fg('  Type f then Enter, choose a displayed number, and ★ save. f 1 also works.', 'green'))
            navigator.browse(neon,rows,f'BOOKMARK PICKER: SESSION #{sid}',input_fn,
                bookmark_factory=lambda:shelf,session_id=sid,query=run['query'])
        elif choice=='3':
            bid=_number(input_fn(neon.fg('  Bookmark ID to edit (Enter = back): ', 'cyan')))
            if not bid:continue
            item=shelf.find(bid)
            if not item:print(neon.fg('  No favorite with that ID.','yellow'));continue
            _print_item(neon,item,detail=True)
            note=input_fn(neon.fg('  New note (Enter = clear note): ', 'pink'))
            shelf.update_note(bid,note)
            print(neon.fg('  ✓ Note saved to separate bookmark database.', 'green'))
        elif choice=='4':
            bid=_number(input_fn(neon.fg('  Bookmark ID to remove (Enter = back): ', 'cyan')))
            if not bid:continue
            item=shelf.find(bid)
            if not item:print(neon.fg('  No favorite with that ID.', 'yellow'));continue
            _print_item(neon,item,detail=True)
            check=input_fn(neon.fg('  Type REMOVE to unstar just this favorite: ', 'red')).strip()
            if check=='REMOVE':
                shelf.delete(bid)
                print(neon.fg('  ✓ Favorite removed. Original research link unchanged.','green'))
            else:print(neon.fg('  Canceled. Nothing removed.','yellow'))
        elif choice=='5':
            fmt=input_fn(neon.fg('  Format [csv/json; default csv]: ', 'cyan')).strip().lower() or 'csv'
            if fmt not in ('csv','json'):
                print(neon.fg('  Use csv or json.','yellow'));continue
            root=Path.home()/'Documents'/'BLACKSWARM-EXPORTS'
            root.mkdir(mode=0o700,parents=True,exist_ok=True)
            # Never overwrite exports. The app does not launch a browser or spreadsheet.
            for i in range(1,10001):
                path=root/f'BLACKSWARM-BOOKMARKS-{i:03d}.{fmt}'
                try:
                    with path.open('xb') as file:
                        if os.name=='posix':path.chmod(0o600)
                        file.write(shelf.export(fmt))
                    print(neon.fg('  ✓ FAVORITES EXPORTED: ', 'green')+str(path))
                    break
                except FileExistsError:continue
            else:print(neon.fg('  Too many exports in that folder.', 'yellow'))
        elif choice=='6':
            term=input_fn(neon.fg('  Search bookmarks by title/URL/note: ','cyan')).strip().casefold()[:100]
            if not term:continue
            matches=[r for r in shelf.all() if term in ' '.join(str(r.get(k,'')) for k in ('title','url','note','search_phrase')).casefold()]
            print(neon.fg(f'  ★ {len(matches)} SAVED FAVORITES MATCH', 'green'))
            for r in matches[:30]:_print_item(neon,r,detail=True)
            if len(matches)>30:print(neon.fg('  Showing first 30. Narrow the search phrase for more.','yellow'))
        else:
            print(neon.fg('  Choose an option from 0 through 6.', 'yellow'))
