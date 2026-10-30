"""One exact native Stream SDK multipart upload, confined to its private worker."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import re
import threading
import time
from urllib.parse import quote_plus

from .gateway_dingtalk_http import Boundary as TokenBoundary,Failure,QuietLogger
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object
from .gateway_media import MAX_BYTES,MAX_IMAGE_BYTES,describe

_ACTIVE=ContextVar('haos_private_dingtalk_upload',default=None)
_LOCK=threading.RLock()
API='https://oapi.dingtalk.com'
MEDIA_ID=re.compile(r'[A-Za-z0-9_@$#./+=:-]{8,8192}\Z')
FORMATS={'image':{'png':'image/png','jpeg':'image/jpeg','jpg':'image/jpeg'},
    'voice':{'amr':'audio/amr'},'video':{'mp4':'video/mp4'},
    'file':{'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'pdf':'application/pdf','zip':'application/zip','rar':'application/vnd.rar',
        'doc':'application/msword','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}}


def target(value):
    if (not isinstance(value,dict) or set(value)!={'kind','name','size','sha256','mime'}
            or not isinstance(value['kind'],str) or value['kind'] not in FORMATS
            or not isinstance(value['name'],str) or not re.fullmatch(r'(result|cover)-[0-3]\.[a-z0-9]{1,4}',value['name'])
            or type(value['size']) is not int or not 1<=value['size']<=MAX_BYTES
            or not isinstance(value['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['sha256'])):
        raise PermissionError('exact bounded path-free native DingTalk upload required')
    extension=value['name'].rsplit('.',1)[1]
    if FORMATS[value['kind']].get(extension)!=value['mime']:
        raise PermissionError('native DingTalk file format and MIME must agree')
    if value['kind'] in {'image','voice'} and value['size']>MAX_IMAGE_BYTES:
        raise PermissionError('native DingTalk image/voice upload exceeds private limit')
    return deepcopy(value)


class Requests:
    @staticmethod
    def post(url,*,data=None,files=None,**kwargs):
        operation=_ACTIVE.get()
        if not isinstance(operation,Upload) or kwargs:raise PermissionError('no closed private native upload scope')
        return operation.post(url,data,files)


@contextmanager
def sdk_scope(operation):
    if not isinstance(operation,Upload) or _ACTIVE.get() is not None:raise PermissionError('one private native upload scope required')
    import dingtalk_stream.stream as native
    with _LOCK:
        previous=native.requests;native.requests=Requests;context=_ACTIVE.set(operation)
        try:yield
        finally:_ACTIVE.reset(context);native.requests=previous


class Upload:
    def __init__(self,owner,token,item,data,current):
        if (not isinstance(owner,TokenBoundary) or not isinstance(token,str) or token not in owner.tokens
                or not callable(current)):
            raise PermissionError('observed private token and current upload authority required')
        self.owner=owner;self.token=token;self.target=target(item);self.data=data;self.current=current
        if (not isinstance(data,bytes) or len(data)!=self.target['size']
                or hashlib.sha256(data).hexdigest()!=self.target['sha256']
                or any(secret.encode() in data for secret in owner.redactor.secrets)):
            raise PermissionError('immutable sealed output bytes without private credentials required')
        kind=self.target['kind']
        if kind in {'image','video'}:
            meta=describe(data,kind)
            if (kind=='image' and self.target['mime']!='image/'+meta['format']
                    or kind=='video' and meta['format']!='mp4'):
                raise PermissionError('native upload format differs from original bytes')
        if kind=='voice':
            from .audio_amr import duration_samples
            from .speech import MAX_SAMPLES
            if duration_samples(data)>MAX_SAMPLES+320:raise PermissionError('bounded native Robot AMR duration required')
        if kind=='file':
            extension=self.target['name'].rsplit('.',1)[1]
            signatures={'pdf':(b'%PDF-',),'doc':(bytes.fromhex('d0cf11e0a1b11ae1'),),
                'zip':(b'PK\x03\x04',b'PK\x05\x06'),'docx':(b'PK\x03\x04',),'xlsx':(b'PK\x03\x04',),
                'rar':(b'Rar!\x1a\x07\x00',b'Rar!\x1a\x07\x01\x00')}
            if not data.startswith(signatures[extension]):
                raise PermissionError('native Robot document format differs from sealed bytes')
        self.used=False;self.write_started=False;self.state='not-dispatched';self.error='';self.retry_after=0
        self.media_id=None;self.created_at=None;self.session=None;self.check()

    def check(self):
        self.current();self.owner.current()
        if self.owner.tokens.get(self.token,{}).get('until',0)<=time.monotonic():raise Failure('invalid-token')

    def reject(self,kind,delay=0):
        self.state='rejected';self.error=kind;self.retry_after=delay;raise PermissionError('private native upload refused')

    def post(self,url,data,files):
        self.check()
        if (_ACTIVE.get() is not self or self.used or url!=API+'/media/upload?access_token='+quote_plus(self.token)
                or data!={'type':self.target['kind']} or not isinstance(files,dict) or set(files)!={'media'}
                or files['media']!=(self.target['name'],self.data,self.target['mime'])):
            raise PermissionError('one exact native multipart upload required')
        self.used=True
        import requests
        self.session=requests.Session();self.session.trust_env=False;self.session.headers.clear()
        self.session.headers['Accept-Encoding']='identity';response=None
        try:
            self.check();self.write_started=True;self.state='uncertain'
            response=self.session.post(url,data=data,files=files,allow_redirects=False,stream=True,timeout=(5,10))
            self.check();status=response.status_code
            if status in {401,403}:self.reject('authentication-refused')
            if status==429:
                from .gateway_retry import retry_after
                self.reject('rate-limited',retry_after(response.headers.get('Retry-After'),default=60,private_values=self.owner.redactor.secrets))
            if (status!=200 or response.headers.get('Content-Encoding','identity').lower() not in {'','identity'}
                    or response.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json'):
                raise PermissionError('native upload acceptance unavailable')
            length=response.headers.get('Content-Length')
            if length is not None and (not length.isascii() or not length.isdecimal() or len(length)>8 or int(length)>65536):
                raise PermissionError('bounded native upload acceptance required')
            raw=bytearray()
            for chunk in response.iter_content(4096):
                self.check();raw.extend(chunk)
                if len(raw)>65536:raise PermissionError('bounded native upload acceptance required')
            if length is not None and len(raw)!=int(length):raise PermissionError('truncated native upload acceptance')
            result=json.loads(bytes(raw).decode(),object_pairs_hook=_object,parse_constant=finite)
            if (not isinstance(result,dict) or 'errcode' not in result
                    or len(result)>64 or type(result['errcode']) is not int):
                raise PermissionError('native upload result required')
            if result['errcode']!=0:self.reject('native-refused')
            if (not {'media_id','type','created_at'}<=set(result) or result['type']!=self.target['kind'] or not isinstance(result['media_id'],str)
                    or not MEDIA_ID.fullmatch(result['media_id']) or '://' in result['media_id']
                    or any(secret in result['media_id'] for secret in (self.owner.value['client_secret'],*self.owner.tokens))
                    or type(result['created_at']) is not int or not 0<result['created_at']<=int(time.time()*1000)+300000):
                raise PermissionError('native upload type, key or timestamp changed')
            self.check();self.media_id=result['media_id'];self.created_at=result['created_at']
            self.owner.register(self.media_id);self.state='confirmed'
            response._content=bytes(raw);response._content_consumed=True
            return response
        finally:
            if response is not None:response.close()
            self.close()

    def close(self):
        if self.session is not None:self.session.cookies.clear();self.session.close();self.session=None


def invoke(client,operation):
    from dingtalk_stream import DingTalkStreamClient
    if not isinstance(operation,Upload) or type(client) is not DingTalkStreamClient:
        raise PermissionError('actual private native SDK upload required')
    operation.owner.check(client)
    if (client._access_token.get('accessToken')!=operation.token
            or client._access_token.get('expireTime',0)<=int(time.time())):
        raise PermissionError('current observed native SDK token cache required')
    original=client.logger;client.logger=QuietLogger()
    try:
        with sdk_scope(operation):
            result=DingTalkStreamClient.upload_to_dingtalk(client,operation.data,filetype=operation.target['kind'],
                filename=operation.target['name'],mimetype=operation.target['mime'])
        operation.check()
        if operation.state=='confirmed' and result==operation.media_id:
            return {'state':'confirmed','kind':operation.target['kind'],'media_id':operation.media_id,'created_at':operation.created_at}
        if operation.state=='rejected':return {'state':'rejected','error':operation.error,'retry_after':operation.retry_after}
        return {'state':'uncertain'} if operation.write_started else {'state':'rejected','error':'authority-or-protocol-refused','retry_after':0}
    except Exception:
        return {'state':'uncertain'} if operation.write_started else {'state':'rejected','error':'authority-or-protocol-refused','retry_after':0}
    finally:client.logger=original;operation.close()
