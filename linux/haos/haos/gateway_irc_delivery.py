"""Prepared native IRC writes with durable intent and correlated server echoes."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
import json
import re
import secrets
import time
from types import MethodType

from .gateway import digest
from .gateway_irc_witness import Witness,DELIVERY_CAPS

_ACTIVE=ContextVar('haos_irc_outbox_authority',default=None)
_HASH=re.compile(r'[0-9a-f]{64}\Z')


class Publisher:
    def __init__(self,adapter):
        self.adapter=adapter;self.boundary=adapter._haos_irc_transport
        if self.boundary.writer is not None:raise PermissionError('IRC delivery capabilities must precede connection')
        self.boundary.required=self.boundary.required|DELIVERY_CAPS
        self.identity=digest(self.boundary.value);self.closed=False;self.lock=asyncio.Lock();self._echo_seconds=15;self.active=set()
        self.db=adapter._haos_native.inbox.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS irc_delivery_intents (
            delivery_id TEXT NOT NULL, attempt INTEGER NOT NULL, connector TEXT NOT NULL,
            identity TEXT NOT NULL, binding_digest TEXT NOT NULL, content_digest TEXT NOT NULL,
            state TEXT NOT NULL, chunk_count INTEGER NOT NULL, receipts TEXT NOT NULL,
            updated_at REAL NOT NULL, PRIMARY KEY(delivery_id,attempt))''')
        if 'receipt' not in {row[1] for row in self.db.execute('PRAGMA table_info(irc_delivery_intents)')}:
            self.db.execute("ALTER TABLE irc_delivery_intents ADD COLUMN receipt TEXT NOT NULL DEFAULT ''")
        self.db.execute("UPDATE irc_delivery_intents SET state='uncertain',updated_at=? WHERE identity=? AND state='writing'",
            (time.time(),self.identity))
        self.witness=Witness(self.boundary,lambda ticket:self.current(ticket.authority))
        self.original=type(adapter).send
        async def wire(_self,line):return await self.write(line)
        async def send(_self,chat,content,reply_to=None,metadata=None):return await self.send(chat,content,reply_to,metadata)
        adapter._send_raw=MethodType(wire,adapter);adapter.send=MethodType(send,adapter)

    def current(self,binding):
        boundary=self.boundary;boundary.current()
        if (self.closed or digest(boundary.value)!=self.identity or not boundary.confirmed
                or not DELIVERY_CAPS<=boundary.capabilities or boundary.writer is None or boundary.writer.is_closing()):
            raise PermissionError('IRC has no current private echo-confirmed outbox connection')
        policy=self.adapter._haos_native.policy()
        policy.current_binding({'binding_id':binding['id'],'binding_digest':digest(binding)})
        if (binding['connector']!=self.adapter._haos_native.connector or binding['scope']!=boundary.server
                or binding['chat']!=boundary.value['channel'] or binding['thread'] or 'read' not in binding['capabilities']):
            raise PermissionError('IRC exact current owner channel read grant required')

    async def write(self,line):
        state=_ACTIVE.get()
        if state is None or state['publisher'] is not self:raise PermissionError('IRC raw write has no current outbox capability')
        self.current(state['binding'])
        index=len(state['receipts'])
        if (index>=len(state['lines']) or line!=state['lines'][index]
                or len(line.encode())>510 or any(c in line for c in '\r\n\0')):
            raise PermissionError('native IRC write changed approved target, content or chunk order')
        label='haos_'+digest([state['delivery'],state['attempt'],index,state['nonce']])[:48]
        ticket=self.witness.register(label,state['binding']['chat'],state['chunks'][index],state['binding'])
        try:
            self.current(state['binding'])
            # The durable writing row precedes every possible socket side effect.
            state['dispatched']=True
            self.boundary.writer.write(('@label='+label+' '+line+'\r\n').encode())
            await asyncio.wait_for(self.boundary.writer.drain(),10)
            receipt=await asyncio.wait_for(ticket.future,self._echo_seconds)
            self.current(state['binding']);state['receipts'].append(receipt)
            self.db.execute('UPDATE irc_delivery_intents SET receipts=?,updated_at=? WHERE delivery_id=? AND attempt=?',
                (json.dumps(state['receipts']),time.time(),state['delivery'],state['attempt']))
        finally:self.witness.release(ticket)

    def result(self,success=False,receipt=None):
        from gateway.platforms.base import SendResult
        return SendResult(success=success,message_id=receipt,
            error=None if success else 'IRC server acceptance unavailable; do not resend an uncertain reply',
            raw_response={'haos_confirmation':'irc-server-echo','recipient_receipt_verified':False,
                'haos_delivery':'server-accepted' if success else 'uncertain'})

    async def send(self,chat,content,reply_to=None,metadata=None):
        fields={'haos_scope','haos_binding','haos_delivery_id','haos_delivery_attempt'}
        if (not isinstance(metadata,dict) or not fields<=set(metadata)
                or set(metadata)-fields-{'notify','thread_id'} or metadata.get('notify',True) is not True
                or metadata.get('thread_id','') or not isinstance(metadata['haos_binding'],dict)
                or set(metadata['haos_binding'])!={'binding_id','binding_digest'}
                or not isinstance(metadata['haos_binding']['binding_id'],str)
                or not isinstance(metadata['haos_binding']['binding_digest'],str)
                or not _HASH.fullmatch(metadata['haos_binding']['binding_digest'])
                or not isinstance(metadata['haos_delivery_id'],str) or not _HASH.fullmatch(metadata['haos_delivery_id'])
                or type(metadata['haos_delivery_attempt']) is not int or not 1<=metadata['haos_delivery_attempt']<=5
                or not isinstance(content,str) or not content.strip() or len(content.encode())>32000
                or any(ord(c)<32 and c not in '\n\t' or ord(c)==127 for c in content) or reply_to is not None and (not isinstance(reply_to,str) or not _HASH.fullmatch(reply_to))):
            raise PermissionError('exact bounded IRC owner outbox identity and attempt required')
        binding=deepcopy(self.adapter._haos_native.policy().current_binding(metadata['haos_binding']))
        self.current(binding)
        if chat!=binding['chat'] or metadata['haos_scope']!=binding['scope']:
            raise PermissionError('IRC outbox target or server changed')
        if self.adapter._haos_native.inbox.redactor.text(content)!=content:
            raise PermissionError('IRC outbox contains a private credential alias')
        async with self.lock:
            self.current(binding)
            key=metadata['haos_delivery_id'];attempt=metadata['haos_delivery_attempt'];body=digest(content)
            previous=self.db.execute('SELECT * FROM irc_delivery_intents WHERE delivery_id=? ORDER BY attempt',(key,)).fetchall()
            for row in previous:
                if row['identity']!=self.identity or row['binding_digest']!=digest(binding) or row['content_digest']!=body:
                    raise PermissionError('IRC outbox identity, owner grant or content changed')
                if row['state']=='confirmed':
                    receipt='irc_echo_'+digest([self.boundary.server,key,json.loads(row['receipts'])])
                    if not row['receipt']:
                        self.db.execute('UPDATE irc_delivery_intents SET receipt=? WHERE delivery_id=? AND attempt=?',
                            (receipt,key,row['attempt']))
                    return self.result(True,receipt)
                if row['attempt']==attempt:return self.result()
            if previous and attempt<=max(row['attempt'] for row in previous):
                raise PermissionError('stale IRC outbox attempt')
            chunks=self.adapter._split_message(content,chat)
            lines=['PRIVMSG '+chat+' :'+chunk for chunk in chunks]
            if not chunks or len(chunks)>64 or any(not chunk or len(line.encode())>510
                    or any(c in line for c in '\r\n\0') for chunk,line in zip(chunks,lines)):
                raise PermissionError('IRC reply exceeds bounded native wire chunks')
            self.db.execute('INSERT INTO irc_delivery_intents '
                '(delivery_id,attempt,connector,identity,binding_digest,content_digest,state,chunk_count,receipts,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (key,attempt,self.adapter._haos_native.connector,self.identity,digest(binding),body,'writing',len(chunks),'[]',time.time()))
            state={'publisher':self,'binding':binding,'delivery':key,'attempt':attempt,'chunks':chunks,'lines':lines,
                'receipts':[],'dispatched':False,'nonce':secrets.token_hex(32)}
            token=_ACTIVE.set(state);old_writer=self.adapter._writer
            task=asyncio.current_task();self.active.add(task)
            try:
                self.adapter._writer=self.boundary.writer
                result=await self.original(self.adapter,chat,content,reply_to=reply_to,metadata=None)
                self.current(binding)
                if result.success is not True or len(state['receipts'])!=len(chunks):
                    raise ConnectionError('IRC native send lacks complete correlated echoes')
                if len(set(state['receipts']))!=len(chunks):raise ConnectionError('IRC repeated server message identity')
                receipt='irc_echo_'+digest([self.boundary.server,key,state['receipts']])
                self.db.execute("UPDATE irc_delivery_intents SET state='confirmed',receipt=?,updated_at=? WHERE delivery_id=? AND attempt=?",
                    (receipt,time.time(),key,attempt))
                return self.result(True,receipt)
            except BaseException as error:
                self.db.execute("UPDATE irc_delivery_intents SET state='uncertain',updated_at=? WHERE delivery_id=? AND attempt=?",
                    (time.time(),key,attempt))
                if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
                return self.result()
            finally:
                self.adapter._writer=old_writer;_ACTIVE.reset(token);self.active.discard(task)

    async def close(self):
        self.closed=True;self.witness.close()
        tasks=[task for task in self.active if task is not asyncio.current_task()]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
