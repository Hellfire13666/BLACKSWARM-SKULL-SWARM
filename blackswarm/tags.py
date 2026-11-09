"""BLACKSWARM // SWARM TAGS.

Standalone, local-only labels for URLs already saved in Intel Collections.
All tag writes go into tags.sqlite3. Never changes the three older vault DBs.
No network, subprocess, browser, OS settings or desktop integration.
"""
from __future__ import annotations

import os
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from .bookmarks import BOOKMARKS_HOME
from .core import clean_url
from .intel import safe_line


def _clean_label(value):
    label=safe_line(str(value),36).strip()
    if not (2 <= len(label) <= 36):
        raise ValueError('Tag must be between 2 and 36 characters')
    if any(c in label for c in ('#','|',',','\\')):
        raise ValueError('Tag cannot contain #, |, comma or backslash')
    return label


def _valid_url(value):
    url=clean_url(str(value))
    if not url:
        raise ValueError('Saved link has no valid public URL')
    return url


class SwarmTags:
    """Isolated SQLite tag index keyed by bookmark URL, shared across folders."""
    def __init__(self, folder=None):
        self.folder=Path(folder) if folder is not None else BOOKMARKS_HOME
        self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.folder/'tags.sqlite3'
        self.lock=RLock()
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tags (
                url TEXT NOT NULL,
                label_key TEXT NOT NULL,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (url,label_key)
            )""")
        if os.name=='posix':
            try:self.path.chmod(0o600)
            except OSError:pass

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.path,timeout=8)
        db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def add(self,url,label):
        url=_valid_url(url)
        label=_clean_label(label)
        with self.lock,self._connect() as db:
            n=db.execute('SELECT count(*) FROM tags WHERE url=?',(url,)).fetchone()[0]
            if n>=20:
                same=db.execute('SELECT 1 FROM tags WHERE url=? AND label_key=?',
                                (url,label.casefold())).fetchone()
                if not same:raise ValueError('Maximum of 20 tags per link')
            result=db.execute('INSERT OR IGNORE INTO tags(url,label_key,label,created_at) VALUES(?,?,?,?)',
                              (url,label.casefold(),label,datetime.now(timezone.utc).isoformat(timespec='seconds')))
            return result.rowcount>0

    def list_for(self,url):
        url=_valid_url(url)
        with self.lock,self._connect() as db:
            return [row['label'] for row in db.execute(
                'SELECT label FROM tags WHERE url=? ORDER BY label_key',(url,)).fetchall()]

    def remove(self,url,label):
        url=_valid_url(url)
        label=_clean_label(label)
        with self.lock,self._connect() as db:
            result=db.execute('DELETE FROM tags WHERE url=? AND label_key=?',
                              (url,label.casefold()))
            return result.rowcount>0

    def all(self):
        with self.lock,self._connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT url,label FROM tags ORDER BY label_key,url').fetchall()]

    def by_url(self):
        result={}
        for row in self.all():
            result.setdefault(row['url'],[]).append(row['label'])
        return result


def _ask_id(input_fn,prompt,neon):
    entered=input_fn(neon.fg(prompt,'cyan')).strip()
    if not entered:return None
    return int(entered) if entered.isdecimal() and int(entered)>0 else None


def _folder_item(neon,store,input_fn):
    folders=store.all()
    if not folders:
        print(neon.fg('  No collections yet. Create one with [2] first.','yellow'))
        return None
    for folder in folders:
        print(neon.fg(f"  FOLDER #{folder['id']} ",'purple') +
              safe_line(folder['name'],55)+f"  ({folder['link_count']} links)")
    cid=_ask_id(input_fn,'  Collection ID (Enter = cancel): ',neon)
    if cid is None:return None
    folder=store.get(cid)
    if not folder:
        print(neon.fg('  Collection ID not found.','yellow'));return None
    rows=store.items(cid)
    if not rows:
        print(neon.fg('  This folder has no links yet.','yellow'));return None
    for row in rows[:40]:
        print(neon.fg(f"  ITEM #{row['id']} ",'cyan')+safe_line(row['title'],78))
    if len(rows)>40:print(neon.fg('  First 40 shown; enter a known item ID if needed.','yellow'))
    itemid=_ask_id(input_fn,'  Item ID (Enter = cancel): ',neon)
    if itemid is None:return None
    item=next((i for i in rows if i['id']==itemid),None)
    if not item:
        print(neon.fg('  Item ID not found in that folder.','yellow'));return None
    return folder,item


def _unique_links(store):
    """Read-only snapshot: one entry per unique collected URL."""
    results={}
    for folder in store.all():
        for item in store.items(folder['id']):
            row=results.setdefault(item['url'],{
                'url':item['url'],'title':item['title'],'folders':[]})
            row['folders'].append((folder['id'],folder['name']))
    return results


def tag_desk(neon,store,input_fn=None,tag_folder=None):
    """Tag menu. Calls only tag DB for mutations and collection DB for reads."""
    input_fn=input_fn or input
    tags=SwarmTags(tag_folder if tag_folder is not None else store.path.parent)
    print('\n'+neon.fg('  ╔════════ BLACKSWARM // SWARM TAGS ════════╗','purple',True))
    print(neon.fg('  ║  COLOR LABELS · QUICK FIND · TAG NEBULA   ║','cyan'))
    print(neon.fg('  ╚═════════════════════════════════════════╝','purple'))
    print(neon.fg('  Separate tags vault. Research, favorites and collections remain unchanged.','green'))
    while True:
        print('\n'+neon.fg('  ═════ TAG CONTROL ═════','purple',True))
        commands=[('1','cyan','VIEW TAGGED LINKS'),
                  ('2','green','ADD A TAG TO A COLLECTION LINK'),
                  ('3','yellow','REMOVE A TAG (CONFIRM FIRST)'),
                  ('4','blue','FIND SAVED LINKS BY TAG'),
                  ('5','purple','TAG NEBULA // RAINBOW CHART'),
                  ('0','red','BACK TO COLLECTION CONTROL')]
        for num,color,caption in commands:
            print(neon.fg(f'  [{num}] ',color)+caption)
        choice=input_fn(neon.fg('  TAGS ❯ ','green',True)).strip().lower()
        if choice in ('0','q','quit',''):
            print(neon.fg('  Swarm Tags closed. Older vaults unchanged.','purple'))
            return
        if choice=='2':
            selected=_folder_item(neon,store,input_fn)
            if selected is None:continue
            folder,item=selected
            label=input_fn(neon.fg('  New tag (2-36 characters; Enter = cancel): ','green')).strip()
            if not label:continue
            try:
                created=tags.add(item['url'],label)
                print(neon.fg('  ★ TAG ADDED TO SAVED LINK.' if created else '  ★ TAG ALREADY EXISTS; NO DUPLICATE.',
                              'green' if created else 'yellow'))
                print(neon.fg('  TAGS: ','cyan')+', '.join(tags.list_for(item['url'])))
            except ValueError as exc:print(neon.fg('  '+str(exc),'yellow'))
        elif choice=='3':
            selected=_folder_item(neon,store,input_fn)
            if selected is None:continue
            folder,item=selected
            labels=tags.list_for(item['url'])
            if not labels:
                print(neon.fg('  This link has no tags.','yellow'));continue
            print(neon.fg('  TAGS: ','cyan')+', '.join(labels))
            label=input_fn(neon.fg('  Tag to remove (Enter = cancel): ','yellow')).strip()
            if not label:continue
            if label.casefold() not in [x.casefold() for x in labels]:
                print(neon.fg('  Tag not found on this link.','yellow'));continue
            conf=input_fn(neon.fg('  Type REMOVE to delete only this tag: ','red')).strip()
            if conf=='REMOVE':
                tags.remove(item['url'],label)
                print(neon.fg('  ✓ TAG REMOVED. Original saved link preserved.','green'))
            else:print(neon.fg('  Canceled. Nothing removed.','yellow'))
        elif choice in ('1','4'):
            current=_unique_links(store)
            tagged=tags.by_url()
            if choice=='4':
                term=input_fn(neon.fg('  Find tag (Enter = back): ','cyan')).strip().casefold()
                if not term:continue
            else:term=''
            matches=[]
            for url,row in current.items():
                labels=tagged.get(url,[])
                if labels and (not term or any(term in x.casefold() for x in labels)):
                    matches.append((row,labels))
            print('\n'+neon.fg(f'  ✦ TAG RADAR: {len(matches)} SAVED LINKS','purple',True))
            if not matches:
                print(neon.fg('  No matching tagged links in current collections.','yellow'))
            for row,labels in matches[:100]:
                print(neon.fg('  ★ ','yellow')+safe_line(row['title'],93))
                print(neon.fg('    TAGS ','green')+', '.join(labels))
                print(neon.fg('    FOLDERS ','purple')+', '.join('#'+str(fid)+' '+safe_line(name,35)
                                                          for fid,name in row['folders']))
                print(neon.fg('    '+safe_line(row['url'],220),'blue'))
            if len(matches)>100:
                print(neon.fg('  Showing first 100 matching links.','yellow'))
        elif choice=='5':
            active=set(_unique_links(store))
            freq=Counter(row['label'] for row in tags.all() if row['url'] in active)
            print('\n'+neon.fg('  ☣ TAG NEBULA // LOCAL RAINBOW CHART','purple',True))
            print(neon.fg(f'  {len(freq)} UNIQUE LABELS  |  {sum(freq.values())} TAG ASSIGNMENTS','green'))
            if not freq:
                print(neon.fg('  No active tags yet. Add one with [2].','yellow'))
                continue
            largest=max(freq.values())
            palette=('green','cyan','purple','pink','yellow','blue')
            for idx,(label,count) in enumerate(sorted(freq.items(),key=lambda x:(-x[1],x[0].casefold()))[:30]):
                color=palette[idx%len(palette)]
                n=max(1,round(32*count/largest))
                print(neon.fg('  '+safe_line(label,26).ljust(27),color)+
                      neon.fg('█'*n,color)+neon.fg(f'  {count} links','green'))
            if len(freq)>30:
                print(neon.fg('  Showing top 30 tags.','yellow'))
            print(neon.fg('  Only current collection links counted. Nothing altered.','cyan'))
        else:print(neon.fg('  Choose a number from 0 through 5.','yellow'))
