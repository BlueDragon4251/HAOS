"""Bounded private mail subprocess lifetime; cancellation always kills and joins."""
import asyncio
import json
from pathlib import Path
import stat

from .gateway_email import credentials,authority

ERRORS=frozenset({'authority-or-protocol-refused','tls-refused','smtp-authentication-refused','imap-unavailable','transport-unavailable'})


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


async def probe(value,connector,current):
    value=credentials(value);current();identity=authority(connector,value)
    request=json.dumps({'action':'probe','connector':connector,'credentials':value,'policy_sha256':identity}).encode()
    if len(request)>32768:raise ValueError('bounded private mail worker request required')
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
        output=asyncio.create_task(collect(process.stdout,16384));errors=asyncio.create_task(collect(process.stderr,16384))
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
            return response(json.loads(raw,object_pairs_hook=_object))
    finally:
        if process is not None:
            if process.returncode is None:
                try:process.kill()
                except ProcessLookupError:pass
            await process.wait()
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
