"""Approved MMS metadata and private bytes; remote URLs never become host paths."""
import json
import re

from .gateway import Conflict,digest
from .gateway_media import approved,authorize,MAX_IMAGE_BYTES,describe


def metadata(row,account,message):
    if (not isinstance(row,dict) or row.get('account_sid')!=account or row.get('parent_sid')!=message
            or not isinstance(row.get('sid'),str) or not re.fullmatch(r'ME[0-9a-fA-F]{32}',row['sid'])
            or not isinstance(row.get('content_type'),str) or not 1<=len(row['content_type'])<=256
            or any(ord(c)<32 for c in row['content_type'])):
        raise PermissionError('exact owned MMS media resource required')
    mime=row['content_type'].split(';',1)[0].strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',mime):
        raise ValueError('canonical bounded MMS content type required')
    kind=('image' if mime in {'image/png','image/jpeg'} else 'voice' if mime.startswith('audio/')
        else 'video' if mime in {'video/mp4','video/3gpp','video/3gpp2'} else 'document')
    return {'id':row['sid'],'mime':mime,'kind':kind}


def limit(item):
    # Twilio's pinned Messages MediaUrl contract: supported images 5 MB,
    # other accepted media 500 KB. HAOS model images have a lower 2 MiB cap.
    if item['kind']=='image':return MAX_IMAGE_BYTES
    return 5_000_000 if item['mime']=='image/gif' else 500_000


async def download(adapter,row):
    from .gateway_media_relay import MediaCache
    native=adapter._haos_native;items=row['payload']['media'];values=row['payload']['form']
    if not isinstance(items,list) or not 1<=len(items)<=4 or len(items)!=int(values.get('NumMedia','0')):
        raise ValueError('bounded retained MMS metadata required')
    db=native.inbox.db;cache=MediaCache(native.inbox)
    db.execute('''CREATE TABLE IF NOT EXISTS sms_input_media(
        input_id TEXT NOT NULL,media_sid TEXT NOT NULL,fingerprint TEXT NOT NULL,
        upload_id TEXT NOT NULL,PRIMARY KEY(input_id,media_sid))''')
    result=[];images=0
    for item in items:
        expected=metadata({'sid':item['id'],'account_sid':values['AccountSid'],'parent_sid':values['MessageSid'],
            'content_type':item['mime']},values['AccountSid'],values['MessageSid'])
        if expected!=item:raise PermissionError('retained MMS type changed')
        def current():
            adapter._haos_sms_check();policy=native.policy();policy.current_binding(row)
            authorize(policy,native.connector,row['envelope'],item['kind']);return policy
        policy=current();prior=db.execute('SELECT * FROM sms_input_media WHERE input_id=? AND media_sid=?',(row['id'],item['id'])).fetchone()
        fingerprint=digest([row['binding_digest'],row['fingerprint'],item])
        if prior is not None:
            if prior['fingerprint']!=fingerprint:raise Conflict('MMS resource replay changed metadata or grant')
            cached=cache.replay(policy,prior['upload_id'])
        else:
            cache.capacity()
            data=await adapter._haos_sms_rest.content(values['MessageSid'],item,current)
            meta=describe(data,item['kind'])
            if item['kind']=='image' and item['mime']!='image/'+meta['format']:
                raise ValueError('MMS image content differs from its declared MIME type')
            if item['kind']=='image' and images+len(data)>MAX_IMAGE_BYTES:raise ValueError('MMS images exceed the aggregate model budget')
            cached=cache.put(current(),native.connector,row['envelope'],data,item['kind'])
            db.execute('INSERT INTO sms_input_media VALUES(?,?,?,?)',(row['id'],item['id'],fingerprint,cached['id']))
        if item['kind']=='image':images+=cached['descriptor']['size']
        if images>MAX_IMAGE_BYTES:raise ValueError('MMS images exceed aggregate model budget')
        if cached['id'] not in {x['id'] for x in result}:result.append(cached)
    return result
