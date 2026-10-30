"""Private fixed-brand native Lark WS discovery and closed verified WSS connection.

Caller must establish the private gateway UID, root publication and account
identity. No endpoint URL or connection options are accepted from an agent.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import re
import ssl
import threading
import time
from types import MethodType,SimpleNamespace
from urllib.parse import urlsplit,parse_qsl,quote,quote_plus

from .gateway_feishu import credentials,DOMAINS
from .gateway_feishu_admission import bounded,finite,Refused,MAX_EVENT
from .gateway_line_ingress import _object
from .gateway_feishu_http import Failure
from .redaction import Redactor

WS_SUFFIXES={'feishu':('feishu.cn',),'lark':('larksuite.com',)}
WS_PORTS=frozenset({None,443})
_INSTALL=threading.RLock()
_ACTIVE=ContextVar('haos_private_feishu_ws_connection',default=None)


class QuietLogger(logging.LoggerAdapter):
    """SDK logs include raw endpoint tickets and event bodies; retain only severity."""
    def log(self,level,_message,*_args,**_kwargs):
        if self.isEnabledFor(level):self.logger.log(level,'private Feishu transport diagnostic')


class PrivateSockets:
    def __init__(self,original):self.original=original
    def __getattr__(self,name):return getattr(self.original,name)
    def connect(self,uri,**kwargs):
        owner=_ACTIVE.get()
        if owner is None:raise Failure('missing-capability')
        return owner.connect(uri,**kwargs)


class Discovery:
    def __init__(self,value,current,redactor):
        self.value=credentials(value,verify_tls=False)
        if self.value['connection_mode']!='websocket' or not callable(current) or not isinstance(redactor,Redactor):
            raise PermissionError('private current websocket account and redaction required')
        self.current=current;self.redactor=redactor;self.origin=DOMAINS[self.value['domain']]
        self.url=None;self.config=None;self.client=None;self.requests=None;self.connect_type=None;self.logger=QuietLogger(logging.getLogger('haos.feishu.websocket'),{})
        self.remember(self.value['app_secret'])
    def remember(self,value):
        self.redactor.secrets=sorted(set([*self.redactor.secrets,value]),key=len,reverse=True)
    def check(self,*,capability=True):
        self.current()
        if capability and _ACTIVE.get() is not self:raise Failure('missing-capability')
        if self.client is not None and (self.client._app_id!=self.value['app_id'] or self.client._app_secret!=self.value['app_secret']
                or self.client._domain!=self.origin):raise Failure('changed-client')
    @contextmanager
    def connection_scope(self):
        self.check(capability=False)
        if _ACTIVE.get() is not None:raise Failure('nested-capability')
        token=_ACTIVE.set(self)
        try:yield self
        finally:_ACTIVE.reset(token)
    def endpoint(self,url):
        if not isinstance(url,str) or not 1<=len(url)<=8192 or any(ord(char)<33 or ord(char)>126 for char in url):
            raise Failure('unapproved-endpoint')
        try:
            address=urlsplit(url);host=address.hostname
            if (address.scheme!='wss' or not host or address.username or address.password or address.fragment
                    or address.port not in WS_PORTS or not re.fullmatch('[a-z0-9.-]{1,253}',host) or host.endswith('.')
                    or not any(host==suffix or host.endswith('.'+suffix) for suffix in WS_SUFFIXES[self.value['domain']])
                    or not address.path.startswith('/') or len(address.path)>256 or '%' in address.path
                    or any(part in {'.','..'} for part in address.path.split('/'))
                    or re.search('%(?![0-9a-fA-F]{2})',address.query)):raise ValueError
            query=parse_qsl(address.query,keep_blank_values=True,strict_parsing=True,max_num_fields=16)
            params=dict(query)
            if (len(query)!=len(params) or not {'device_id','service_id'}<=set(params)
                    or not re.fullmatch('[A-Za-z0-9_.:-]{1,256}',params['device_id'])
                    or not re.fullmatch('[1-9][0-9]{0,18}',params['service_id']) or int(params['service_id'])>=2**63
                    or any(not re.fullmatch('[A-Za-z0-9_]{1,64}',key) or not 1<=len(item)<=4096
                        or any(ord(char)<32 or ord(char)==127 for char in item) for key,item in query)):
                raise ValueError
        except (ValueError,TypeError):raise Failure('unapproved-endpoint') from None
        self.remember(url)
        for key,item in query:
            if key in {'device_id','service_id'}:continue  # Public routing IDs aren't credentials.
            for variant in {item,quote(item,safe=''),quote_plus(item,safe='')}:self.remember(variant)
        return url
    def post(self,url,**kwargs):
        self.check();deadline=time.monotonic()+20
        if url!=self.origin+'/callback/ws/endpoint' or set(kwargs)!={'headers','json'}:
            raise Failure('unapproved-operation')
        headers=kwargs['headers'];body=kwargs['json']
        if (not isinstance(headers,dict) or set(headers)!={'locale','User-Agent'} or headers['locale']!='zh'
                or not isinstance(headers['User-Agent'],str) or not 1<=len(headers['User-Agent'])<=2048
                or any(ord(char)<32 or ord(char)==127 for char in headers['User-Agent'])
                or body!={'AppID':self.value['app_id'],'AppSecret':self.value['app_secret']}):
            raise Failure('changed-authentication')
        headers=dict(headers);headers['Accept-Encoding']='identity'
        try:response=self.requests.post(url,headers=headers,json=body,stream=True,allow_redirects=False,verify=True,timeout=(3,10))
        except Exception as error:
            import requests
            raise Failure('tls-refused' if isinstance(error,requests.exceptions.SSLError) else 'transport-unavailable') from None
        try:
            self.check();status=response.status_code
            if 300<=status<400:raise Failure('redirect-refused')
            if status in {401,403}:raise Failure('authentication-refused')
            if status==429:raise Failure('rate-limited')
            if status!=200:raise Failure('server-refused')
            if response.headers.get('Content-Encoding','identity').lower()!='identity':raise Failure('invalid-response')
            length=response.headers.get('Content-Length')
            if length is not None and (not length.isascii() or not length.isdecimal() or not 0<int(length)<=16384):
                raise Failure('response-too-large')
            parts=[];size=0
            while True:
                self.check()
                part=response.raw.read1(4096,decode_content=False)
                if not part:break
                self.check();size+=len(part)
                if size>16384:raise Failure('response-too-large')
                if time.monotonic()>deadline:raise Failure('expired-capability')
                parts.append(part)
            raw=b''.join(parts)
            if length is not None and len(raw)!=int(length):raise Failure('truncated-response')
            try:value=json.loads(raw.decode(),object_pairs_hook=_object,parse_constant=finite);bounded(value)
            except (ValueError,UnicodeError,RecursionError,Refused):raise Failure('invalid-response') from None
            if not isinstance(value,dict) or type(value.get('code')) is not int:raise Failure('invalid-response')
            if value['code']!=0:raise Failure('authentication-refused' if value['code'] in {403,514} else 'server-refused')
            data=value.get('data')
            if not isinstance(data,dict) or set(data)-{'URL','ClientConfig'} or not isinstance(data.get('URL'),str):
                raise Failure('invalid-response')
            conf=data.get('ClientConfig')
            if conf is not None:
                limits={'ReconnectCount':(-1,100),'ReconnectInterval':(1,3600),'ReconnectNonce':(0,120),'PingInterval':(1,3600)}
                if not isinstance(conf,dict) or set(conf)-set(limits):raise Failure('invalid-response')
                for key,item in conf.items():
                    if type(item) is not int or not limits[key][0]<=item<=limits[key][1]:raise Failure('invalid-response')
            self.config=None if conf is None else dict(conf)
            self.url=self.endpoint(data['URL']);self.check()
            response._content=raw;response._content_consumed=True;return response
        except Failure:raise
        except Exception:raise Failure('transport-unavailable') from None
        finally:response.close()
    @contextmanager
    def http_scope(self):
        # The SDK uses its own module requests alias, distinct from REST Transport.
        import lark_oapi.ws.client as sdk
        with _INSTALL:
            original=sdk.requests
            if not hasattr(original,'post'):raise Failure('sdk-unavailable')
            self.requests=original;sdk.requests=SimpleNamespace(post=self.post)
            try:yield
            finally:sdk.requests=original;self.requests=None
    def connect(self,uri,**kwargs):
        self.check()
        if self.url is None or uri!=self.url:raise Failure('unapproved-endpoint')
        if set(kwargs)-{'proxy','ping_interval','ping_timeout'} or kwargs.get('proxy') is not None:
            raise Failure('unapproved-request-options')
        for key in ['ping_interval','ping_timeout']:
            value=kwargs.get(key)
            if value is not None and (type(value) not in {int,float} or not 1<=value<=3600):raise Failure('unapproved-request-options')
        context=ssl.create_default_context()
        return self.connect_type(uri,ssl=context,proxy=None,compression=None,max_size=MAX_EVENT+16384,max_queue=8,
            open_timeout=10,close_timeout=3,ping_interval=kwargs.get('ping_interval',20),ping_timeout=kwargs.get('ping_timeout',20),logger=self.logger)
    def install(self,client):
        from importlib.metadata import version
        import lark_oapi.ws.client as sdk
        from websockets.asyncio.client import connect
        if version('websockets')!='15.0.1' or hasattr(client,'_haos_ws_discovery'):
            raise Failure('sdk-unavailable')
        self.client=client;self.check(capability=False);original=sdk.Client._get_conn_url
        class ClosedConnect(connect):
            def process_redirect(self,exception):return exception
        self.connect_type=ClosedConnect
        with _INSTALL:
            if not isinstance(sdk.websockets,PrivateSockets):
                from plugins.platforms.feishu import adapter as native
                if native._WS_ISOLATION_INSTALLED:raise Failure('sdk-unavailable')
                sdk.websockets=PrivateSockets(sdk.websockets)
        def discover(_client):
            self.check();self.url=None
            with self.http_scope():url=original(_client)
            if self.url is None or url!=self.url:raise Failure('changed-endpoint')
            self.check();return url
        client._get_conn_url=MethodType(discover,client);client._haos_ws_discovery=self
        # A dedicated facade must be passed to the actual native runner's
        # thread-local connect seam; do not replace the global websockets module.
        sdk.logger=QuietLogger(sdk.logger.logger if isinstance(sdk.logger,QuietLogger) else sdk.logger,{})
        return client
