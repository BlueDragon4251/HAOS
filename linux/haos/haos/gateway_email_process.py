"""Bounded private mail subprocess lifetime; cancellation always kills and joins."""
import asyncio
import base64
import hashlib
import math
import json
import os
from pathlib import Path
import stat
import time

from .gateway_email import credentials,authority

ERRORS=frozenset({'authority-or-protocol-refused','tls-refused','smtp-authentication-refused','imap-unavailable','transport-unavailable','uid-state-changed','unapproved-sender','unapproved-thread','pre-grant','self-or-automated','unsupported-content','authentication-refused','smtp-temporary-refusal','smtp-permanent-refusal','smtp-outcome-unknown','media-not-approved'})


def command():
    root=Path('/usr/lib/haos');python=root/'hermes/.venv/bin/python'
    for path in [root,root/'haos',root/'hermes',root/'hermes/.venv',python.parent]:
        value=path.lstat()
        if not stat.S_ISDIR(value.st_mode) or value.st_uid!=0 or value.st_mode&0o022:
            raise PermissionError('root-owned private mail worker runtime required')
    value=python.resolve(strict=True).lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_uid!=0 or value.st_mode&0o022:
        raise PermissionError('root-owned private mail interpreter required')
    return [str(python),'-E','-s','-m','haos.gateway_email_worker']


def response(value):
    if not isinstance(value,dict):raise ValueError('bounded mail worker result required')
    if set(value)=={'error'}:
        if not isinstance(value['error'],str) or value['error'] not in ERRORS:raise ValueError('finite private mail diagnostic required')
        return value
    if (set(value)!={'imap_authenticated','smtp_authenticated','uid_validity','uid_next','smtp_message_sent'}
            or value['imap_authenticated'] is not True or value['smtp_authenticated'] is not True
            or value['smtp_message_sent'] is not False
            or any(type(value[key]) is not int or not 0<value[key]<2**32 for key in ('uid_validity','uid_next'))):
        raise ValueError('exact authenticated mailbox state and no-send receipt required')
    return value


