"""Closed private SDK token/discovery transport; no generic HTTP capability."""
from contextlib import contextmanager
from contextvars import ContextVar
import importlib
import json
import platform
import re
import threading
import time
from urllib.parse import urlsplit

from .gateway import digest
from .gateway_dingtalk import credentials,API
from .gateway_line_ingress import _object
from .gateway_dingtalk_admission import finite
from .redaction import Redactor

_ACTIVE=ContextVar('haos_private_dingtalk_sdk_http',default=None)
_LOCK=threading.RLock()
MAX_REPLY=65536
TOKEN=re.compile(r'[A-Za-z0-9_./+=:-]{16,8192}\Z')
ERRORS=frozenset({'authentication-refused','rate-limited','server-refused','transport-unavailable','tls-refused',
    'redirect-refused','response-too-large','truncated-response','invalid-response','invalid-token'})


class Failure(PermissionError):
    def __init__(self,kind):
        if kind not in ERRORS:raise ValueError('finite DingTalk transport diagnostic required')
        super().__init__('private DingTalk SDK operation refused');self.kind=kind


def endpoint(value):
    if not isinstance(value,str) or not 1<=len(value)<=2048 or any(not 33<=ord(char)<=126 for char in value):raise Failure('invalid-response')
    try:
        parsed=urlsplit(value)
        if (parsed.scheme!='wss' or parsed.hostname!='wss-open-connection.dingtalk.com'
                or parsed.port not in {None,443} or parsed.path!='/connect' or parsed.query or parsed.fragment
                or parsed.username or parsed.password):raise ValueError
    except ValueError:raise Failure('invalid-response') from None
    return value


class QuietLogger:
    """Native SDK diagnostics can contain app secrets, tickets and response bodies."""
    def debug(self,*_args,**_kwargs):pass
    def info(self,*_args,**_kwargs):pass
    def warning(self,*_args,**_kwargs):pass
    def error(self,*_args,**_kwargs):pass
    def exception(self,*_args,**_kwargs):pass


class Requests:
    @staticmethod
    def post(url,*,headers=None,data=None,**kwargs):
        operation=_ACTIVE.get()
        if operation is None or kwargs:raise PermissionError('no reviewed private DingTalk SDK request scope')
        return operation['boundary'].post(operation,url,headers,data)


@contextmanager
def sdk_scope():
    # This scope belongs in the isolated private worker, never in agent extensions.
    with _LOCK:
        module=importlib.import_module('dingtalk_stream.stream');previous=module.requests;module.requests=Requests
        try:yield
        finally:module.requests=previous


