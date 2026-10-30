"""Bounded no-send SDK worker in the distinct private gateway identity."""
import asyncio
import json
import os
from pathlib import Path
import stat

from .gateway_dingtalk import credentials,authority,scope
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object
from .gateway_dingtalk_http import ERRORS as HTTP_ERRORS

ERRORS=HTTP_ERRORS|{'authority-or-protocol-refused','sdk-unavailable'}


def command():
    root=Path('/usr/lib/haos');python=root/'hermes/.venv/bin/python'
    for path in [root,root/'haos',root/'hermes',root/'hermes/.venv',python.parent]:
        own=path.lstat()
        if not stat.S_ISDIR(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022:raise PermissionError('root-owned private DingTalk runtime required')
    own=python.resolve(strict=True).lstat()
    if not stat.S_ISREG(own.st_mode) or own.st_uid!=0 or own.st_mode&0o022:raise PermissionError('root-owned private DingTalk interpreter required')
    return [str(python),'-E','-s','-m','haos.gateway_dingtalk_worker']


def response(result,value):
    if isinstance(result,dict) and set(result)=={'error'}:
        if not isinstance(result['error'],str) or result['error'] not in ERRORS:raise ValueError('finite DingTalk diagnostic required')
        return result
    if (not isinstance(result,dict) or set(result)!={'app_authenticated','corp_identity_verified','robot_identity_verified','account_scope','message_sent'}
            or result['app_authenticated'] is not True or result['corp_identity_verified'] is not False
            or result['robot_identity_verified'] is not False or result['message_sent'] is not False or result['account_scope']!=scope(value)):
        raise ValueError('exact no-send DingTalk account result required')
    return result


async def kill(process):
    if process.returncode is None:
        try:os.killpg(process.pid,9)
        except ProcessLookupError:pass
    await process.wait()


async def account(value,connector,current):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value);current();publication=authority(connector,value)
    payload={'action':'account','connector':connector,'credentials':value,'policy_sha256':publication,'parent_pid':os.getpid()}
    raw=(json.dumps(payload,ensure_ascii=False)+'\n').encode()
    if len(raw)>32768:raise ValueError('bounded private DingTalk account frame required')
    spawning=asyncio.create_task(asyncio.create_subprocess_exec(*command(),stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True,limit=16385,
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HERMES_SAFE_MODE':'1',
            'HOME':'/var/lib/haos-gateway','HERMES_HOME':'/var/lib/haos-gateway'}))
    try:process=await asyncio.shield(spawning)
    except asyncio.CancelledError:
        process=await spawning;await kill(process);raise
    async def bounded(stream,limit):
        result=bytearray()
        while True:
            part=await stream.read(min(4096,limit+1-len(result)))
            if not part:return bytes(result)
            result.extend(part)
            if len(result)>limit:raise ValueError('private DingTalk worker response exceeds bound')
    async def write():
        process.stdin.write(raw);await process.stdin.drain();process.stdin.close();await process.stdin.wait_closed()
    async def exchange():return await asyncio.gather(write(),bounded(process.stdout,16384),bounded(process.stderr,16384))
    work=asyncio.create_task(exchange())
    try:
        async with asyncio.timeout(35):
            while not work.done():
                current();authority(connector,value,publication)
                await asyncio.wait({work},timeout=.1)
            _sent,out,_err=await work
            if await process.wait()!=0:raise RuntimeError('private DingTalk account worker unavailable')
            current();authority(connector,value,publication)
            return response(json.loads(out,object_pairs_hook=_object,parse_constant=finite),value)
    finally:
        if not work.done():work.cancel()
        await kill(process);await asyncio.gather(work,return_exceptions=True)
