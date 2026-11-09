"""BLACKSWARM // INTEL COLLECTIONS.

Offline, terminal-only curated collections made from existing starred bookmarks.
Writes only to a new separate collections.sqlite3, never results.sqlite3 or
bookmarks.sqlite3. No network clients, browsers, shell or desktop calls.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from . import bookmarks, tags
from .intel import safe_line


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _id(value):
    data=str(value).strip()
    return int(data) if data.isdecimal() and int(data)>0 else None


def _sanitize(value, bound=300):
    return safe_line(str(value), bound).strip()


def _name(value):
    data=_sanitize(value,64)
    if not (2 <= len(data) <= 64):
        raise ValueError('Collection name must be 2–64 characters')
    return data


def _csv_literal(value):
    data=str(value)
    return "'"+data if data.lstrip().startswith(('=', '+', '-', '@')) else data


class IntelCollections:
    """New isolated storage for named bookmark collections."""
    def __init__(self, folder=None):
        home = Path(folder) if folder is not None else Path(
            os.environ.get('BLACKSWARM_COLLECTIONS', str(bookmarks.BOOKMARKS_HOME)))
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = home/'collections.sqlite3'
        self.lock=RLock()
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS collection_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                bookmark_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                sources TEXT NOT NULL,
                relevance TEXT NOT NULL,
                bookmark_note TEXT NOT NULL DEFAULT '',
                added_at TEXT NOT NULL,
                UNIQUE(collection_id,url)
            )''')
        if os.name=='posix':
            try: self.path.chmod(0o600)
            except OSError: pass

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.path,timeout=8)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db: yield db
        finally: db.close()

    def create(self,name,description=''):
        title=_name(name)
        with self.lock,self._connect() as db:
            try:
                cursor=db.execute('INSERT INTO collections (name,description,created_at,updated_at) VALUES (?,?,?,?)',
                                  (title,_sanitize(description,500),_now(),_now()))
            except sqlite3.IntegrityError as exc:
                raise ValueError('That collection name already exists') from exc
            return cursor.lastrowid

    def all(self):
        with self.lock,self._connect() as db:
            rows=db.execute('''SELECT c.*, COUNT(i.id) AS link_count FROM collections c
                LEFT JOIN collection_items i ON i.collection_id=c.id
                GROUP BY c.id ORDER BY c.id''').fetchall()
            return [dict(r) for r in rows]

    def get(self,cid):
        with self.lock,self._connect() as db:
            row=db.execute('''SELECT c.*, COUNT(i.id) AS link_count FROM collections c
                LEFT JOIN collection_items i ON i.collection_id=c.id
                WHERE c.id=? GROUP BY c.id''',(cid,)).fetchone()
            return dict(row) if row else None

    def update(self,cid,name=None,description=None):
        current=self.get(cid)
        if not current: return False
        title=_name(name) if name is not None else current['name']
        text=_sanitize(description,500) if description is not None else current['description']
        with self.lock,self._connect() as db:
            try:
                changed=db.execute('''UPDATE collections SET name=?,description=?,updated_at=? WHERE id=?''',
                                   (title,text,_now(),cid))
            except sqlite3.IntegrityError as exc:
                raise ValueError('That collection name already exists') from exc
            return changed.rowcount>0

    def add(self,cid,bookmark):
        if not self.get(cid): raise ValueError('Collection ID not found')
        if not bookmark or not isinstance(bookmark.get('id'),int):
            raise ValueError('Bookmark ID not found')
        with self.lock,self._connect() as db:
            cursor=db.execute('''INSERT OR IGNORE INTO collection_items
                (collection_id,bookmark_id,url,title,sources,relevance,bookmark_note,added_at)
                VALUES (?,?,?,?,?,?,?,?)''',(
                cid,bookmark['id'],bookmark['url'],_sanitize(bookmark.get('title',''),350),
                json.dumps(bookmark.get('sources',[])[:12],ensure_ascii=False),
                _sanitize(bookmark.get('relevance','unscored'),30),
                _sanitize(bookmark.get('note',''),700),_now()))
            return cursor.rowcount>0

    def items(self,cid):
        with self.lock,self._connect() as db:
            rows=db.execute('SELECT * FROM collection_items WHERE collection_id=? ORDER BY id',(cid,)).fetchall()
            result=[]
            for r in rows:
                item=dict(r)
                item['sources']=json.loads(item['sources'])
                result.append(item)
            return result


    def radar_search(self, phrase, cid=None):
        """Read-only multi-term search across saved collection metadata snapshots.

        Every term must match some field of the same collected item or its
        collection. No network calls; no updates; no outside FTS dependency.
        """
        query=_sanitize(phrase,160)
        terms=[t.casefold() for t in query.split()]
        if not terms: return []
        if cid is not None and not self.get(cid): raise ValueError('Collection ID not found')
        with self.lock,self._connect() as db:
            sql=('SELECT i.*, c.name AS collection_name, c.description AS collection_description '
                 'FROM collection_items AS i JOIN collections AS c ON c.id=i.collection_id')
            if cid is not None:
                sql+=' WHERE c.id=?'
                rows=db.execute(sql+' ORDER BY i.id',(cid,)).fetchall()
            else:
                rows=db.execute(sql+' ORDER BY i.id').fetchall()
        matches=[]
        for r in rows:
            item=dict(r)
            try:
                sources=json.loads(item['sources'])
                if not isinstance(sources,list): sources=[]
            except (ValueError,TypeError): sources=[]
            fields=(item['title'],item['url'],item['bookmark_note'],item['relevance'],
                    item['collection_name'],item['collection_description'],
                    ' '.join(str(a) for a in sources))
            haystack=' '.join(str(field) for field in fields).casefold()
            if not all(t in haystack for t in terms): continue
            weights=(9,5,6,1,3,2,3)
            score=sum(weight for field,weight in zip(fields,weights)
                      for token in terms if token in str(field).casefold())
            item['sources']=sources
            item['radar_score']=score
            matches.append(item)
        return sorted(matches,key=lambda i:(-i['radar_score'],i['collection_id'],i['id']))

    def radar_pulse(self):
        """Read-only collection overview and cross-collection duplication count."""
        folders=self.all()
        with self.lock,self._connect() as db:
            rows=db.execute('SELECT url FROM collection_items').fetchall()
        urls=[r['url'] for r in rows]
        return {'folders':folders,'total_links':len(urls),
                'unique_urls':len(set(urls)),
                'cross_collection_copies':len(urls)-len(set(urls))}

    def remove_link(self,cid,item_id):
        with self.lock,self._connect() as db:
            cursor=db.execute('DELETE FROM collection_items WHERE collection_id=? AND id=?',(cid,item_id))
            return cursor.rowcount>0

    def export(self,cid,format='csv'):
        folder=self.get(cid)
        if not folder: raise ValueError('Collection not found')
        records=self.items(cid)
        if format=='json':
            return json.dumps({'app':'BLACKSWARM','kind':'intel-collection','collection':folder,
                               'links':records},ensure_ascii=False,indent=2).encode('utf-8')
        if format!='csv': raise ValueError('Use csv or json')
        buffer=io.StringIO()
        columns=('collection_id','collection_name','id','bookmark_id','url','title','sources',
                 'relevance','bookmark_note','added_at')
        writer=csv.DictWriter(buffer,columns)
        writer.writeheader()
        for record in records:
            d={'collection_id':cid,'collection_name':folder['name'],**record,
               'sources':'; '.join(record['sources'])}
            writer.writerow({k:_csv_literal(d.get(k,'')) for k in columns})
        return buffer.getvalue().encode('utf-8-sig')


def _show_collection(neon,store,cid,input_fn):
    data=store.get(cid)
    if not data: return
    page=0
    size=8
    while True:
        rows=store.items(cid)
        total=len(rows)
        print('\n'+neon.fg(f'  ✦ {safe_line(data["name"],64)}  |  {total} LINKS  |  PAGE {page+1}/{max(1,(total+size-1)//size)}','purple',True))
        if data['description']: print(neon.fg('  '+safe_line(data['description'],230),'yellow'))
        if not rows:
            print(neon.fg('  This collection is empty. Use [3] to add starred links.','yellow'))
            return
        for item in rows[page*size:(page+1)*size]:
            print(neon.fg(f"  [#{item['id']}] ",'cyan')+safe_line(item['title'],85))
            print(neon.fg('        '+safe_line(item['url'],180),'blue'))
        choice=input_fn(neon.fg('  n next | p previous | item ID details | b back: ','yellow')).strip().lower()
        if choice in ('','b','0'):return
        if choice=='n':
            if (page+1)*size<total:page+=1
            else:print(neon.fg('  Last page.','yellow'))
        elif choice=='p':
            if page:page-=1
            else:print(neon.fg('  First page.','yellow'))
        elif _id(choice):
            item=next((r for r in rows if r['id']==int(choice)),None)
            if item:
                print(neon.fg(f"  ITEM #{item['id']}  |  ★ BOOKMARK #{item['bookmark_id']}",'green'))
                print('  '+safe_line(item['title'],200))
                print(neon.fg('  URL ', 'cyan')+safe_line(item['url'],400))
                print(neon.fg('  SOURCE ','purple')+', '.join(item['sources']))
                if item['bookmark_note']:print(neon.fg('  NOTE ','pink')+safe_line(item['bookmark_note'],700))
                print(neon.fg('  Saved metadata snapshot. No website opened.','yellow'))
            else:print(neon.fg('  Item ID not found.','yellow'))
        else:print(neon.fg('  Choose n, p, an item ID, or b.','yellow'))




def _collection_radar(neon,store,input_fn):
    print('\n'+neon.fg('  ☣ COLLECTION RADAR // SEARCH MY SAVED INTEL','purple',True))
    print(neon.fg('  Local collection snapshots only. No browsing or new search.','green'))
    if not store.all():
        print(neon.fg('  No collections yet. Create one with [2].','yellow'))
        return
    query=input_fn(neon.fg('  Find words in titles, notes, URLs, sources or folders (Enter = back): ','cyan')).strip()
    if not query: return
    scope=input_fn(neon.fg('  Collection ID filter [Enter = ALL collections]: ','yellow')).strip()
    cid=_id(scope) if scope else None
    if scope and cid is None:
        print(neon.fg('  Invalid collection ID. Radar canceled.','yellow')); return
    try: results=store.radar_search(query,cid)
    except ValueError as exc:
        print(neon.fg('  '+str(exc),'yellow'));return
    if not results:
        print(neon.fg('  NO SAVED LINKS MATCH. Nothing changed.','yellow'))
        return
    size=8
    page=0
    urls=len(set(i['url'] for i in results))
    while True:
        start=page*size
        print('\n'+neon.fg(f'  ✦ RADAR: {len(results)} MATCHES  |  {urls} UNIQUE URLs  |  PAGE {page+1}/{(len(results)+size-1)//size}','purple',True))
        print(neon.fg('  QUERY ','cyan')+safe_line(query,160))
        for item in results[start:start+size]:
            print(neon.fg(f"  [#{item['id']}] ★ ",'yellow')+safe_line(item['title'],85))
            print(neon.fg(f"        FOLDER #{item['collection_id']}: ",'purple')+safe_line(item['collection_name'],65))
            print(neon.fg('        '+safe_line(item['url'],200),'blue'))
        choice=input_fn(neon.fg('  n next | p previous | item ID details | b back: ','yellow')).strip().lower()
        if choice in ('','b','0'): return
        if choice=='n':
            if (page+1)*size<len(results):page+=1
            else:print(neon.fg('  Last page.','yellow'))
        elif choice=='p':
            if page:page-=1
            else:print(neon.fg('  First page.','yellow'))
        elif _id(choice):
            item=next((r for r in results if r['id']==int(choice)),None)
            if item is None:
                print(neon.fg('  Item ID not found in these matches.','yellow'));continue
            print('\n'+neon.fg(f"  ★ RADAR ITEM #{item['id']}  |  COLLECTION #{item['collection_id']}",'green',True))
            print(neon.fg('  FOLDER ','purple')+safe_line(item['collection_name'],90))
            print(neon.fg('  TITLE ','cyan')+safe_line(item['title'],350))
            print(neon.fg('  URL ','blue')+safe_line(item['url'],400))
            print(neon.fg('  SOURCES ','purple')+', '.join(str(s) for s in item['sources']))
            print(neon.fg('  RELEVANCE ','green')+safe_line(item['relevance'],30))
            if item['bookmark_note']:
                print(neon.fg('  SAVED NOTE ','pink')+safe_line(item['bookmark_note'],700))
            print(neon.fg('  Stored metadata only. No webpage opened.','yellow'))
        else:print(neon.fg('  Choose n, p, a displayed item ID, or b.','yellow'))


def _collection_pulse(neon,store):
    status=store.radar_pulse()
    print('\n'+neon.fg('  ☣ COLLECTION PULSE // LOCAL SWARM CHART','purple',True))
    print(neon.fg(f"  {len(status['folders'])} FOLDERS  |  {status['total_links']} ENTRIES  |  {status['unique_urls']} UNIQUE URLs",'green'))
    print(neon.fg(f"  {status['cross_collection_copies']} CROSS-COLLECTION COPIES (NOT EXTRA URLS)",'yellow'))
    folders=status['folders']
    if not folders:
        print(neon.fg('  Create a collection with [2] to see your chart.','yellow'));return
    maximum=max(1,max(c['link_count'] for c in folders))
    colors=('green','cyan','purple','pink','yellow','blue')
    for idx,c in enumerate(folders):
        bar='█'*min(32,round(32*c['link_count']/maximum))
        if c['link_count'] and not bar: bar='▏'
        print(neon.fg(f"  #{c['id']:>3} ",colors[idx%len(colors)])+
              safe_line(c['name'],27).ljust(27)+' '+
              neon.fg(bar,colors[idx%len(colors)])+
              neon.fg(f"  {c['link_count']} links",'green'))
    print(neon.fg('  Snapshot counts only. Vaults unchanged.','cyan'))

def collection_desk(neon,store,shelf,input_fn=None,export_root=None):
    """Explore/create link collections with independent local storage only."""
    input_fn=input_fn or input
    print('\n'+neon.fg('  ╔═══════ BLACKSWARM // INTEL COLLECTIONS ═══════╗','purple',True))
    print(neon.fg('  ║  STARRED LINKS · COLLECTION RADAR · EXPORTS  ║','cyan'))
    print(neon.fg('  ╚═══════════════════════════════════════════════╝','purple'))
    print(neon.fg('  Research and bookmark vaults stay unchanged. No browser.','green'))
    while True:
        print('\n'+neon.fg('  ═════ COLLECTION CONTROL ═════','purple',True))
        for n,color,label in [('1','green','VIEW COLLECTIONS + LINKS'),('2','cyan','CREATE COLLECTION'),
                              ('3','yellow','ADD A STARRED BOOKMARK'),('4','pink','RENAME / EDIT DESCRIPTION'),
                              ('5','red','REMOVE LINK FROM COLLECTION ONLY'),('6','blue','EXPORT COLLECTION CSV / JSON'),
                              ('7','green','COLLECTION RADAR // SEARCH ALL FOLDERS'),
                              ('8','purple','COLLECTION PULSE // RAINBOW MINI CHART'),
                              ('9','green','SWARM TAGS // LABEL SAVED LINKS'),
                              ('0','purple','RETURN TO COMMAND DECK')]:
            print(neon.fg(f'  [{n}] ',color)+label)
        choice=input_fn(neon.fg('  COLLECTIONS ❯ ','green',True)).strip()
        if choice in ('','0','q','quit'):
            print(neon.fg('  Intel Collections closed. Existing vaults unchanged.','purple'))
            return
        if choice=='1':
            folders=store.all()
            if not folders:
                print(neon.fg('  No collections yet. Choose [2] to create your first.','yellow')); continue
            print(neon.fg('  YOUR INTEL COLLECTIONS','pink',True))
            for folder in folders:
                print(neon.fg(f"  #{folder['id']} ",'cyan')+safe_line(folder['name'],64)+
                      neon.fg(f"  |  {folder['link_count']} starred links",'green'))
            cid=_id(input_fn(neon.fg('  Collection ID to open (Enter = back): ','cyan')))
            if cid:
                if store.get(cid):_show_collection(neon,store,cid,input_fn)
                else:print(neon.fg('  Collection ID not found.','yellow'))
        elif choice=='2':
            label=input_fn(neon.fg('  New collection name (Enter = cancel): ','cyan')).strip()
            if not label:continue
            description=input_fn(neon.fg('  Description (optional, Enter to skip): ','pink'))
            try:
                cid=store.create(label,description)
                print(neon.fg(f'  ✓ COLLECTION #{cid} CREATED. Add favorites with [3].','green'))
            except ValueError as e:print(neon.fg('  '+str(e),'yellow'))
        elif choice=='3':
            folders=store.all()
            favorites=shelf.all()
            if not folders:
                print(neon.fg('  Create a collection first with [2].','yellow'));continue
            if not favorites:
                print(neon.fg('  No starred bookmarks. Use [11] navigator then f + number first.','yellow'));continue
            for f in folders:print(neon.fg(f"  COLLECTION #{f['id']}",'cyan')+'  '+safe_line(f['name'],60))
            cid=_id(input_fn(neon.fg('  Collection ID (Enter = cancel): ','cyan')))
            if not cid:continue
            folder=store.get(cid)
            if not folder:print(neon.fg('  Collection ID not found.','yellow'));continue
            print(neon.fg('  YOUR STARRED BOOKMARK IDs','purple',True))
            for f in favorites[:40]:
                print(neon.fg(f"  ★ #{f['id']} ",'yellow')+safe_line(f['title'],80))
            if len(favorites)>40:print(neon.fg('  First 40 shown; [12] lists all bookmark IDs.','yellow'))
            bid=_id(input_fn(neon.fg('  Bookmark ID to add (Enter = cancel): ','cyan')))
            if not bid:continue
            item=shelf.find(bid)
            if not item:print(neon.fg('  Bookmark ID not found.','yellow'));continue
            print(neon.fg('  ADD TO '+safe_line(folder['name'],64)+': ','pink')+safe_line(item['title'],110))
            try:
                created=store.add(cid,item)
                print(neon.fg('  ★ LINK ADDED TO COLLECTION.' if created else '  ★ ALREADY IN COLLECTION; NOT DUPLICATED.',
                              'green' if created else 'yellow'))
            except ValueError as e:print(neon.fg('  '+str(e),'yellow'))
        elif choice=='4':
            cid=_id(input_fn(neon.fg('  Collection ID to edit (Enter = back): ','cyan')))
            if not cid:continue
            current=store.get(cid)
            if not current:print(neon.fg('  Collection ID not found.','yellow'));continue
            print(neon.fg('  CURRENT '+safe_line(current['name'],65),'purple'))
            label=input_fn(neon.fg('  New name (Enter = keep): ','cyan')).strip()
            desc=input_fn(neon.fg('  New description (Enter = keep; type CLEAR to empty): ','pink'))
            try:
                store.update(cid,name=label if label else None,
                             description='' if desc=='CLEAR' else (desc if desc else None))
                print(neon.fg('  ✓ COLLECTION UPDATED.','green'))
            except ValueError as e:print(neon.fg('  '+str(e),'yellow'))
        elif choice=='5':
            cid=_id(input_fn(neon.fg('  Collection ID (Enter = cancel): ','cyan')))
            if not cid:continue
            if not store.get(cid):print(neon.fg('  Collection ID not found.','yellow'));continue
            entries=store.items(cid)
            for i in entries[:40]:print(neon.fg(f"  ITEM #{i['id']} ",'cyan')+safe_line(i['title'],80))
            itemid=_id(input_fn(neon.fg('  Item ID to unlink (Enter = cancel): ','cyan')))
            if not itemid:continue
            chosen=next((item for item in entries if item['id']==itemid),None)
            if not chosen:print(neon.fg('  Item ID not found in this collection.','yellow'));continue
            print(neon.fg('  COLLECTION LINK: ','yellow')+safe_line(chosen['title'],110))
            confirmation=input_fn(neon.fg('  Type REMOVE to unlink ONLY from this collection: ','red')).strip()
            if confirmation=='REMOVE':
                store.remove_link(cid,itemid)
                print(neon.fg('  ✓ UNLINKED. Bookmark and research record preserved.','green'))
            else:print(neon.fg('  Canceled. Nothing removed.','yellow'))
        elif choice=='7':
            _collection_radar(neon,store,input_fn)
        elif choice=='8':
            _collection_pulse(neon,store)
        elif choice=='9':
            tags.tag_desk(neon,store,input_fn)
        elif choice=='6':
            cid=_id(input_fn(neon.fg('  Collection ID (Enter = cancel): ','cyan')))
            if not cid:continue
            folder=store.get(cid)
            if not folder:print(neon.fg('  Collection ID not found.','yellow'));continue
            fmt=input_fn(neon.fg('  Format [csv/json; default csv]: ','cyan')).strip().lower() or 'csv'
            if fmt not in ('csv','json'):
                print(neon.fg('  Choose csv or json.','yellow'));continue
            root=Path(export_root) if export_root is not None else Path.home()/'Documents'/'BLACKSWARM-EXPORTS'
            root.mkdir(parents=True,exist_ok=True,mode=0o700)
            for num in range(1,10001):
                dest=root/f'BLACKSWARM-COLLECTION-{cid}-{num:03d}.{fmt}'
                try:
                    with dest.open('xb') as file:
                        if os.name=='posix':dest.chmod(0o600)
                        file.write(store.export(cid,fmt))
                    print(neon.fg('  ✓ COLLECTION EXPORTED: ','green')+str(dest))
                    break
                except FileExistsError:continue
        else:
            print(neon.fg('  Choose a menu number from 0 through 9.','yellow'))