def header_response(value,uid,validity):
    from .gateway_email_imap import uid_number
    from .gateway_email_codec import MAX_HEADERS,MAX_RAW
    uid_number(uid);uid_number(validity)
    if isinstance(value,dict) and set(value)=={'error'}:return response(value)
    if (not isinstance(value,dict) or set(value)!={'uid','uid_validity','uid_next','internal_at','size','content_base64','sha256'}
            or type(value['uid']) is not int or value['uid']!=uid
            or type(value['uid_validity']) is not int or value['uid_validity']!=validity
            or type(value['uid_next']) is not int or not uid<value['uid_next']<2**32
            or type(value['internal_at']) not in {int,float} or not math.isfinite(value['internal_at'])
            or not 0<value['internal_at']<=time.time()+300 or type(value['size']) is not int or not 1<=value['size']<=MAX_RAW
            or not isinstance(value['content_base64'],str) or len(value['content_base64'])>4*((MAX_HEADERS+2)//3)
            or not isinstance(value['sha256'],str)):
        raise ValueError('exact bounded private mail header response required')
    try:raw=base64.b64decode(value['content_base64'],validate=True)
    except (ValueError,UnicodeError):raise ValueError('canonical private mail header encoding required') from None
    if (not 1<=len(raw)<=min(MAX_HEADERS,value['size']) or base64.b64encode(raw).decode()!=value['content_base64']
            or hashlib.sha256(raw).hexdigest()!=value['sha256']):
        raise ValueError('private mail header bytes or digest changed')
    return {'uid':uid,'uid_validity':validity,'uid_next':value['uid_next'],'internal_at':value['internal_at'],'size':value['size'],'content':raw}


def search_response(value,page):
    if isinstance(value,dict) and set(value)=={'error'}:return response(value)
    if (not isinstance(value,dict) or set(value)!={'uid_validity','uid_next','after','through','uids'}
            or any(type(value[key]) is not int or value[key]!=page[key] for key in ('uid_validity','after','through'))
            or type(value['uid_next']) is not int or not page['through']<value['uid_next']<2**32
            or not isinstance(value['uids'],list) or len(value['uids'])>1000
            or any(type(uid) is not int or not page['after']<uid<=page['through'] for uid in value['uids'])
            or sorted(set(value['uids']))!=value['uids']):
        raise ValueError('exact complete bounded private mail search response required')
    return value


async def search(value,connector,current,page):
    if (not isinstance(page,dict) or set(page)!={'uid_validity','after','through'}
            or any(type(page[key]) is not int for key in page)
            or not 0<page['uid_validity']<2**32 or not 0<=page['after']<page['through']<2**32
            or page['through']-page['after']>100000):
        raise ValueError('exact bounded private mail UID search page required')
    return await _run(value,connector,current,'search',page=dict(page))


def message_response(raw,uid,validity,header_sha256,route):
    from .gateway_email_codec import MAX_RAW,MAX_HEADERS
    from .gateway_line_ingress import _object
    if not isinstance(raw,bytes):raise ValueError('bounded private mail binary frame required')
    marker=raw.find(b'\n')
    if not 0<marker<=16384:raise ValueError('bounded private mail binary frame required')
    metadata=json.loads(raw[:marker],object_pairs_hook=_object);content=raw[marker+1:]
    if isinstance(metadata,dict) and set(metadata)=={'error'}:
        if content:raise ValueError('mail refusal cannot include body data')
        return response(metadata)
    if (not isinstance(metadata,dict) or set(metadata)!={'uid','uid_validity','uid_next','internal_at','size','approval','sha256','mime'}
            or type(metadata['uid']) is not int or metadata['uid']!=uid
            or type(metadata['uid_validity']) is not int or metadata['uid_validity']!=validity
            or type(metadata['uid_next']) is not int or not uid<metadata['uid_next']<2**32
            or type(metadata['size']) is not int or not 1<=metadata['size']==len(content)<=MAX_RAW
            or type(metadata['internal_at']) not in {int,float} or not math.isfinite(metadata['internal_at'])
            or not 0<metadata['internal_at']<=time.time()+300 or hashlib.sha256(content).hexdigest()!=metadata['sha256']):
        raise ValueError('complete immutable private email resource required')
    from .gateway_email_media import manifest
    if manifest(content)!=metadata['mime']:raise ValueError('exact bounded MIME manifest required')
    approval=metadata['approval']
    if (not isinstance(approval,dict) or set(approval)!={'envelope','binding_id','binding_digest','received_at','header_sha256','rfc_message_id'}
            or approval['binding_id']!=route['binding_id'] or approval['binding_digest']!=route['binding_digest']
            or type(approval['received_at']) not in {int,float} or approval['received_at']!=metadata['internal_at'] or approval['header_sha256']!=header_sha256):
        raise PermissionError('private email body approval changed')
    boundary=content.find(b'\r\n\r\n')
    if not 0<boundary<=MAX_HEADERS or hashlib.sha256(content[:boundary+4]).hexdigest()!=header_sha256:
        raise ValueError('full email changed the previously approved headers')
    return {**metadata,'content':content}


async def message(value,connector,current,uid,validity,header_sha256,route):
    from .gateway_email_imap import uid_number
    import re
    uid_number(uid);uid_number(validity)
    if (not isinstance(header_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',header_sha256)
            or not isinstance(route,dict) or set(route)!={'binding_id','binding_digest'}
            or not isinstance(route['binding_id'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}',route['binding_id'])
            or not isinstance(route['binding_digest'],str) or not re.fullmatch(r'[0-9a-f]{64}',route['binding_digest'])):
        raise ValueError('exact approved private email body route required')
    return await _run(value,connector,current,'message',uid=uid,validity=validity,header_sha256=header_sha256,route=dict(route))


def mailbox_response(value):
    if isinstance(value,dict) and set(value)=={'error'}:return response(value)
    if (not isinstance(value,dict) or set(value)!={'uid_validity','uid_next'}
            or any(type(value[key]) is not int or not 0<value[key]<2**32 for key in value)):
        raise ValueError('exact private mailbox state required')
    return value


async def mailbox(value,connector,current):
    return await _run(value,connector,current,'mailbox')


def smtp_response(result,value,item):
    if isinstance(result,dict) and set(result)=={'error'}:return response(result)
    from .gateway import digest
    from .gateway_email_smtp import identity
    expected='smtp_accept_'+digest([identity(value,item),item['delivery_id'],item['attempt']])
    if (not isinstance(result,dict) or set(result)!={'accepted','receipt','recipient_receipt_verified'}
            or result['accepted'] is not True or result['receipt']!=expected or result['recipient_receipt_verified'] is not False):
        raise ValueError('exact SMTP acceptance receipt required; recipient delivery is not verified')
    return result


async def smtp(value,connector,current,item):
    return await _run(value,connector,current,'smtp',item=item)


async def probe(value,connector,current):
    return await _run(value,connector,current,'probe')


async def headers(value,connector,current,uid,validity):
    from .gateway_email_imap import uid_number
    uid_number(uid);uid_number(validity)
    return await _run(value,connector,current,'headers',uid=uid,validity=validity)


async def _run(value,connector,current,action,*,uid=None,validity=None,page=None,header_sha256=None,route=None,item=None):
    value=credentials(value);current();identity=authority(connector,value)
    payload={'action':action,'connector':connector,'credentials':value,'policy_sha256':identity,'parent_pid':os.getpid()}
    if action=='headers':payload.update(uid=uid,uid_validity=validity)
    elif action=='search':payload['page']=page
    elif action=='message':payload.update(uid=uid,uid_validity=validity,header_sha256=header_sha256,**route)
    elif action=='smtp':payload['reply']=item
    request=json.dumps(payload,ensure_ascii=False).encode()
    if len(request)>(262144 if action=='smtp' else 32768):raise ValueError('bounded private mail worker request required')
    process=None;tasks=[]
    async def collect(stream,limit):
        result=bytearray()
        while chunk:=await stream.read(4096):
            result.extend(chunk)
            if len(result)>limit:raise ValueError('bounded mail worker output exceeded')
        return bytes(result)
    try:
        process=await asyncio.create_subprocess_exec(*command(),cwd='/usr/lib/haos',
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=16384,
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1'})
        output=asyncio.create_task(collect(process.stdout,48*1024*1024+16385 if action=='message' else 131072 if action=='headers' else 16384));errors=asyncio.create_task(collect(process.stderr,16384))
        ended=asyncio.create_task(process.wait());tasks=[output,errors,ended]
        process.stdin.write(request);await process.stdin.drain();process.stdin.close()
        async with asyncio.timeout(35):
            while not ended.done():
                current();authority(connector,value,identity)
                for task in [output,errors]:
                    if task.done() and task.exception() is not None:task.result()
                await asyncio.wait({ended},timeout=.1)
            raw=await output;await errors
            if ended.result()!=0:raise ConnectionError('private mail worker unavailable; inspect account, TLS and retained status')
            current();authority(connector,value,identity)
            from .gateway_line_ingress import _object
            if action=='message':
                result=message_response(raw,uid,validity,header_sha256,route)
                if 'error' not in result:
                    from .gateway_email import PreparedEmailPolicy
                    from .gateway_email_admission import approve
                    from .sandbox import trusted_json
                    expected=approve(PreparedEmailPolicy(trusted_json(Path('/etc/haos/gateways.json'))),connector,value,result)
                    if expected!=result['approval']:raise PermissionError('email body differs from its fresh independent source approval')
                    current();authority(connector,value,identity)
                return result
            decoded=json.loads(raw,object_pairs_hook=_object)
            if action=='smtp':return smtp_response(decoded,value,item)
            if action=='mailbox':return mailbox_response(decoded)
            if action=='search':return search_response(decoded,page)
            return response(decoded) if action=='probe' else header_response(decoded,uid,validity)
    finally:
        if process is not None:
            if process.returncode is None:
                try:process.kill()
                except ProcessLookupError:pass
            await process.wait()
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
