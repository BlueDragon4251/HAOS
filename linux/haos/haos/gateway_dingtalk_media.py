"""Durable private DingTalk resource copies, bound to retained source and exact grants."""
import base64
import hashlib
import math
import re
import time

from .gateway import digest,Conflict
from .gateway_dingtalk_admission import Refused
from .gateway_media import MAX_IMAGE_BYTES
from .gateway_dingtalk_resource import specification,classify


async def retained(adapter,row,original):
    from .gateway_media_relay import MediaCache
    from .gateway_dingtalk_resource_process import resource
    native=adapter._haos_native;db=native.inbox.db;value=adapter._haos_dingtalk_value
    cache=MediaCache(native.inbox);result=[];image_ids=set();images=0
    db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_input_media(
        input_id TEXT NOT NULL,resource_index INTEGER NOT NULL,fingerprint TEXT NOT NULL,
        upload_id TEXT NOT NULL,mime TEXT NOT NULL,PRIMARY KEY(input_id,resource_index))''')
    db.execute('''CREATE TABLE IF NOT EXISTS dingtalk_delivery_backoff(
        account_scope TEXT PRIMARY KEY,status TEXT NOT NULL,next_attempt REAL NOT NULL,updated_at REAL NOT NULL)''')
    account=digest([value[key] for key in ['client_id','client_secret','corp_id','robot_code']])
    db.execute('INSERT OR IGNORE INTO dingtalk_delivery_backoff VALUES(?,?,?,?)',(account,'ready',0,time.time()))
    def current():
        adapter._haos_dingtalk_check();policy=native.policy();policy.current_binding(row);return policy
    for index,item in enumerate(original['resources']):
        policy=current();source_fingerprint=digest([row['binding_digest'],row['fingerprint'],original['id'],item])
        prior=db.execute('SELECT * FROM dingtalk_input_media WHERE input_id=? AND resource_index=?',(row['id'],index)).fetchone()
        if prior is not None:
            if (not isinstance(prior['mime'],str) or not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',prior['mime'])
                    or prior['fingerprint']!=digest([source_fingerprint,prior['upload_id'],prior['mime']])):
                raise Conflict('retained DingTalk resource identity, bytes, MIME or grant changed')
            cached=cache.replay(policy,prior['upload_id']);mime=prior['mime']
        else:
            state=db.execute('SELECT status,next_attempt FROM dingtalk_delivery_backoff WHERE account_scope=?',(account,)).fetchone()
            if (state is None or state['status'] not in {'ready','authentication-refused','rate-limited'}
                    or type(state['next_attempt']) not in {int,float} or not math.isfinite(state['next_attempt']) or state['next_attempt']<0):
                raise Conflict('damaged private DingTalk account backoff')
            if state['status']=='authentication-refused':raise Refused('resource-authentication-refused')
            if state['next_attempt']>time.time():raise Refused('resource-rate-limited',min(86400,max(1,math.ceil(state['next_attempt']-time.time()))))
            cache.capacity();raw=original['raw']
            proof={'binding_id':row['binding_id'],'binding_digest':row['binding_digest'],
                'source_base64':base64.b64encode(raw).decode(),'source_sha256':hashlib.sha256(raw).hexdigest(),'resource_index':index}
            approved=specification(value,policy,native.connector,proof,native.inbox.redactor)
            reply=await resource(value,native.connector,current,proof);policy=current()
            if 'error' in reply:
                error=reply['error']
                if error in {'authentication-refused','rate-limited'}:
                    now=time.time();db.execute('UPDATE dingtalk_delivery_backoff SET status=?,next_attempt=?,updated_at=? WHERE account_scope=?',
                        (error,now+reply.get('retry_after',60) if error=='rate-limited' else 0,now,account))
                raise Refused('resource-'+error,reply.get('retry_after',60) if error in {'rate-limited','content-rate-limited'} else 0)
            if specification(value,policy,native.connector,proof,native.inbox.redactor)!=approved:
                raise PermissionError('resource source or grant changed during native read')
            meta=classify(approved,reply['mime'],reply['data'])
            if meta!=reply['descriptor']:raise Conflict('private native resource descriptor changed')
            cached=cache.put(policy,native.connector,row['envelope'],reply['data'],meta['kind']);mime=reply['mime']
            db.execute('INSERT INTO dingtalk_input_media VALUES(?,?,?,?,?)',
                (row['id'],index,digest([source_fingerprint,cached['id'],mime]),cached['id'],mime))
        if cached['envelope_digest']!=digest(row['envelope']) or cached['connector']!=native.connector:
            raise Conflict('retained resource points to another message or connector')
        if cached['descriptor']['kind']=='image' and cached['id'] not in image_ids:
            image_ids.add(cached['id']);images+=cached['descriptor']['size']
        if images>MAX_IMAGE_BYTES:raise Refused('aggregate-image-budget')
        result.append({'resource':dict(item),'index':index,'item':cached,'mime':mime})
    current();return result
