"""Retain private Matrix sync pages before acknowledging a transport cursor.

Transport persistence grants no sender/room/mission authority. The public Matrix
factory and independent HAOS message admission are deliberately not enabled.
"""
import asyncio
from contextvars import ContextVar
import inspect
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
from types import MethodType

from .gateway import Conflict,digest

_ACTIVE=ContextVar('haos_matrix_sync_page',default=None)


class DeferredDispatch(ConnectionError):
    def __init__(self):super().__init__('private Matrix sync decoding deferred; retained page available')


class SyncJournal:
    def __init__(self,path,scope):
        if not isinstance(scope,str) or len(scope)!=64 or any(c not in '0123456789abcdef' for c in scope):
            raise ValueError('bound Matrix identity digest required')
        path=Path(path);parent=path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.geteuid() or parent.st_mode&0o077:
            raise PermissionError('Matrix sync directory must belong privately to this identity')
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            own=os.fstat(fd)
            if not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077 or own.st_nlink!=1:
                raise PermissionError('Matrix sync journal must be private, regular and single-link')
        finally:os.close(fd)
        for suffix in ('-wal','-shm'):
            try:own=path.with_name(path.name+suffix).lstat()
            except FileNotFoundError:continue
            if not stat.S_ISREG(own.st_mode) or own.st_uid!=os.geteuid() or own.st_mode&0o077 or own.st_nlink!=1:
                raise PermissionError('untrusted Matrix sync sidecar')
        self.scope=scope;self.db=sqlite3.connect(path,isolation_level=None);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in {0,1}:self.db.close();raise ValueError('unsupported Matrix sync journal')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS matrix_sync_cursor(
            scope TEXT PRIMARY KEY,cursor TEXT,updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS matrix_sync_pages(
            id TEXT PRIMARY KEY,scope TEXT NOT NULL,from_batch TEXT,next_batch TEXT NOT NULL,
            fingerprint TEXT NOT NULL,payload TEXT NOT NULL,authority TEXT NOT NULL,
            initial INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempt INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0,created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS matrix_sync_gaps(
            id TEXT PRIMARY KEY,scope TEXT NOT NULL,page_id TEXT NOT NULL,room_id TEXT NOT NULL,
            before_token TEXT NOT NULL,authority TEXT NOT NULL,created_at REAL NOT NULL);
            PRAGMA user_version=1;''')
        self.db.execute('INSERT OR IGNORE INTO matrix_sync_cursor(scope,updated_at) VALUES(?,?)',(scope,time.time()))

    def close(self):self.db.close()

    @property
    def cursor(self):return self.db.execute('SELECT cursor FROM matrix_sync_cursor WHERE scope=?',(self.scope,)).fetchone()[0]

    def capture(self,payload,authority,*,initial=False,from_batch=None):
        if not isinstance(payload,dict) or not isinstance(authority,dict) or type(initial) is not bool:
            raise ValueError('bounded native sync page and authority snapshot required')
        next_batch=payload.get('next_batch')
        if (not isinstance(next_batch,str) or not 1<=len(next_batch)<=4096 or any(ord(c)<32 for c in next_batch)
                or from_batch is not None and (not isinstance(from_batch,str) or len(from_batch)>4096)):
            raise ValueError('invalid opaque Matrix sync cursor')
        encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        snapshot=json.dumps(authority,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        if len(encoded.encode())>8*1024*1024 or len(snapshot.encode())>65536:
            raise ValueError('Matrix sync capture exceeds private bound')
        fingerprint=digest(payload);key=digest([self.scope,from_batch,next_batch,fingerprint])
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT * FROM matrix_sync_pages WHERE id=?',(key,)).fetchone()
            if old is None:
                if self.cursor!=from_batch:raise Conflict('Matrix sync response belongs to another captured cursor')
                used=(self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0])*self.db.execute('PRAGMA page_size').fetchone()[0]
                if used+len(encoded.encode())+len(snapshot.encode())>64*1024*1024 or self.db.execute('SELECT COUNT(*) FROM matrix_sync_pages').fetchone()[0]>=65536:
                    raise Conflict('private Matrix sync journal capacity reached')
                self.db.execute('INSERT INTO matrix_sync_pages(id,scope,from_batch,next_batch,fingerprint,payload,authority,initial,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (key,self.scope,from_batch,next_batch,fingerprint,encoded,snapshot,int(initial),time.time()))
                # Transport cursor and the complete raw response share this COMMIT.
                self.db.execute('UPDATE matrix_sync_cursor SET cursor=?,updated_at=? WHERE scope=?',(next_batch,time.time(),self.scope))
            self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        return key

    def page(self,key):
        row=self.db.execute('SELECT * FROM matrix_sync_pages WHERE id=? AND scope=?',(key,self.scope)).fetchone()
        if row is None:raise KeyError('unknown private Matrix sync page')
        return {**dict(row),'payload':json.loads(row['payload']),'authority':json.loads(row['authority'])}

    def finish(self,key):
        row=self.page(key)
        if row['state']=='processed':return
        gaps=[]
        for room,data in row['payload'].get('rooms',{}).get('join',{}).items():
            timeline=data.get('timeline',{})
            if timeline.get('limited') is not True:continue
            before=timeline.get('prev_batch')
            if (not isinstance(room,str) or not 1<=len(room)<=1024 or any(ord(c)<32 for c in room)
                    or not isinstance(before,str) or not 1<=len(before)<=4096 or any(ord(c)<32 for c in before)):
                raise ValueError('limited Matrix timeline has no recoverable pagination marker')
            gaps.append((digest([self.scope,key,room,before]),self.scope,key,room,before,
                json.dumps(row['authority'],allow_nan=False),row['created_at']))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('SELECT COUNT(*) FROM matrix_sync_gaps').fetchone()[0]+len(gaps)>4096:
                raise Conflict('Matrix timeline gap queue capacity reached')
            self.db.executemany('INSERT OR IGNORE INTO matrix_sync_gaps(id,scope,page_id,room_id,before_token,authority,created_at) VALUES(?,?,?,?,?,?,?)',gaps)
            self.db.execute("UPDATE matrix_sync_pages SET state='processed',payload='{}',authority='{}' WHERE id=? AND scope=? AND state='pending'",(key,self.scope))
            self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise

    def defer(self,key):
        row=self.page(key);attempt=row['attempt']+1
        self.db.execute("UPDATE matrix_sync_pages SET attempt=?,next_attempt=? WHERE id=? AND scope=? AND state='pending'",
            (attempt,time.time()+min(60,2**min(attempt,6)),key,self.scope))

    def due(self,now=None):
        row=self.db.execute("SELECT id FROM matrix_sync_pages WHERE scope=? AND state='pending' AND next_attempt<=? ORDER BY next_attempt,created_at LIMIT 1",
            (self.scope,time.time() if now is None else now)).fetchone()
        return row[0] if row else None


def active_page():
    """Private receiver context; its snapshot is evidence, never authorization."""
    state=_ACTIVE.get()
    if state is None:raise PermissionError('no retained Matrix sync page is being decoded')
    return state['row']


def verified_crypto(event):
    state=_ACTIVE.get()
    if state is None:raise PermissionError('Matrix event has no retained private decode context')
    value=state['crypto'].get(id(event))
    return value[1] if value is not None and value[0] is event else None


class JournalSyncStore:
    def __init__(self,journal):self.journal=journal
    async def get_next_batch(self):return self.journal.cursor
    async def put_next_batch(self,value):
        if value==self.journal.cursor:return
        state=_ACTIVE.get()
        if (state is None or state.get('journal') is not self.journal
                or state['row']['next_batch']!=value):
            raise Conflict('SDK cannot acknowledge an uncaptured Matrix cursor')
        # Replaying an older retained page never rolls the newer raw transport cursor back.


def protect_dispatch(client):
    if getattr(client,'_haos_strict_sync',False):
        if client._haos_sync_crypto is not getattr(client,'crypto',None):
            raise PermissionError('Matrix crypto identity changed; use a fresh verified client')
        return
    original_dispatch=client.dispatch_manual_event
    original_event=client.dispatch_event
    async def call(self,handler,data):await handler(data)
    def dispatch(self,*args,**kwargs):
        # Include callbacks that the native SDK normally starts as background
        # tasks, including tasks recursively launched by another dispatcher.
        if len(args)>3:
            args=list(args);args[3]=True
        else:kwargs['force_synchronous']=True
        tasks=original_dispatch(*args,**kwargs)
        state=_ACTIVE.get()
        if state is not None:state['tasks'].update(tasks)
        return tasks
    def event_dispatch(self,event,source):
        gate=getattr(self,'_haos_sync_source_gate',None)
        if event is not None and gate is not None and gate(event) is not True:return []
        return original_event(event,source)
    def deserialize(self,cls,data):
        try:return cls.deserialize(data)
        except Exception:raise DeferredDispatch() from None
    client._catch_errors=MethodType(call,client)
    client.dispatch_event=MethodType(event_dispatch,client)
    client.dispatch_manual_event=MethodType(dispatch,client)
    client._try_deserialize=MethodType(deserialize,client)
    if any(client.event_middlewares.values()):raise RuntimeError('unreviewed Matrix event middleware')
    if getattr(client,'crypto',None) is not None:
        from mautrix.client.encryption_manager import DecryptionDispatcher
        from mautrix.types import EventType
        native=client.dispatchers.get(DecryptionDispatcher)
        if native is not None:client.remove_event_handler(EventType.ROOM_ENCRYPTED,native.handle)
        async def decrypt(event):
            # Native default logs/deletes this dispatch obligation on a missing
            # session. Retain it so later to-device keys can unblock a retry.
            decrypted=await client.crypto.decrypt_megolm_event(event)
            stored=await client.crypto.crypto_store.get_group_session(event.room_id,event.content.session_id)
            state=_ACTIVE.get()
            if state is None or stored is None:raise DeferredDispatch()
            descriptor={
                'sender':str(event.sender),'room':str(event.room_id),'event_id':str(event.event_id),
                'device_id':str(event.content.device_id or ''),
                'ed25519':str(stored.signing_key),'curve25519':str(stored.sender_key)}
            state['crypto'][id(decrypted)]=(decrypted,descriptor)
            client.dispatch_event(decrypted,event.source)
        client.add_event_handler(EventType.ROOM_ENCRYPTED,decrypt,wait_sync=True)
    client._haos_sync_crypto=getattr(client,'crypto',None)
    client._haos_strict_sync=True


async def dispatch_page(adapter,client,journal,key):
    lock=getattr(adapter,'_haos_sync_dispatch_lock',None)
    if lock is None:lock=adapter._haos_sync_dispatch_lock=asyncio.Lock()
    async with lock:
        return await _dispatch_page(adapter,client,journal,key)


async def _dispatch_page(adapter,client,journal,key):
    row=journal.page(key)
    if row['state']=='processed':return True
    protect_dispatch(client);client.sync_store=JournalSyncStore(journal)
    state={'row':row,'journal':journal,'tasks':set(),'failed':False,'crypto':{}};token=_ACTIVE.set(state)
    original=adapter._dispatch_sync
    pending_invites=adapter._schedule_pending_invite_joins
    async def strict(_data):
        try:
            tasks=client.handle_sync(_data)
            if inspect.isawaitable(tasks):tasks=await tasks
            state['tasks'].update(tasks or [])
            # Native dispatchers sometimes ignore the tasks returned by nested
            # dispatch. Drain the complete callback tree before compacting input.
            seen=set()
            while state['tasks']-seen:
                batch=state['tasks']-seen;seen.update(batch)
                results=await asyncio.gather(*batch,return_exceptions=True)
                if any(isinstance(result,BaseException) for result in results):state['failed']=True
            if state['failed']:raise DeferredDispatch()
        except asyncio.CancelledError:
            state['failed']=True;raise
        except Exception:
            state['failed']=True;raise DeferredDispatch() from None
    adapter._dispatch_sync=strict
    adapter._schedule_pending_invite_joins=lambda _data:None
    try:
        await adapter._absorb_sync(client,row['payload'],initial=bool(row['initial']))
        if state['failed']:raise DeferredDispatch()
        journal.finish(key);return True
    except BaseException:
        journal.defer(key)
        raise
    finally:
        pending={task for task in state['tasks'] if not task.done()}
        for task in pending:task.cancel()
        if pending:await asyncio.gather(*pending,return_exceptions=True)
        adapter._dispatch_sync=original;adapter._schedule_pending_invite_joins=pending_invites
        _ACTIVE.reset(token)


async def receive_sync(adapter,client,journal,authority,*,initial=False):
    lock=getattr(adapter,'_haos_sync_receive_lock',None)
    if lock is None:lock=adapter._haos_sync_receive_lock=asyncio.Lock()
    # Actual immutable SDK owns authentication, request encoding and response
    # decoding. This API deliberately performs no room/sender authorization.
    async with lock:
        before=journal.cursor
        payload=await asyncio.wait_for(client.sync(since=before,timeout=0,full_state=initial),45)
        key=journal.capture(payload,authority,initial=initial,from_batch=before)
    return await dispatch_page(adapter,client,journal,key)
