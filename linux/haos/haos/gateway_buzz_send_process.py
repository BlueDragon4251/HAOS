"""One fixed CLI send with verified original custody before native publication."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import struct
import time

from .gateway_buzz import HEX,credentials
from .gateway_buzz_crypto import command,verify

GUARD='HAOS_BUZZ_APPROVAL_SOCKET-v1: bounded signed original plus one-byte approval before native message submission'


def files(value,item):
    from .gateway_buzz_upload import descriptor
    parts=item.get('attachments',[])
    if not isinstance(parts,list) or len(parts)>4:raise PermissionError('at most four sealed uploaded Buzz files required')
    result=[];names=set()
    for part in parts:
        if (not isinstance(part,dict) or set(part)!={'descriptor','name'} or not isinstance(part['name'],str)
                or not 1<=len(part['name'])<=120 or part['name'].startswith('.')
                or any(not(c.isascii() and (c.isalnum() or c in '._-')) for c in part['name']) or part['name'] in names):
            raise PermissionError('distinct bounded inert Buzz result filenames required')
        names.add(part['name']);result.append({'descriptor':descriptor(value,part['descriptor']),'name':part['name']})
    return result


def body(value,item):
    result=item['content']
    for part in files(value,item):
        desc=part['descriptor'];kind=desc['type'].split('/')[0]
        label='!['+kind+']' if kind in {'image','video'} else '['+part['name']+']'
        result+='\n'+label+'('+desc['url']+')'
    return result


def media_tags(value,item,tags):
    parts=files(value,item);actual=[tag for tag in tags if tag[0]=='imeta']
    if len(parts)!=len(actual):return False
    for part,tag in zip(parts,actual):
        desc=part['descriptor'];expected=['imeta','url '+desc['url'],'m '+desc['type'],'x '+desc['sha256'],'size '+str(desc['size'])]
        for key in ['dim','blurhash','thumb']:
            if desc.get(key) is not None:expected.append(key+' '+desc[key])
        if desc.get('duration') is not None:
            if len(tag)!=len(expected)+2 or not tag[-2].startswith('duration '):return False
            try:duration=float(tag[-2][9:])
            except ValueError:return False
            if duration!=desc['duration']:return False
            tag=tag[:-2]+tag[-1:]
        expected.append('filename '+part['name'])
        if tag!=expected:return False
    return True


def target(value,item):
    fields={'channel','anchor','thread','content','kind','allowed_mentions','explicit_mentions'}
    if (not isinstance(item,dict) or not fields<=set(item)<=fields|{'attachments'} or item['channel'] not in value['channels']
            or any(not isinstance(item[key],str) or not HEX.fullmatch(item[key]) for key in ['anchor','thread'])
            or type(item['kind']) is not int or item['kind'] not in {9,45003}
            or not isinstance(item['content'],str) or not 1<=len(item['content'].strip().encode())<=32000
            or len(item['content'].encode())>32000
            or any(ord(c)<32 and c not in '\n\r\t' or ord(c)==127 for c in item['content'])):
        raise PermissionError('one exact bounded owner-approved Buzz reply target required')
    for key in ['allowed_mentions','explicit_mentions']:
        parts=item[key]
        if (not isinstance(parts,list) or len(parts)>2 or any(not isinstance(part,str) or not HEX.fullmatch(part) for part in parts)
                or len(set(parts))!=len(parts)):raise PermissionError('bounded explicit Buzz notification identities required')
    if not set(item['explicit_mentions'])<=set(item['allowed_mentions']):raise PermissionError('Buzz mention lacks separate reply recipient authority')
    if len(body(value,item).encode())>32000:raise PermissionError('bounded complete Buzz message including uploaded references required')
    args=['messages','send','--channel',item['channel'],'--content','-','--reply-to',item['anchor']]
    if item['kind']!=9:args+=['--kind',str(item['kind'])]
    for public in item['explicit_mentions']:args+=['--mention',public]
    return args


async def send(value,item,*,home,current,retain,redactor,replay=None):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value);args=target(value,item)
    if not callable(current) or not callable(retain):raise PermissionError('current sealed delivery authority and durable signed original custody required')
    current()
    from .gateway_line_profile import _directory
    home=Path(home);_directory(home)
    if redactor.text(item['content'])!=item['content']:raise PermissionError('private Buzz credential reflection refused')
    from plugins.platforms.buzz.nostr_auth import public_key_hex
    if public_key_hex(value['private_key'])!=value['public_key']:raise PermissionError('native private Buzz reply identity mismatch')
    program=command('buzz');metadata=json.loads((Path(program).parent/'source.json').read_text())
    if metadata.get('prepublish_guard')!=GUARD:raise PermissionError('installed Buzz program lacks reviewed durable prepublication guard')
    replay_event=None
    if replay is not None:
        if metadata.get('signed_replay')!='HAOS_BUZZ_REPLAY_FD-v1: bounded SDK-verified original from inherited descriptor, exact own identity, same prepublication guard, no new signature':
            raise PermissionError('installed Buzz program lacks reviewed immutable signed replay')
        replay_event=await verify(replay);current()
    name='haos-buzz-'+secrets.token_hex(32);process=None;tasks=[];clients=set();pid_ready=asyncio.Event()
    state={'used':False,'ack':False,'event':None,'error':'prepublication-refused'}
    async def approve(reader,writer):
        client=asyncio.current_task();clients.add(client)
        try:
            async with asyncio.timeout(10):
                await pid_ready.wait();current()
                peer=struct.unpack('3i',writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if process is None or peer!=(process.pid,os.geteuid(),os.getegid()) or state['used']:
                    raise PermissionError('one exact private native CLI peer process required')
                state['used']=True
                length=int.from_bytes(await reader.readexactly(4),'big')
                if not 1<=length<=1048576:raise PermissionError('bounded signed Buzz original required')
                raw=await reader.readexactly(length);event=await verify(raw);current()
                from .gateway_buzz_admission import thread
                from plugins.platforms.buzz.adapter import _event_reply_parent_id
                channels=[tag[1] for tag in event['tags'] if tag[0]=='h' and len(tag)>=2]
                mentions=[tag[1] for tag in event['tags'] if tag[0]=='p' and len(tag)>=2]
                links=[tag[1] for tag in event['tags'] if tag[0]=='e' and len(tag)>=2]
                if (event['pubkey']!=value['public_key'] or event['kind']!=item['kind'] or event['content']!=body(value,item)
                        or channels!=[item['channel']] or thread(event)!=item['thread'] or _event_reply_parent_id(event)!=item['anchor']
                        or not set(links)<={item['anchor'],item['thread']} or len(links)>2
                        or len(set(mentions))!=len(mentions) or not set(mentions)<=set(item['allowed_mentions'])
                        or any(tag[0]=='broadcast' for tag in event['tags']) or not media_tags(value,item,event['tags'])
                        or replay_event is None and abs(time.time()-event['created_at'])>60
                        or replay_event is not None and (event!=replay_event or raw!=replay)):
                    raise PermissionError('native signed Buzz message changed approved body route thread recipient or resource authority')
                # The caller must commit the actual signed bytes and its sealed
                # outbox/source mapping before returning explicit True.
                retained=await retain(raw,event);current()
                if retained is not True:raise PermissionError('durable signed Buzz custody was not acknowledged')
                state['event']=event
                # Conservative intent before drain: loss after this point is
                # uncertain, including loss of the one-byte acknowledgment.
                state['ack']=True;writer.write(b'\x01');await writer.drain()
        except asyncio.CancelledError:raise
        except Exception:
            if not state['ack']:state['error']='prepublication-refused'
        finally:
            writer.close()
            try:await writer.wait_closed()
            except (ConnectionError,OSError):pass
            clients.discard(client)
    server=await asyncio.start_unix_server(approve,path='\0'+name,limit=8192)
    env={'PATH':'/usr/bin:/bin','HOME':str(home),'LANG':'C.UTF-8','BUZZ_PRIVATE_KEY':value['private_key'],
        'BUZZ_RELAY_URL':value['relay_url'],'BUZZ_OUTPUT_FORMAT':'json','BUZZ_TIMEOUT_SECS':'10','BUZZ_CONNECT_TIMEOUT_SECS':'5',
        'SSL_CERT_FILE':'/etc/ssl/certs/ca-certificates.crt','TOKIO_WORKER_THREADS':'2','HAOS_BUZZ_APPROVAL_SOCKET':name}
    if value.get('auth_tag'):env['BUZZ_AUTH_TAG']=value['auth_tag']
    async def collect(stream,limit):
        out=bytearray()
        while block:=await stream.read(8192):
            if len(out)+len(block)>limit:raise ValueError('bounded Buzz reply process response required')
            out.extend(block)
        return bytes(out)
    async def revoked():
        while True:current();await asyncio.sleep(.1)
    spawn=None;replay_fd=None;upload_fd=None
    try:
        current()
        inherited=()
        attachments=files(value,item)
        if attachments:
            from .gateway_buzz_upload import MANIFEST,sealed
            if metadata.get('uploaded_manifest')!=MANIFEST:raise PermissionError('installed Buzz program lacks reviewed sealed upload manifest')
            raw=json.dumps(attachments,separators=(',',':'),ensure_ascii=False).encode()
            if len(raw)>65536 or redactor.text(raw.decode())!=raw.decode():raise PermissionError('bounded nonprivate upload manifest required')
            upload_fd=sealed('haos-buzz-uploaded-manifest',raw)
            env['HAOS_BUZZ_UPLOADED_FD']=str(upload_fd);inherited+=(upload_fd,)
        if replay is not None:
            from .gateway_buzz_upload import sealed
            replay_fd=sealed('haos-buzz-signed-replay',replay)
            env['HAOS_BUZZ_REPLAY_FD']=str(replay_fd);inherited+=(replay_fd,)
        spawn=asyncio.create_task(asyncio.create_subprocess_exec(program,*args,stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env,cwd=str(home),start_new_session=True,limit=16384,pass_fds=inherited))
        async with asyncio.timeout(40):
            process=await asyncio.shield(spawn);pid_ready.set()
            tasks=[asyncio.create_task(collect(process.stdout,8192)),asyncio.create_task(collect(process.stderr,65536)),
                asyncio.create_task(process.wait()),asyncio.create_task(revoked())]
            process.stdin.write(item['content'].encode());await process.stdin.drain();process.stdin.close()
            joined=asyncio.gather(*tasks[:3]);tasks.append(joined)
            done,_=await asyncio.wait([joined,tasks[3]],return_when=asyncio.FIRST_COMPLETED)
            if tasks[3] in done:tasks[3].result()
            out,_err,code=await joined;current()
            if code==0 and state['ack']:
                from .gateway_line_ingress import _object
                from .gateway_dingtalk_admission import finite
                result=json.loads(out,object_pairs_hook=_object,parse_constant=finite)
                if isinstance(result,dict) and result.get('accepted') is True and result.get('event_id')==state['event']['id']:
                    return {'state':'confirmed','receipt':state['event']['id'],'error':None}
            return {'state':'uncertain' if state['ack'] else 'not-dispatched','receipt':None,
                'error':'delivery-unknown' if state['ack'] else state['error']}
    except asyncio.CancelledError:raise
    except Exception:
        return {'state':'uncertain' if state['ack'] else 'not-dispatched','receipt':None,
            'error':'delivery-unknown' if state['ack'] else state['error']}
    finally:
        server.close();await server.wait_closed()
        if process is None and spawn is not None:
            try:process=await asyncio.shield(spawn)
            except Exception:pass
        pid_ready.set()
        if process is not None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            await process.wait()
        for task in [*tasks,*clients]:
            if not task.done():task.cancel()
        if tasks or clients:await asyncio.gather(*tasks,*clients,return_exceptions=True)
        if replay_fd is not None:os.close(replay_fd)
        if upload_fd is not None:os.close(upload_fd)
