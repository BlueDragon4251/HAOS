"""Download only public pinned model bytes, with HTTPS and exact integrity bounds."""
import hashlib
import os
from pathlib import Path
import tempfile
import time
import urllib.parse
import urllib.request

from .speech_model import FILES,REPOSITORY,REVISION


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        target=urllib.parse.urlsplit(newurl)
        host=(target.hostname or '').lower()
        if (target.scheme!='https' or target.username or target.password or target.fragment
                or not (host in {'huggingface.co','raw.githubusercontent.com','cas-bridge.xethub.hf.co','cdn-lfs.hf.co'}
                    or host.endswith('.huggingface.co') or host.endswith('.hf.co'))):
            raise PermissionError('public speech download redirect refused')
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def fetch(url,target,size,checksum):
    """Internal fixed-URL caller; never an owner-supplied endpoint or model filename."""
    target=Path(target)
    if target.exists() or target.is_symlink():
        info=target.lstat()
        import stat
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size!=size:
            raise ValueError('existing public speech asset requires owner inspection')
        with target.open('rb') as existing:
            actual=hashlib.file_digest(existing,'sha256').hexdigest()
        if actual!=checksum:raise ValueError('existing public speech asset checksum mismatch')
        return
    descriptor,temporary=tempfile.mkstemp(prefix='.haos-public-speech-',dir=target.parent)
    try:
        digest=hashlib.sha256();received=0;deadline=time.monotonic()+120
        opener=urllib.request.build_opener(Redirect())
        with os.fdopen(descriptor,'wb') as output:
            descriptor=-1
            request=urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'HAOS-pinned-local-speech'})
            with opener.open(request,timeout=30) as response:
                if (response.status!=200 or response.headers.get('Content-Encoding','identity').lower()!='identity'
                        or response.headers.get('Content-Length') not in {None,str(size)}):
                    raise ValueError('public speech download response refused')
                while True:
                    if time.monotonic()>deadline:raise TimeoutError('public speech download deadline reached')
                    block=response.read(min(1024*1024,size+1-received))
                    if not block:break
                    received+=len(block)
                    if received>size:raise ValueError('public speech download exceeds expected size')
                    digest.update(block);output.write(block)
                if received!=size or digest.hexdigest()!=checksum:raise ValueError('public speech asset integrity mismatch')
            output.flush();os.fsync(output.fileno())
        os.chmod(temporary,0o644);os.replace(temporary,target)
        parent=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        if descriptor!=-1:os.close(descriptor)
        try:os.unlink(temporary)
        except FileNotFoundError:pass


def public_model(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True,mode=0o755)
    for name,(size,checksum) in FILES.items():
        fetch('https://huggingface.co/'+REPOSITORY+'/resolve/'+REVISION+'/'+name,destination/name,size,checksum)
    return destination
