"""Original-bound media reads; native private Blossom GET and anonymous approved TLS."""
import asyncio
import hashlib
import json
import re
import ssl
from pathlib import Path

from .gateway import Conflict,digest
from .gateway_buzz import resource_origin
from .gateway_buzz_crypto import command
from .gateway_buzz_admission import Refused
from .gateway_media import approved,describe,MAX_BYTES

MEDIA_LIMIT='8388608 bytes before allocation, scoped native request/connect deadlines, bounded native error handler, actual Blossom signer unchanged'


async def specification(adapter,row,original,index):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();adapter._haos_buzz_check()
    if type(index) is not int or not 0<=index<4:raise PermissionError('exact retained Buzz resource index required')
    native=adapter._haos_native;policy=native.policy();binding=policy.current_binding(row)
    actual=await adapter._haos_buzz_raw.get(policy,native.connector,adapter._haos_buzz_value,original['id'])
    if (actual!=original or actual['source_key']!=row['id'] or actual['envelope']!=row['envelope']
            or row['fingerprint']!=digest(actual['envelope']) or index>=len(actual['resources'])
            or 'create' not in binding['capabilities'] or not approved(binding)):
        raise PermissionError('current exact original-bound Buzz media/create grant required')
    resource=dict(actual['resources'][index]);mode=resource_origin(adapter._haos_buzz_value,resource['url'])
    return {'binding':binding,'resource':resource,'mode':mode,'source':actual['id'],'fingerprint':digest([row['fingerprint'],actual['raw_sha256'],resource])}


def classify(spec,data):
    resource=spec['resource'];mime=(resource.get('mime_type') or 'application/octet-stream').split(';',1)[0].strip().lower()
    if not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',mime):raise Refused('resource-mime-mismatch')
    kind=resource.get('kind','document')
    png=data.startswith(b'\x89PNG\r\n\x1a\n');jpeg=data.startswith(b'\xff\xd8\xff')
    iso=len(data)>=16 and data[4:8]==b'ftyp'
    m4a=iso and data[8:12] in {b'M4A ',b'M4B ',b'M4P '}
    voice=(data.startswith((b'#!AMR\n',b'#!AMR-WB\n',b'OggS',b'fLaC',b'ID3'))
        or len(data)>=12 and data[:4]==b'RIFF' and data[8:12]==b'WAVE'
        or len(data)>=2 and data[0]==255 and data[1]&224==224)
    if png or jpeg:kind='image';actual_mime='image/png' if png else 'image/jpeg'
    elif m4a:kind='voice';actual_mime='audio/mp4'
    elif iso or mime.startswith('video/'):kind='video';actual_mime=mime if mime.startswith('video/') else 'video/mp4'
    elif voice or mime.startswith('audio/'):
        kind='voice';actual_mime=mime if mime.startswith('audio/') else 'audio/ogg' if data.startswith(b'OggS') else 'audio/flac' if data.startswith(b'fLaC') else 'audio/wav' if data.startswith(b'RIFF') else 'audio/amr-wb' if data.startswith(b'#!AMR-WB') else 'audio/amr' if data.startswith(b'#!AMR') else 'audio/mpeg'
    elif mime.startswith('image/'):kind='image';actual_mime=mime
    else:actual_mime=mime
    if not approved(spec['binding'],kind):raise Refused('independent-decoded-media-consent-required')
    if mime!='application/octet-stream' and (kind=='image' and mime!=actual_mime
            or kind=='voice' and not mime.startswith('audio/') or kind=='video' and not mime.startswith('video/')):
        raise Refused('resource-mime-mismatch')
    return describe(data,kind),actual_mime


async def fetch(adapter,row,original,index):
    spec=await specification(adapter,row,original,index);resource=spec['resource'];reader=adapter._haos_buzz_reader
    def current():adapter._haos_buzz_check();adapter._haos_native.policy().current_binding(row)
    current()
    if spec['mode']=='relay':
        path=command('buzz');meta=json.loads((Path(path).parent/'source.json').read_text())
        if meta.get('native_media_body_limit')!=MEDIA_LIMIT:raise PermissionError('installed native media reader lacks reviewed bounded body contract')
        out,err,code=await reader._execute(['media','get','-o','-',resource['url']],None)
        current()
        if code:
            try:error=json.loads(err)
            except (ValueError,RecursionError):error={}
            message=error.get('message','') if isinstance(error,dict) else ''
            if isinstance(message,str) and message.startswith('relay error 429:'):raise Refused('resource-rate-limited',60)
            if code==3:raise Refused('resource-authentication-or-content-refused')
            raise Refused('resource-unavailable',2)
        data=out
    else:
        import httpx
        async def read():
            async with httpx.AsyncClient(follow_redirects=False,trust_env=False,timeout=10,
                    verify=ssl.create_default_context(cafile='/etc/ssl/certs/ca-certificates.crt'),headers={'Accept-Encoding':'identity'}) as client:
                async with client.stream('GET',resource['url']) as response:
                    current()
                    if response.status_code==429:raise Refused('resource-rate-limited',60)
                    if response.status_code!=200:raise Refused('resource-unavailable',2)
                    length=response.headers.get('content-length')
                    if length is not None and (not length.isascii() or not length.isdecimal() or not 0<int(length)<=MAX_BYTES):raise Refused('resource-size-refused')
                    data=bytearray()
                    async for chunk in response.aiter_bytes():
                        current()
                        if len(data)+len(chunk)>MAX_BYTES:raise Refused('resource-size-refused')
                        data.extend(chunk)
                    return bytes(data)
        async def watch():
            while True:current();await asyncio.sleep(.1)
        tasks=[]
        try:
            async with asyncio.timeout(20):
                tasks=[asyncio.create_task(read()),asyncio.create_task(watch())]
                done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                if tasks[1] in done:tasks[1].result()
                data=await tasks[0]
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
    current()
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:raise Refused('resource-size-refused')
    expected=resource.get('sha256')
    if expected is None:
        from urllib.parse import urlsplit
        expected=urlsplit(resource['url']).path.split('/media/',1)[1].split('.',1)[0]
    if (hashlib.sha256(data).hexdigest()!=expected or 'size' in resource and len(data)!=resource['size']
            or any(secret.encode() in data for secret in adapter._haos_native.inbox.redactor.secrets)):
        raise Refused('resource-integrity-refused')
    if await specification(adapter,row,original,index)!=spec:raise Conflict('Buzz media source or consent changed during download')
    descriptor,mime=classify(spec,data);current()
    return {'data':data,'descriptor':descriptor,'mime':mime,'resource':resource}
