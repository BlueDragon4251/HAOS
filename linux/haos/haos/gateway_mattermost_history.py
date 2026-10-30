"""Fixed descending Mattermost history windows, advanced only after raw commits."""
import asyncio
import json
import logging
import sqlite3
import time

from .gateway import Conflict, digest
from .gateway_mattermost import APIError, _ID, capture, channel, post_event, read

KINDS = {'ready','permission-denied','rate-limited','transport-unavailable','storage-unavailable','invalid-source'}


def boundary(binding):
    value = binding.get('since')
    return value if type(value) is int and value > 0 and binding.get('generation') else None


def setup(db):
    db.execute('''CREATE TABLE IF NOT EXISTS mattermost_history (
        binding_digest TEXT PRIMARY KEY, floor INTEGER NOT NULL, ceiling INTEGER,
        before_id TEXT NOT NULL DEFAULT '', next_attempt REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ready', updated_at REAL NOT NULL)''')


def outcome(adapter, key, kind, now, delay=5):
    if kind not in KINDS: raise ValueError('invalid Mattermost history status')
    db = adapter._haos_native.inbox.db
    db.execute('UPDATE mattermost_history SET status=?,next_attempt=?,updated_at=? WHERE binding_digest=?',
        (kind, now+delay, time.time(), key))
    adapter._haos_mm_history_after = now+delay


async def recover_one(adapter, current_policy, connector, *, now=None):
    now = time.time() if now is None else now
    if now < getattr(adapter, '_haos_mm_history_after', 0): return 0
    policy = current_policy()
    bindings = [b for b in policy.bindings.values() if b['connector'] == connector and boundary(b) is not None]
    if not bindings: return 0
    index = getattr(adapter, '_haos_mm_history_index', 0) % len(bindings)
    adapter._haos_mm_history_index = index+1
    binding = bindings[index]; key = digest(binding)
    route = {'binding_id': binding['id'], 'binding_digest': key}
    db = adapter._haos_native.inbox.db; setup(db)
    db.execute('INSERT OR IGNORE INTO mattermost_history(binding_digest,floor,updated_at) VALUES(?,?,?)',
        (key,boundary(binding),time.time()))
    row = db.execute('SELECT * FROM mattermost_history WHERE binding_digest=?',(key,)).fetchone()
    if now < row['next_attempt']: return 0
    try:
        info = await channel(adapter,binding)
        path = 'channels/'+binding['chat']+'/posts?per_page=100'
        if row['before_id']:
            if not _ID.fullmatch(row['before_id']): raise ValueError('invalid Mattermost history cursor')
            path += '&before='+row['before_id']
        try:
            page = await read(adapter,binding,path)
        except APIError as error:
            if row['before_id'] and error.status==404:
                # A deleted remote anchor must not strand already retained input.
                # Restart from the same floor; existing raw receipts deduplicate.
                db.execute("UPDATE mattermost_history SET ceiling=NULL,before_id='' WHERE binding_digest=?",(key,))
            raise
        current_policy().current_binding(route)
        order, posts = page.get('order'), page.get('posts')
        if (not isinstance(order,list) or len(order)>100 or not isinstance(posts,dict)
                or len(posts)>100 or any(not isinstance(i,str) or not _ID.fullmatch(i) for i in order)
                or len(set(order)) != len(order) or set(order) != set(posts)):
            raise ValueError('invalid Mattermost ordered history page')
        ordered = []
        for identity in order:
            post = posts[identity]
            if (not isinstance(post,dict) or post.get('id') != identity or post.get('channel_id') != binding['chat']
                    or type(post.get('create_at')) is not int or post['create_at'] <= 0
                    or post['create_at'] > time.time()*1000+300000):
                raise ValueError('Mattermost history changed its source or time')
            ordered.append(post)
        if any(a['create_at']<b['create_at'] for a,b in zip(ordered,ordered[1:])):
            raise ValueError('Mattermost history order moved forward')
        if row['before_id'] in order: raise ValueError('Mattermost history cursor did not advance')
        ceiling = row['ceiling']
        if ceiling is None:
            # Persist the first page upper boundary before recording any input.
            ceiling = ordered[0]['create_at'] if ordered else time.time_ns()//1_000_000
            db.execute('UPDATE mattermost_history SET ceiling=? WHERE binding_digest=?',(ceiling,key))
        if any(post['create_at']>ceiling for post in ordered):
            raise ValueError('Mattermost history escaped its fixed window')
        admitted = 0
        for post in reversed(ordered):
            current_policy().current_binding(route)
            if post['create_at'] <= boundary(binding) or post['create_at'] < row['floor']:
                continue
            if (post.get('root_id') or '') != binding['thread']:
                continue
            event = {'event':'posted','data':{'post':json.dumps(post,ensure_ascii=False),'channel_type':info['type']}}
            parsed = post_event(event)
            if parsed is None or parsed['user_id'] != binding['sender']: continue
            # Completed/previously captured originals must not replay as edited input.
            envelope = {'platform':'mattermost','scope':binding['scope'],'chat':binding['chat'],
                'thread':binding['thread'],'message_id':post['id']}
            raw_key = adapter._haos_native.inbox.key(connector,envelope)
            if db.execute('SELECT 1 FROM native_inbox WHERE id=?',(raw_key,)).fetchone(): continue
            if await capture(adapter,event) is not None: admitted += 1
        current_policy().current_binding(route)
        done = len(ordered)<100 or ordered[-1]['create_at']<row['floor']
        if done:
            # Keep an inclusive overlap for delayed indexing and equal-millisecond posts.
            floor = max(boundary(binding),ceiling-300000)
            db.execute("UPDATE mattermost_history SET floor=?,ceiling=NULL,before_id='' WHERE binding_digest=?",(floor,key))
        else:
            db.execute('UPDATE mattermost_history SET before_id=? WHERE binding_digest=?',(ordered[-1]['id'],key))
        outcome(adapter,key,'ready',now)
        return admitted
    except Exception as error:
        kind = ('permission-denied' if isinstance(error,PermissionError) or isinstance(error,APIError) and error.status in {401,403,404}
            else 'rate-limited' if isinstance(error,APIError) and error.status==429
            else 'storage-unavailable' if isinstance(error,(sqlite3.Error,OSError,Conflict)) and not isinstance(error,APIError)
            else 'invalid-source' if isinstance(error,ValueError) else 'transport-unavailable')
        delay = error.retry_after if isinstance(error,APIError) and error.status==429 else 5
        outcome(adapter,key,kind,now,delay)
        raise


async def maintain(adapter, stop, current_policy, connector):
    while not stop.is_set():
        try:
            if adapter.is_connected:
                await asyncio.wait_for(recover_one(adapter,current_policy,connector),30)
        except Exception as error:
            logging.warning('Mattermost history deferred: %s',type(error).__name__)
        try: await asyncio.wait_for(stop.wait(),2)
        except TimeoutError: pass
