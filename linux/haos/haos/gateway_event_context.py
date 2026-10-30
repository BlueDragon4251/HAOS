"""Controller-origin event context for transports with task rather than chat semantics."""
import hashlib
import json
import re

from .store import Conflict

KINDS=frozenset({'gateway.receipt','gateway.answer-unconfirmed','mission.request','mission.claimed','mission.completed',
    'mission.failed','mission.blocked','mission.cancelled','mission.paused','mission.resumed'})
STATES=frozenset({'queued','running','waiting','blocked','failed','completed','cancelled'})
HASH=re.compile('[0-9a-f]{64}\\Z')


def snapshot(store,mission_id,kind,source,*,request_id=None,request_method=None):
    if kind not in KINDS or not isinstance(source,str) or not 1<=len(source)<=256:raise ValueError('closed controller gateway event required')
    mission=store.get(mission_id)
    result={'version':1,'mission_id':mission_id,'kind':kind,'source_event':source,'state':mission['state'],'phase':mission['phase'],
        'request_id':request_id,'request_method':request_method}
    validate({**result,'part':0,'parts':1,'total_bytes':0,'content_sha256':'0'*64,'group_sha256':'0'*64})
    return result


def validate(value):
    fields={'version','mission_id','kind','source_event','state','phase','request_id','request_method','part','parts','total_bytes','content_sha256','group_sha256'}
    if (not isinstance(value,dict) or set(value)!=fields or type(value['version']) is not int or value['version']!=1
            or not isinstance(value['kind'],str) or value['kind'] not in KINDS
            or not isinstance(value['state'],str) or value['state'] not in STATES
            or any(not isinstance(value[k],str) or not 1<=len(value[k])<=256 or any(ord(c)<32 for c in value[k]) for k in ['mission_id','source_event','phase'])
            or any(value[k] is not None and (not isinstance(value[k],str) or not 1<=len(value[k])<=256 or any(ord(c)<32 for c in value[k])) for k in ['request_id','request_method'])
            or type(value['part']) is not int or type(value['parts']) is not int or not 0<=value['part']<value['parts']<=65536
            or type(value['total_bytes']) is not int or not 0<=value['total_bytes']<=64*1024*1024
            or any(not isinstance(value[k],str) or not HASH.fullmatch(value[k]) for k in ['content_sha256','group_sha256'])):
        raise Conflict('damaged controller gateway event context')
    return value


def retain(store,delivery_id,context,content):
    validate(context)
    if hashlib.sha256(content.encode()).hexdigest()!=context['content_sha256']:raise Conflict('controller chunk changed before event context commit')
    encoded=json.dumps(context,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    if len(encoded.encode())>4096:raise ValueError('bounded controller event context required')
    checksum=hashlib.sha256(encoded.encode()).hexdigest()
    existing=store.db.execute('SELECT metadata,sha256 FROM gateway_delivery_context WHERE delivery_id=?',(delivery_id,)).fetchone()
    if existing is not None:
        if tuple(existing)!=(encoded,checksum):raise Conflict('controller event changed a queued delivery context')
    else:store.db.execute('INSERT INTO gateway_delivery_context VALUES(?,?,?)',(delivery_id,encoded,checksum))


def load(store,delivery):
    row=store.db.execute('SELECT metadata,sha256 FROM gateway_delivery_context WHERE delivery_id=?',(delivery['id'],)).fetchone()
    if row is None:raise Conflict('task transport delivery lacks a committed controller event context')
    encoded,checksum=row
    if (not isinstance(encoded,str) or not 1<=len(encoded.encode())<=4096 or not isinstance(checksum,str)
            or hashlib.sha256(encoded.encode()).hexdigest()!=checksum):raise Conflict('controller gateway context proof changed')
    try:value=json.loads(encoded)
    except (ValueError,RecursionError):raise Conflict('invalid controller gateway context') from None
    validate(value)
    if (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)!=encoded
            or hashlib.sha256(delivery['content'].encode()).hexdigest()!=value['content_sha256']):
        raise Conflict('controller delivery content no longer matches its event context')
    mission=store.db.execute('SELECT mission_id FROM gateway_routes WHERE id=?',(delivery['route_id'],)).fetchone()
    if mission is None or mission[0]!=value['mission_id']:raise Conflict('controller event changed mission route')
    return value
