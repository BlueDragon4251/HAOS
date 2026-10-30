"""Bounded signed event parsing and the installed official SDK verifier."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

from .gateway_buzz import HEX

FIELDS=frozenset({'id','pubkey','created_at','kind','tags','content','sig'})


def wire(raw):
    if not isinstance(raw,bytes) or not 1<=len(raw)<=1048576:raise ValueError('bounded original signed Nostr event required')
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    try:event=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
    except (ValueError,RecursionError):raise ValueError('valid original signed Nostr JSON required') from None
    if (not isinstance(event,dict) or set(event)!=FIELDS or any(not isinstance(event[key],str) or not HEX.fullmatch(event[key]) for key in ['id','pubkey'])
            or not isinstance(event['sig'],str) or len(event['sig'])!=128 or any(c not in '0123456789abcdef' for c in event['sig'])
            or type(event['created_at']) is not int or not 0<event['created_at']<2**53 or type(event['kind']) is not int or not 0<=event['kind']<=65535
            or not isinstance(event['content'],str) or len(event['content'].encode())>32000 or '\x00' in event['content']
            or not isinstance(event['tags'],list) or len(event['tags'])>64
            or any(not isinstance(tag,list) or not 1<=len(tag)<=16 or any(not isinstance(item,str) or len(item.encode())>4096
                or any(ord(c)<32 or ord(c)==127 for c in item) for item in tag) for tag in event['tags'])):
        raise ValueError('closed finite signed Nostr event fields required')
    return event


def command(name):
    if name not in {'buzz','haos-buzz-verify'}:raise PermissionError('fixed installed Buzz program required')
    root=Path('/usr/lib/haos/buzz')
    for path in [root.parent,root]:
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or path.resolve()!=path:
            raise PermissionError('immutable root-owned Buzz program directory required')
    metadata=root/'source.json';binary=root/name
    for path,limit in [(metadata,16384),(binary,128*1024*1024)]:
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_nlink!=1 or not 0<info.st_size<=limit:
            raise PermissionError('bounded immutable root-owned Buzz program and provenance required')
    value=json.loads(metadata.read_text())
    if (not isinstance(value,dict) or value.get('commit')!='1eb67bb525d66448b56d79f98c4ba0e2188b44c5' or value.get('nostr_version')!='0.44.7'
            or not isinstance(value.get('programs'),dict) or set(value['programs'])!={'buzz','haos-buzz-verify'}):
        raise PermissionError('exact reviewed Buzz source and official Nostr SDK provenance required')
    entry=value['programs'][name]
    if not isinstance(entry,dict):raise PermissionError('typed installed Buzz executable provenance required')
    expected=entry.get('sha256')
    if not isinstance(expected,str) or not HEX.fullmatch(expected):raise PermissionError('exact installed Buzz executable digest required')
    actual=hashlib.sha256()
    with binary.open('rb') as stream:
        while block:=stream.read(1024*1024):actual.update(block)
    if actual.hexdigest()!=expected:raise PermissionError('Buzz executable differs from installed reviewed build provenance')
    return str(binary)


async def verify(raw):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();event=wire(raw);process=None;tasks=[]
    async def collect(stream):
        result=bytearray()
        while block:=await stream.read(1024):
            if len(result)+len(block)>1024:raise ValueError('bounded private Nostr verifier response required')
            result.extend(block)
        return bytes(result)
    spawn=asyncio.create_task(asyncio.create_subprocess_exec(command('haos-buzz-verify'),stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True,limit=2048,cwd='/',
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent'}))
    try:
        async with asyncio.timeout(10):
            process=await asyncio.shield(spawn)
            tasks=[asyncio.create_task(collect(process.stdout)),asyncio.create_task(collect(process.stderr))]
            process.stdin.write(raw);await process.stdin.drain();process.stdin.close()
            out,err=await asyncio.gather(*tasks);await process.wait()
            from .gateway_line_ingress import _object
            from .gateway_dingtalk_admission import finite
            result=json.loads(out,object_pairs_hook=_object,parse_constant=finite)
            if err or process.returncode!=0 or result!={'valid':True,'id':event['id'],'pubkey':event['pubkey']}:
                raise PermissionError('official Nostr SDK refused the signed event')
            return event
    finally:
        if process is None and not spawn.cancelled():
            try:process=await asyncio.shield(spawn)
            except Exception:pass
        if process is not None:
            if process.returncode is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            await process.wait()
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
