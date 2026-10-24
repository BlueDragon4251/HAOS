"""Owner-bounded SDK history windows; pagination never skips uncommitted input."""
import asyncio
from decimal import Decimal
import logging
import math
import re
import sqlite3
import time

from .gateway import digest, Conflict

_TS=re.compile(r'[1-9][0-9]{0,15}\.[0-9]{6}\Z')
_KINDS={'ready','permission-denied','rate-limited','transport-unavailable','storage-unavailable','invalid-source'}


def timestamp(value):
    if not isinstance(value,str) or not _TS.fullmatch(value):raise ValueError('invalid Slack history timestamp')
    return Decimal(value)


def boundary(binding):
    value=binding.get('since')
    if type(value) is not int or value<=0 or not binding.get('generation'):return None
    seconds,milliseconds=divmod(value,1000)
    return f'{seconds}.{milliseconds*1000+999:06d}'


def setup(db):
    db.execute('''CREATE TABLE IF NOT EXISTS slack_history (
        binding_digest TEXT PRIMARY KEY, floor TEXT NOT NULL, latest TEXT,
        page_cursor TEXT NOT NULL DEFAULT '', next_attempt REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ready', updated_at REAL NOT NULL)''')


def outcome(adapter,key,kind,now,delay=60):
    if kind not in _KINDS:raise ValueError('invalid Slack history status')
    if type(delay) not in {int,float} or not math.isfinite(delay):delay=60
    delay=min(86400,max(1,delay))
    adapter._haos_slack_history_after=now+delay
    adapter._haos_native.inbox.db.execute('UPDATE slack_history SET status=?,next_attempt=?,updated_at=? WHERE binding_digest=?',
        (kind,now+delay,time.time(),key))