class Boundary:
    def __init__(self,value,current,redactor):
        if not callable(current) or not isinstance(redactor,Redactor):raise PermissionError('current owner publication and private redaction required')
        self.value=credentials(value);self.current=current;self.redactor=redactor;self.failure=None
        self.tokens={};self.session=None;self.register(self.value['client_secret']);current()

    def register(self,value):
        variants={value}
        for _ in range(2):
            variants|={json.dumps(text,ensure_ascii=ascii)[1:-1] for text in tuple(variants) for ascii in (True,False)}
            variants|={repr(text)[1:-1] for text in tuple(variants)}
        self.redactor.secrets=sorted(set([*self.redactor.secrets,*variants]),key=len,reverse=True)

    def client(self):
        self.current()
        from dingtalk_stream import DingTalkStreamClient,Credential
        client=DingTalkStreamClient(Credential(self.value['client_id'],self.value['client_secret']),logger=QuietLogger())
        # SDK's routing hint otherwise probes a public UDP address. It isn't an
        # authenticated identity field and must not create another network path.
        client.get_host_ip=lambda:''
        return client

    def check(self,client):
        self.current()
        from dingtalk_stream import DingTalkStreamClient
        if (type(client) is not DingTalkStreamClient or client.credential.client_id!=self.value['client_id']
                or client.credential.client_secret!=self.value['client_secret']):raise PermissionError('exact current private SDK client required')
        cache=client._access_token
        if cache:
            if (not isinstance(cache,dict) or not {'accessToken','expireIn','expireTime'}<=set(cache)
                    or not isinstance(cache['accessToken'],str) or cache['accessToken'] not in self.tokens):raise Failure('invalid-token')
            record=self.tokens[cache['accessToken']]
            payload={key:value for key,value in cache.items() if key!='expireTime'}
            if (digest(payload)!=record['wire'] or type(cache['expireIn']) is not int or cache['expireIn']!=record['ttl'] or type(cache['expireTime']) is not int
                    or not record['issued']+record['ttl']-301<=cache['expireTime']<=record['issued']+record['ttl']-298):
                raise Failure('invalid-token')
            if time.monotonic()>=record['until']:client.reset_access_token()

    @contextmanager
    def operation(self,purpose,client):
        if purpose not in {'token','connection'} or _ACTIVE.get() is not None:raise PermissionError('one closed private SDK operation required')
        self.failure=None;self.check(client);operation={'boundary':self,'purpose':purpose,'client':client,'requests':0}
        token=_ACTIVE.set(operation)
        try:
            yield operation
            self.current()
        finally:_ACTIVE.reset(token)

    def refuse(self,kind):
        self.failure=kind;raise Failure(kind)

    def post(self,operation,url,headers,data):
        self.check(operation['client'])
        if operation is not _ACTIVE.get() or operation['requests']!=0:raise PermissionError('one current scoped SDK request required')
        purpose=operation['purpose'];target=API+('/v1.0/oauth2/accessToken' if purpose=='token' else '/v1.0/gateway/connections/open')
        if url!=target:raise PermissionError('unreviewed DingTalk SDK target')
        expected={'Content-Type':'application/json','Accept':'application/json'}
        if purpose=='connection':
            from dingtalk_stream.version import VERSION_STRING
            expected['User-Agent']=f'DingTalkStream/1.0 SDK/{VERSION_STRING} Python/{platform.python_version()} (+https://github.com/open-dingtalk/dingtalk-stream-sdk-python)'
        if headers!=expected:raise PermissionError('unreviewed private SDK headers')
        if isinstance(data,str):data=data.encode('utf-8')
        if not isinstance(data,bytes) or not 1<=len(data)<=32768:raise ValueError('bounded native SDK request bytes required')
        try:body=json.loads(data.decode('utf-8'),object_pairs_hook=_object,parse_constant=finite)
        except (ValueError,UnicodeError,RecursionError):raise ValueError('exact native SDK request JSON required') from None
        wanted={'appKey':self.value['client_id'],'appSecret':self.value['client_secret']}
        if purpose=='connection':
            from dingtalk_stream import ChatbotMessage
            from dingtalk_stream.version import VERSION_STRING
            wanted={'clientId':self.value['client_id'],'clientSecret':self.value['client_secret'],
                'subscriptions':[{'type':'CALLBACK','topic':ChatbotMessage.TOPIC}],
                'ua':'dingtalk-sdk-python/v'+VERSION_STRING+'-union','localIp':''}
        if body!=wanted:raise PermissionError('SDK request widened credentials, subscriptions or network hints')
        operation['requests']+=1
        import requests
        if self.session is None:
            self.session=requests.Session();self.session.trust_env=False
            self.session.headers.clear();self.session.headers['Accept-Encoding']='identity'
        self.session.cookies.clear();response=None
        try:
            self.current()
            response=self.session.post(url,headers=expected,data=data,allow_redirects=False,stream=True,timeout=(5,10))
            self.current();status=response.status_code
            if 300<=status<400:self.refuse('redirect-refused')
            if status in {401,403}:self.refuse('authentication-refused')
            if status==429:self.refuse('rate-limited')
            if status!=200:self.refuse('server-refused')
            if response.headers.get('Content-Encoding','identity').lower() not in {'','identity'}:self.refuse('invalid-response')
            content_type=response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
            if content_type!='application/json':self.refuse('invalid-response')
            length=response.headers.get('Content-Length');limit=None
            if length is not None:
                if not length.isascii() or not length.isdecimal():self.refuse('invalid-response')
                limit=int(length)
                if limit>MAX_REPLY:self.refuse('response-too-large')
            raw=bytearray()
            for chunk in response.iter_content(4096):
                self.current();raw.extend(chunk)
                if len(raw)>MAX_REPLY:self.refuse('response-too-large')
            if limit is not None and len(raw)!=limit:self.refuse('truncated-response')
            try:result=json.loads(bytes(raw).decode('utf-8'),object_pairs_hook=_object,parse_constant=finite)
            except (ValueError,UnicodeError,RecursionError):self.refuse('invalid-response')
            if not isinstance(result,dict):self.refuse('invalid-response')
            if purpose=='token':
                if (not {'accessToken','expireIn'}<=set(result) or len(result)>64 or not isinstance(result['accessToken'],str) or not TOKEN.fullmatch(result['accessToken'])
                        or type(result['expireIn']) is not int or not 1<=result['expireIn']<=86400):self.refuse('invalid-response')
                token=result['accessToken'];ttl=result['expireIn'];self.register(token)
                self.tokens[token]={'ttl':ttl,'issued':int(time.time()),'until':time.monotonic()+ttl,'wire':digest(result)}
            else:
                if not {'endpoint','ticket'}<=set(result) or len(result)>64 or not isinstance(result['ticket'],str) or not TOKEN.fullmatch(result['ticket']):self.refuse('invalid-response')
                endpoint(result['endpoint']);self.register(result['ticket'])
            self.current();response._content=bytes(raw);response._content_consumed=True
            return response
        except Failure as error:self.failure=error.kind;raise
        except requests.exceptions.SSLError:self.refuse('tls-refused')
        except requests.exceptions.ChunkedEncodingError:self.refuse('truncated-response')
        except requests.exceptions.RequestException:self.refuse('transport-unavailable')
        finally:
            self.session.cookies.clear()
            if response is not None:response.close()

    def close(self):
        if self.session is not None:self.session.close();self.session=None
