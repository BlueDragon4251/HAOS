"""Private FULL-journal decisions for exact upload or media-message parts."""
import asyncio
import json
import math
import re
import time

from .gateway import Conflict,digest
from .gateway_dingtalk_reply_process import ERRORS
from .gateway_line_ingress import _object
from .gateway_dingtalk_admission import finite

TABLES={'upload':'dingtalk_upload_intents','reply':'dingtalk_media_reply_intents'}


class Journal:
    def __init__(self,adapter,operation):
        if operation not in TABLES:raise ValueError('reviewed private part operation required')
        self.adapter=adapter;self.native=adapter._haos_native;self.db=self.native.inbox.db
        self.table=TABLES[operation];self.operation=operation;self.scope=digest([self.native.connector,adapter._haos_dingtalk_value])
        self.lock=asyncio.Lock()
        self.db.execute(f'''CREATE TABLE IF NOT EXISTS {self.table}(
            delivery_id TEXT NOT NULL,part INTEGER NOT NULL,attempt INTEGER NOT NULL,connector TEXT NOT NULL,
            credential_scope TEXT NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,
            receipt_sha256 TEXT NOT NULL,error TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
            PRIMARY KEY(delivery_id,part,attempt))''')
        self.db.execute(f"UPDATE {self.table} SET state='uncertain' WHERE state='writing' AND connector=? AND credential_scope=?",
            (self.native.connector,self.scope))

    def current(self,binding,authority):
        self.adapter._haos_dingtalk_publisher.current(binding,authority)
        if binding.get('allow_outbound_media') is not True:raise PermissionError('current separate output/read approval required')

    def backoff(self,error,delay):
        publisher=self.adapter._haos_dingtalk_publisher;before=publisher.health();now=time.time()
        state='authentication-refused' if before['status']=='authentication-refused' or error=='authentication-refused' else 'rate-limited'
        deadline=max(before['next_attempt'],now+max(60,delay) if error=='rate-limited' else 0)
        self.db.execute('UPDATE dingtalk_delivery_backoff SET status=?,next_attempt=?,updated_at=? WHERE account_scope=?',
            (state,deadline,now,publisher.account_scope))

    def rejected(self,error):
        state=self.adapter._haos_dingtalk_publisher.health()
        delay=max(0,min(86400,math.ceil(state['next_attempt']-time.time()))) if error=='rate-limited' else 0
        return {'state':'rejected','error':error,'retry_after':delay}

    async def perform(self,binding,delivery_id,attempt,part,fingerprint,check_response,invoke,authority):
        if (not isinstance(delivery_id,str) or not re.fullmatch('[0-9a-f]{64}',delivery_id)
                or not isinstance(fingerprint,str) or not re.fullmatch('[0-9a-f]{64}',fingerprint)
                or type(attempt) is not int or not 1<=attempt<=5 or type(part) is not int
                or not 0<=part<(8 if self.operation=='upload' else 4)):
            raise ValueError('bounded exact private part delivery and attempt required')
        def current():self.current(binding,authority)
        async with self.lock:
            current()
            previous=self.db.execute(f'SELECT * FROM {self.table} WHERE delivery_id=? AND part=? ORDER BY attempt',(delivery_id,part)).fetchall()
            for index,row in enumerate(previous):
                if (row['connector']!=self.native.connector or row['credential_scope']!=self.scope or row['fingerprint']!=fingerprint
                        or type(row['attempt']) is not int or row['attempt']!=index+1 or not 1<=row['attempt']<=5
                        or any(type(row[key]) not in {int,float} or not math.isfinite(row[key]) or row[key]<=0 for key in ['created_at','updated_at'])):
                    raise Conflict('private part changed account, source, grant, artifact or native wire intent')
                if row['state']=='confirmed':
                    if (index!=len(previous)-1 or row['error'] or not isinstance(row['receipt'],str) or not 1<=len(row['receipt'])<=32768
                            or digest([fingerprint,row['receipt']])!=row['receipt_sha256']):
                        raise Conflict('damaged private part acceptance proof')
                    result=json.loads(row['receipt'],object_pairs_hook=_object,parse_constant=finite)
                    if not isinstance(result,dict) or result.get('state')!='confirmed' or json.dumps(result,sort_keys=True,separators=(',',':'))!=row['receipt']:
                        raise Conflict('noncanonical private part acceptance proof')
                    check_response(result)
                elif (row['state'] not in {'writing','uncertain','rejected','owner-retry-approved'}
                        or row['receipt'] or row['receipt_sha256']
                        or row['state']=='rejected' and row['error'] not in ERRORS
                        or row['state']!='rejected' and row['error']):
                    raise Conflict('damaged private part decision')
            confirmed=next((row for row in previous if row['state']=='confirmed'),None)
            if confirmed is not None:
                return check_response(json.loads(confirmed['receipt'],object_pairs_hook=_object,parse_constant=finite))
            if any(row['state'] in {'writing','uncertain'} for row in previous):return {'state':'uncertain'}
            matched=next((row for row in previous if row['attempt']==attempt),None)
            if matched is not None:return self.rejected(matched['error'] or 'authority-or-protocol-refused')
            if (previous and previous[-1]['attempt']+1!=attempt or not previous and attempt!=1):
                raise Conflict('sequential approved private part attempt required')
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0]
            if (len(previous)>=5 or self.db.execute(f'SELECT COUNT(*) FROM {self.table}').fetchone()[0]>=65536
                    or pages*self.db.execute('PRAGMA page_size').fetchone()[0]>=64*1024*1024):
                raise Conflict('private part journal full; owner recovery required')
            current();now=time.time();account=self.adapter._haos_dingtalk_publisher.health()
            blocked=account['status']=='authentication-refused' or account['next_attempt']>now
            error='authentication-refused' if account['status']=='authentication-refused' else 'rate-limited'
            if not blocked and account['status']=='rate-limited':
                self.db.execute("UPDATE dingtalk_delivery_backoff SET status='ready',next_attempt=0,updated_at=? WHERE account_scope=?",
                    (now,self.adapter._haos_dingtalk_publisher.account_scope))
            self.db.execute(f'INSERT INTO {self.table} VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (delivery_id,part,attempt,self.native.connector,self.scope,fingerprint,'rejected' if blocked else 'writing',
                    '','',error if blocked else '',now,now))
            if blocked:return self.rejected(error)
            try:
                result=await invoke(current);current();result=check_response(result)
                if result['state'] not in {'confirmed','rejected','uncertain'}:raise Conflict('finite native part decision required')
                stored=json.dumps(result,sort_keys=True,separators=(',',':')) if result['state']=='confirmed' else ''
                self.db.execute(f'UPDATE {self.table} SET state=?,receipt=?,receipt_sha256=?,error=?,updated_at=? WHERE delivery_id=? AND part=? AND attempt=?',
                    (result['state'],stored,digest([fingerprint,stored]) if stored else '',result.get('error',''),time.time(),delivery_id,part,attempt))
                if result.get('error') in {'authentication-refused','rate-limited'}:
                    self.backoff(result['error'],result['retry_after'])
                return result
            except BaseException as error:
                self.db.execute(f"UPDATE {self.table} SET state='uncertain',receipt='',receipt_sha256='',error='',updated_at=? WHERE delivery_id=? AND part=? AND attempt=?",
                    (time.time(),delivery_id,part,attempt))
                if isinstance(error,(asyncio.CancelledError,PermissionError,Conflict)):raise
                return {'state':'uncertain'}