async def recover_one(adapter,current_policy,connector,*,now=None):
    from slack_sdk.errors import SlackApiError
    from . import gateway_slack
    now=time.time() if now is None else now
    if now<getattr(adapter,'_haos_slack_history_after',0):return 0
    policy=current_policy()
    grants=[binding for binding in policy.bindings.values() if binding['connector']==connector and boundary(binding) is not None]
    if not grants:return 0
    db=adapter._haos_native.inbox.db;setup(db)
    index=getattr(adapter,'_haos_slack_history_index',0)%len(grants)
    adapter._haos_slack_history_index=index+1
    binding=grants[index];key=digest(binding)
    route={'binding_id':binding['id'],'binding_digest':key}
    db.execute('INSERT OR IGNORE INTO slack_history(binding_digest,floor,updated_at) VALUES(?,?,?)',
        (key,boundary(binding),time.time()))
    row=db.execute('SELECT * FROM slack_history WHERE binding_digest=?',(key,)).fetchone()
    if now<row['next_attempt']:return 0
    try:
        floor=timestamp(row['floor'])
        cursor=row['page_cursor']
        if not isinstance(cursor,str) or len(cursor)>2048 or any(ord(c)<32 for c in cursor):
            raise ValueError('invalid private Slack history cursor')
        latest=row['latest']
        if latest is None:
            seconds,microseconds=divmod(time.time_ns()//1000,1_000_000)
            latest=f'{seconds}.{microseconds:06d}'
            if timestamp(latest)<=floor:return 0
            db.execute('UPDATE slack_history SET latest=?,page_cursor=? WHERE binding_digest=?',(latest,'',key))
            cursor=''
        upper=timestamp(latest)
        if upper<floor:raise ValueError('Slack history window moved backwards')
        client=adapter._team_clients.get(binding['scope'])
        if client is None:raise PermissionError('Slack history workspace is not authenticated')
        params={'channel':binding['chat'],'oldest':str(floor),'latest':latest,'inclusive':True,'limit':15}
        if cursor:params['cursor']=cursor
        with gateway_slack.secret_scope(adapter._haos_secrets,adapter._haos_secret_home):
            if binding['thread']:
                response=await client.conversations_replies(ts=binding['thread'],**params)
            else:response=await client.conversations_history(**params)
        current_policy().current_binding(route)
        messages=response.get('messages');metadata=response.get('response_metadata')
        if metadata is None:metadata={}
        if not isinstance(messages,list) or len(messages)>15 or not isinstance(metadata,dict):
            raise ValueError('invalid Slack history page')
        next_cursor=metadata.get('next_cursor','')
        if next_cursor is None:next_cursor=''
        if type(response.get('has_more',False)) is not bool:raise ValueError('invalid Slack history pagination flag')
        if (not isinstance(next_cursor,str) or len(next_cursor)>2048 or any(ord(c)<32 for c in next_cursor)
                or next_cursor and next_cursor==cursor or response.get('has_more') and not next_cursor):
            raise ValueError('Slack history page did not advance')
        decoded=[]
        for message in messages:
            if not isinstance(message,dict):raise ValueError('invalid Slack history message')
            when=timestamp(message.get('ts'))
            if (not floor<=when<=upper or when>Decimal(str(time.time()+300))
                    or message.get('channel',binding['chat'])!=binding['chat']
                    or message.get('team',binding['scope'])!=binding['scope']
                    or binding['thread'] and message['ts']!=binding['thread'] and message.get('thread_ts')!=binding['thread']):
                raise ValueError('Slack history changed its approved source or window')
            event={**message,'channel':binding['chat'],'team':binding['scope'],'type':'message',
                'channel_type':'im' if binding['chat'].startswith('D') else 'channel'}
            body={'type':'event_callback','team_id':binding['scope'],'event':event}
            decoded.append((when,event,body))
        if len({item[0] for item in decoded})!=len(decoded):raise ValueError('duplicate Slack history identity')
        admitted=0
        for when,event,body in sorted(decoded,key=lambda item:item[0]):
            current=current_policy();current.current_binding(route)
            source=gateway_slack.envelope(adapter,event,body)
            if source is None:continue
            try:matched=current.authorize(connector,source)
            except (PermissionError,ValueError):continue
            start=boundary(matched)
            if start is None or when<=timestamp(start):continue
            native=adapter._haos_native.inbox
            raw_key=native.key(connector,source)
            if native.db.execute('SELECT id FROM native_inbox WHERE id=?',(raw_key,)).fetchone():continue
            native.admit(current,connector,source,body,received_at=float(when));admitted+=1
        # The page cursor changes only after every approved input is durable.
        # Inclusive windows plus overlap cover boundary equality/indexing delay;
        # raw receipts own idempotency independently of provider pagination.
        if next_cursor:
            db.execute('UPDATE slack_history SET page_cursor=? WHERE binding_digest=?',(next_cursor,key))
        else:
            advance=max(floor,timestamp(boundary(binding)),upper-Decimal(300))
            db.execute('UPDATE slack_history SET floor=?,latest=NULL,page_cursor=? WHERE binding_digest=?',
                (f'{advance:.6f}','',key))
        outcome(adapter,key,'ready',now)
        return admitted
    except SlackApiError as error:
        code=error.response.get('error')
        if code=='invalid_cursor' and error.response.status_code in {200,400}:
            db.execute("UPDATE slack_history SET page_cursor='' WHERE binding_digest=?",(key,))
            outcome(adapter,key,'ready',now)
            return 0
        kind='rate-limited' if error.response.status_code==429 else 'permission-denied' if code in {
            'missing_scope','not_in_channel','channel_not_found','invalid_auth','token_revoked','no_permission'} else 'transport-unavailable'
        outcome(adapter,key,kind,now,adapter._retry_after_from_exc(error) or 60)
        raise
    except Exception as error:
        kind=('permission-denied' if isinstance(error,PermissionError) else 'storage-unavailable'
            if isinstance(error,(sqlite3.Error,Conflict)) else 'invalid-source' if isinstance(error,ValueError) else 'transport-unavailable')
        outcome(adapter,key,kind,now)
        raise


async def maintain(adapter,stop,current_policy,connector):
    while not stop.is_set():
        try:
            if adapter.is_connected:await asyncio.wait_for(recover_one(adapter,current_policy,connector),15)
        except Exception as error:logging.warning('Slack history recovery deferred: %s',type(error).__name__)
        try:await asyncio.wait_for(stop.wait(),2)
        except TimeoutError:pass
