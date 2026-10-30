"""Fixed native Blossom upload from sealed bytes, then verify the stored blob."""
import asyncio
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal

from .gateway_buzz import HEX,credentials,resource_origin
from .gateway_buzz_crypto import command
from .gateway_media import MAX_BYTES

UPLOAD='HAOS_BUZZ_GENERIC_FILES-v1: exact pinned relay MIME subset, sealed input, 8MiB before read, scoped deadline and bounded native response'
MANIFEST='HAOS_BUZZ_UPLOADED_FD-v1: sealed root-owned upload descriptors, actual native imeta builder, one guarded message for up to four files'


class UploadFailed(RuntimeError):
    def __init__(self,category):
        self.category=category;super().__init__(category)


def descriptor(value,item):
    required={'url','sha256','size','type','uploaded'};optional={'dim','blurhash','thumb','duration'}
    if (not isinstance(item,dict) or not required<=set(item)<=required|optional
            or not isinstance(item['sha256'],str) or not HEX.fullmatch(item['sha256'])
            or type(item['size']) is not int or not 1<=item['size']<=MAX_BYTES
            or type(item['uploaded']) is not int or not 0<=item['uploaded']<=253402300799
            or not isinstance(item['type'],str) or not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',item['type'])):
        raise PermissionError('bounded closed native Buzz upload descriptor required')
    if resource_origin(value,item['url'])!='relay' or item['url'].split('/media/',1)[1].split('.',1)[0]!=item['sha256']:
        raise PermissionError('uploaded Buzz blob must remain on its exact content-addressed relay')
    for key,pattern in [('dim','[1-9][0-9]{0,4}x[1-9][0-9]{0,4}'),('blurhash','[!-~]{1,200}')]:
        if item.get(key) is not None and (not isinstance(item[key],str) or not re.fullmatch(pattern,item[key])):
            raise PermissionError('bounded native Buzz media metadata required')
    if item.get('thumb') is not None and resource_origin(value,item['thumb'])!='relay':
        raise PermissionError('Buzz thumbnail cannot gain foreign network authority')
    if item.get('duration') is not None and (type(item['duration']) not in {int,float}
            or not math.isfinite(item['duration']) or not 0<=item['duration']<=86400):
        raise PermissionError('finite bounded Buzz media duration required')
    return dict(item)


def sealed(name,data):
    fd=os.memfd_create(name,os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
    try:
        with os.fdopen(os.dup(fd),'wb') as stream:stream.write(data);stream.flush()
        os.lseek(fd,0,os.SEEK_SET)
        # Linux UAPI also covers Python builds without GNU constant exports.
        # Unsupported kernels still fail closed at the actual syscall.
        fcntl.fcntl(fd,getattr(fcntl,'F_ADD_SEALS',1033),getattr(fcntl,'F_SEAL_SEAL',1)
            |getattr(fcntl,'F_SEAL_SHRINK',2)|getattr(fcntl,'F_SEAL_GROW',4)|getattr(fcntl,'F_SEAL_WRITE',8))
        return fd
    except BaseException:os.close(fd);raise


async def _execute(program,args,env,home,current,*,fds=(),limit=65536):
    current();process=None;tasks=[]
    async def collect(stream,bound):
        out=bytearray()
        while block:=await stream.read(8192):
            if len(out)+len(block)>bound:raise UploadFailed('response_limit')
            out.extend(block)
        return bytes(out)
    async def revoked():
        while True:current();await asyncio.sleep(.1)
    spawn=asyncio.create_task(asyncio.create_subprocess_exec(program,*args,stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env,cwd=str(home),
        start_new_session=True,limit=16384,pass_fds=fds))
    try:
        async with asyncio.timeout(40):
            process=await asyncio.shield(spawn)
            tasks=[asyncio.create_task(collect(process.stdout,limit)),asyncio.create_task(collect(process.stderr,65536)),
                asyncio.create_task(process.wait()),asyncio.create_task(revoked())]
            joined=asyncio.gather(*tasks[:3]);tasks.append(joined)
            done,_=await asyncio.wait([joined,tasks[3]],return_when=asyncio.FIRST_COMPLETED)
            if tasks[3] in done:tasks[3].result()
            out,err,code=await joined;current()
            if code:
                category='authentication_refused' if code==3 else 'upload_unavailable'
                if code==2:
                    try:failure=json.loads(err)
                    except (ValueError,RecursionError):failure=None
                    if (isinstance(failure,dict) and failure.get('error')=='relay_error'
                            and isinstance(failure.get('message'),str) and failure['message'].startswith('relay error 429:')):
                        category='rate_limited'
                raise UploadFailed(category)
            return out
    except TimeoutError:raise UploadFailed('upload_timeout') from None
    finally:
        if process is None:
            try:process=await asyncio.shield(spawn)
            except Exception:pass
        if process is not None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            await process.wait()
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)


async def upload(value,data,*,home,current,redactor):
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity();value=credentials(value)
    if not callable(current) or not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:
        raise PermissionError('current sealed output authority and bounded immutable bytes required')
    current()
    if any(secret.encode() in data for secret in redactor.secrets if secret):
        raise PermissionError('private Buzz credentials cannot become uploaded media')
    from .gateway_line_profile import _directory
    home=Path(home);_directory(home)
    from plugins.platforms.buzz.nostr_auth import public_key_hex
    if public_key_hex(value['private_key'])!=value['public_key']:raise PermissionError('native private Buzz upload identity mismatch')
    program=command('buzz');metadata=json.loads((Path(program).parent/'source.json').read_text())
    from .gateway_buzz_resource import MEDIA_LIMIT
    if metadata.get('generic_file_upload')!=UPLOAD or metadata.get('native_media_body_limit')!=MEDIA_LIMIT:
        raise PermissionError('installed native Buzz upload and retrieval must have reviewed bounds')
    env={'PATH':'/usr/bin:/bin','HOME':str(home),'LANG':'C.UTF-8','BUZZ_PRIVATE_KEY':value['private_key'],
        'BUZZ_RELAY_URL':value['relay_url'],'BUZZ_OUTPUT_FORMAT':'json','BUZZ_TIMEOUT_SECS':'10','BUZZ_CONNECT_TIMEOUT_SECS':'5',
        'SSL_CERT_FILE':'/etc/ssl/certs/ca-certificates.crt','TOKIO_WORKER_THREADS':'2','HAOS_BUZZ_GENERIC_FILES':'1'}
    if value.get('auth_tag'):env['BUZZ_AUTH_TAG']=value['auth_tag']
    fd=sealed('haos-buzz-root-output',data)
    try:raw=await _execute(program,['upload','file','--file','/proc/self/fd/'+str(fd)],env,home,current,fds=(fd,))
    finally:os.close(fd)
    from .gateway_line_ingress import _object
    from .gateway_dingtalk_admission import finite
    try:item=descriptor(value,json.loads(raw,object_pairs_hook=_object,parse_constant=finite))
    except (ValueError,RecursionError,PermissionError):raise UploadFailed('invalid_descriptor') from None
    current()
    # A relay may normalize images/video. Validate its actual stored bytes,
    # preserve both hashes, and never describe them as unchanged source bytes.
    stored=await _execute(program,['media','get','-o','-',item['url']],env,home,current,limit=MAX_BYTES)
    if len(stored)!=item['size'] or hashlib.sha256(stored).hexdigest()!=item['sha256']:
        raise UploadFailed('stored_blob_mismatch')
    if any(secret.encode() in stored for secret in redactor.secrets if secret):raise UploadFailed('private_reflection')
    if not item['type'].startswith(('image/','video/')) and stored!=data:raise UploadFailed('unexpected_blob_transformation')
    current()
    return {'descriptor':item,'source_sha256':hashlib.sha256(data).hexdigest(),'stored':stored}
