"""Private scoped native Lark SDK reads; no generic HTTP or message-write capability.

Install only inside the private gateway SDK identity. The worker must separately
establish kernel identity, root publication and the purpose-specific owner grant.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import logging
import re
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from .gateway import digest
from .gateway_feishu import credentials,DOMAINS,MESSAGE_ID
from .gateway_line_ingress import _object
from .gateway_feishu_admission import bounded,Refused
from .redaction import Redactor

_ACTIVE=ContextVar('haos_private_lark_read',default=None)
_INSTALL=threading.RLock()
TOKEN=re.compile(r'[A-Za-z0-9_./+=:-]{16,8192}\Z')


class Failure(PermissionError):
    def __init__(self,kind):
        super().__init__('private Feishu SDK read refused')
        self.kind=kind


def finite(_value):raise ValueError('finite SDK JSON required')


def active():
    state=_ACTIVE.get()
    if state is None:raise Failure('missing-capability')
    state['boundary'].check(state)
    return state


class ScopedCache:
    def __init__(self,original):self.original=original
    def key(self,key):
        state=active();boundary=state['boundary']
        if key not in {'self_tenant_token:'+boundary.value['app_id'],'self_app_token:'+boundary.value['app_id']}:
            raise Failure('unapproved-token-cache')
        return boundary.namespace+':'+key
    def get(self,key):
        value=self.original.get(self.key(key));boundary=active()['boundary']
        return value if isinstance(value,str) and boundary.tokens.get(value,0)>time.time() else None
    def set(self,key,value,expire):
        bound=self.key(key)
        if (not isinstance(value,str) or not TOKEN.fullmatch(value) or type(expire) is not int
                or active()['boundary'].tokens.get(value,0)<=time.time()):
            raise Failure('invalid-token')
        self.original.set(bound,value,expire)


class Boundary:
    def __init__(self,value,current,authorize,redactor):
        self.value=credentials(value,verify_tls=False)
        if not callable(current) or not callable(authorize) or not isinstance(redactor,Redactor):
            raise PermissionError('private publication, grant and redaction callbacks required')
        self.current=current;self.authorize=authorize;self.redactor=redactor
        self.origin=DOMAINS[self.value['domain']];self.namespace=digest([self.value,self.origin]);self.tokens={}
        self.remember(self.value['app_secret'])

    def remember(self,value):
        self.redactor.secrets=sorted(set([*self.redactor.secrets,value,json.dumps(value,ensure_ascii=False)[1:-1],json.dumps(value,ensure_ascii=True)[1:-1],repr(value)[1:-1]]),key=len,reverse=True)

    def check(self,state):
        self.current()
        if state['boundary'] is not self or time.monotonic()>state['deadline']:raise Failure('expired-capability')
        config=state['config']
        if (config.app_id!=self.value['app_id'] or config.app_secret!=self.value['app_secret'] or config.domain!=self.origin):
            raise Failure('changed-client')
        if self.authorize(state['purpose'],deepcopy(state['target'])) is not True:raise Failure('withdrawn-grant')

    @contextmanager
    def operation(self,config,purpose,target):
        if (not isinstance(target,dict) or purpose not in {'account','message'}
                or purpose=='account' and target!={}
                or purpose=='message' and (set(target)!={'message_id'} or not isinstance(target['message_id'],str)
                    or not MESSAGE_ID.fullmatch(target['message_id']))):raise Failure('unapproved-operation')
        with self._operation(config,purpose,target) as state:yield state

    @contextmanager
    def _operation(self,config,purpose,target):
        state={'boundary':self,'config':config,'purpose':purpose,'target':deepcopy(target),
            'deadline':time.monotonic()+30,'auth_requests':0}
        self.check(state);token=_ACTIVE.set(state)
        try:yield state
        finally:_ACTIVE.reset(token)

    def api_request(self,state,method,path,data):
        expected='/open-apis/bot/v3/info' if state['purpose']=='account' else '/open-apis/im/v1/messages/'+state['target']['message_id']
        if method!='GET' or path!=expected or data is not None:raise Failure('unapproved-operation')

    def api_response(self,state,body):pass

    def request(self,real,method,url,**kwargs):
        state=active()
        if state['boundary'] is not self:raise Failure('wrong-account')
        if not isinstance(url,str):raise Failure('unapproved-endpoint')
        address=urlsplit(url)
        if (address.scheme!='https' or address.username or address.password
                or address.query or address.fragment or address.scheme+'://'+address.netloc!=self.origin):
            raise Failure('unapproved-endpoint')
        if set(kwargs)-{'headers','params','data','timeout'}:raise Failure('unapproved-request-options')
        try:headers=dict(kwargs.get('headers') or {})
        except (TypeError,ValueError):raise Failure('invalid-headers') from None
        if (len(headers)>32 or any(not isinstance(key,str) or not isinstance(value,str) or len(key)>128 or len(value)>16384
                or any(char in key+value for char in ['\r','\n','\0']) for key,value in headers.items())):
            raise Failure('invalid-headers')
        folded={key.lower():value for key,value in headers.items()}
        if len(folded)!=len(headers) or set(folded)-{'authorization','content-type','user-agent','accept'}:
            raise Failure('invalid-headers')
        params=kwargs.get('params') or []
        if not isinstance(params,(list,tuple,dict)) or params:raise Failure('unapproved-query')
        auth=method=='POST' and address.path in {'/open-apis/auth/v3/tenant_access_token/internal','/open-apis/auth/v3/app_access_token/internal'}
        data=kwargs.get('data');write=False
        if auth:
            if state['auth_requests']>=2:raise Failure('authentication-budget')
            if not isinstance(data,bytes) or not 1<=len(data)<=16384:raise Failure('invalid-authentication-body')
            try:body=json.loads(data.decode(),object_pairs_hook=_object,parse_constant=finite)
            except (ValueError,UnicodeError):raise Failure('invalid-authentication-body') from None
            if (body!={'app_id':self.value['app_id'],'app_secret':self.value['app_secret']}
                    or any(key.lower() in {'authorization','cookie'} for key in headers)):
                raise Failure('changed-authentication')
            state['auth_requests']+=1;headers.setdefault('Content-Type','application/json; charset=utf-8')
        else:
            write=self.api_request(state,method,address.path,data)
            authorization=folded.get('authorization')
            if not isinstance(authorization,str) or not authorization.startswith('Bearer '):raise Failure('missing-private-token')
            token=authorization[7:]
            if self.tokens.get(token,0)<=time.time():raise Failure('unknown-private-token')
        self.check(state)
        if write:state['write_started']=True
        headers['Accept-Encoding']='identity'
        try:
            response=real(method,url,headers=headers,data=data,params=params,timeout=(3,10),
                stream=True,allow_redirects=False,verify=True)
        except Exception as error:
            import requests
            if isinstance(error,requests.exceptions.SSLError):raise Failure('tls-refused') from None
            raise Failure('transport-unavailable') from None
        try:
            state['http_status']=response.status_code
            if 300<=response.status_code<400:raise Failure('redirect-refused')
            if response.status_code==429:raise Failure('rate-limited')
            if response.status_code in {401,403}:raise Failure('authentication-refused')
            if not 200<=response.status_code<300:raise Failure('server-refused')
            if response.headers.get('Content-Encoding','identity').lower()!='identity':raise Failure('invalid-response')
            limit=16384 if auth else 1024*1024
            length=response.headers.get('Content-Length')
            if length is not None and (not length.isascii() or not length.isdecimal() or not 0<int(length)<=limit):
                raise Failure('response-too-large')
            chunks=[];size=0
            for chunk in response.iter_content(16384):
                self.check(state);size+=len(chunk)
                if size>limit:raise Failure('response-too-large')
                chunks.append(chunk)
            raw=b''.join(chunks)
            if length is not None and int(length)!=len(raw):raise Failure('truncated-response')
            try:body=json.loads(raw.decode('utf-8'),object_pairs_hook=_object,parse_constant=finite)
            except (ValueError,UnicodeError,RecursionError):raise Failure('invalid-response') from None
            if not isinstance(body,dict) or type(body.get('code')) is not int:raise Failure('invalid-response')
            try:bounded(body)
            except Refused:raise Failure('invalid-response') from None
            if auth:
                if body['code']!=0:
                    state['authentication_refused']=True
                    raise Failure('authentication-refused')
                key='tenant_access_token' if 'tenant_access_token' in address.path else 'app_access_token'
                token=body.get(key);expire=body.get('expire')
                if (body['code']!=0 or not isinstance(token,str) or not TOKEN.fullmatch(token)
                        or type(expire) is not int or not 0<expire<=86400):raise Failure('invalid-token')
                self.tokens={old:end for old,end in self.tokens.items() if end>time.time()}
                if token not in self.tokens and len(self.tokens)>=4:raise Failure('token-capacity')
                self.tokens[token]=time.time()+expire;self.remember(token)
            self.check(state)
            if not auth:self.api_response(state,body)
            response._content=raw;response._content_consumed=True
            return response
        except Failure:raise
        except Exception:raise Failure('transport-unavailable') from None
        finally:response.close()


@contextmanager
def sdk_scope():
    """Private SDK module aliases only; never replace the process requests module."""
    with _INSTALL:
        from lark_oapi.core.http import transport
        from lark_oapi.core.token.manager import TokenManager
        from lark_oapi.core.log import logger
        from .gateway_runtime import SafeFormatter
        original_requests=transport.requests;original_cache=TokenManager.cache;original_async=transport.Transport.aexecute
        if isinstance(original_cache,ScopedCache):raise PermissionError('one private SDK transport installation required')
        old_handlers=list(logger.handlers);old_level=logger.level;old_propagate=logger.propagate
        class Formatter(logging.Formatter):
            def format(self,record):
                state=_ACTIVE.get()
                return (SafeFormatter(state['boundary'].redactor).format(record) if state is not None
                    else record.levelname+' '+record.name+' private SDK diagnostic outside active capability')
        handler=logging.StreamHandler();handler.setFormatter(Formatter());logger.handlers=[handler];logger.propagate=False
        def request(method,url,**kwargs):
            state=active();return state['boundary'].request(original_requests.request,method,url,**kwargs)
        async def deny_async(*_args,**_kwargs):raise Failure('async-transport-unavailable')
        transport.requests=SimpleNamespace(request=request);TokenManager.cache=ScopedCache(original_cache)
        transport.Transport.aexecute=staticmethod(deny_async)
        try:yield
        finally:
            transport.requests=original_requests;TokenManager.cache=original_cache
            transport.Transport.aexecute=staticmethod(original_async);logger.handlers=old_handlers;logger.setLevel(old_level);logger.propagate=old_propagate
