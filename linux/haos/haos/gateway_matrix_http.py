"""Private Matrix SDK HTTP boundary; no public gateway or mission authority."""
import hashlib
import inspect
import json
import math
from types import MethodType
from urllib.parse import unquote,urlsplit


def homeserver_url(value):
    from .gateway_mattermost import server_url
    try:return server_url(value)
    except ValueError:raise ValueError('provide an unambiguous Matrix HTTPS homeserver without embedded credentials') from None


class HTTPBoundary:
    def __init__(self,server,user,device,*,allow_room_read=None,allow_write=None,allow_login=False,allow_recovery=False):
        self.server=homeserver_url(server)
        if (not isinstance(user,str) or not user.startswith('@') or ':' not in user or len(user.encode())>255
                or not isinstance(device,str) or not 1<=len(device.encode())<=255
                or any(ord(c)<32 or ord(c)==127 for c in user+device)):
            raise ValueError('explicit bounded Matrix user/device identity required')
        self._target=self.server
        self.user,self.device=user,device
        self.allow_room_read=allow_room_read or (lambda _room:False)
        self.allow_write=allow_write or (lambda _method,_path:False)
        self.allow_login=allow_login is True;self.allow_recovery=allow_recovery is True
        self._token_digest=None;self._client=None;self.last_status=None;self.last_retry_after=5

    def confirm(self,client,proof):
        if (client is not self._client or str(getattr(proof,'user_id',''))!=self.user or str(getattr(proof,'device_id',None) or '')!=self.device
                or str(client.mxid)!=self.user or str(client.device_id or '')!=self.device
                or not isinstance(client.api.token,str) or not client.api.token):
            raise PermissionError('Matrix HTTP identity was not confirmed by the actual SDK response')
        self._token_digest=hashlib.sha256(client.api.token.encode()).digest()

    def revoke(self):
        self._token_digest=None;self._client=None

    def path(self,url):
        actual=urlsplit(str(url));target=urlsplit(self._target)
        actual_port=actual.port or (443 if actual.scheme=='https' else 80)
        target_port=target.port or (443 if target.scheme=='https' else 80)
        if (actual.scheme,actual.hostname,actual_port)!=(target.scheme,target.hostname,target_port) or actual.username is not None or actual.password is not None or actual.fragment:
            raise PermissionError('Matrix request target differs from the approved private homeserver')
        prefix=target.path.rstrip('/')
        if not actual.path.startswith(prefix+'/_matrix/client/'):
            raise PermissionError('Matrix request path is outside the approved client API')
        parts=actual.path[len(prefix):].split('/')[1:]
        if len(parts)<4 or parts[:2]!=['_matrix','client'] or parts[2] not in {'v1','v3','r0'}:
            raise PermissionError('Matrix protocol endpoint is not approved')
        try:logical=tuple(unquote(value,errors='strict') for value in parts[3:])
        except (ValueError,UnicodeError):raise PermissionError('invalid Matrix protocol path') from None
        if any(any(ord(c)<32 or ord(c)==127 for c in value) for value in logical):
            raise PermissionError('invalid Matrix protocol identity')
        return logical

    def authorize(self,api,method,url,query):
        if self._client is None or api is not self._client.api:
            raise PermissionError('Matrix request belongs to a superseded private client')
        path=self.path(url);method=str(method)
        if any(key in query for key in ('access_token','user_id','device_id','org.matrix.msc3202.device_id')):
            raise PermissionError('Matrix impersonation and credential query parameters are forbidden')
        if method=='GET' and path==('account','whoami'):return
        if method=='POST' and path==('login',) and self.allow_login:return
        if (self._token_digest is None or not isinstance(api.token,str)
                or hashlib.sha256(api.token.encode()).digest()!=self._token_digest):
            raise PermissionError('Matrix private account requires confirmed stable token identity')
        if method=='GET':
            if path in {('sync',),('keys','changes'),('joined_rooms',)}:return
            if len(path)==4 and path[0]=='user' and path[1]==self.user and path[2]=='account_data':return
            if (len(path)>=3 and path[0]=='rooms' and path[2] in {'state','members','joined_members','event','messages','relations'}
                    and self.allow_room_read(path[1]) is True):return
        if method=='POST' and path in {('keys','query'),('keys','upload'),('keys','claim')}:return
        if method=='POST' and path==('keys','signatures','upload') and self.allow_recovery:return
        if method in {'POST','PUT'} and self.allow_write(method,path) is True:return
        raise PermissionError('Matrix operation has no explicit private authorization')

    def bind(self,client):
        api=client.api;self._client=client;self._token_digest=None;self.last_status=None;self.last_retry_after=5
        existing=getattr(api,'_haos_matrix_http_boundary',None)
        if existing is not None:
            if existing is not self:raise PermissionError('Matrix API already belongs to another private boundary')
            return client
        # The pinned aiohttp transport independently retries idempotent HTTP
        # methods on a lost connection, including Matrix PUT sends. SDK retry
        # settings alone do not prevent this second wire dispatch.
        if type(getattr(api.session,'_retry_connection',None)) is not bool:
            raise RuntimeError('Matrix private HTTP retry contract changed')
        api.session._retry_connection=False
        api._haos_matrix_http_boundary=self
        original_request=api.request
        signature=inspect.signature(original_request)
        boundary=self
        async def request(self,*args,**kwargs):
            bound=signature.bind(*args,**kwargs)
            bound.arguments['retry_count']=0;bound.arguments['sensitive']=True
            return await original_request(*bound.args,**bound.kwargs)
        async def send(self,method,url,content,query_params,headers):
            import aiohttp
            from mautrix.errors import make_request_error
            boundary.authorize(self,method,url,query_params)
            size=len(content.encode()) if isinstance(content,str) else len(content) if isinstance(content,(bytes,bytearray)) else 0
            if size>8*1024*1024:
                raise ValueError('Matrix request exceeds private size bound')
            if content is not None and not isinstance(content,(str,bytes,bytearray)):
                raise PermissionError('Matrix streaming uploads require a separate approved media path')
            try:
                async with self.session.request(str(method),url,data=content,params=query_params,headers=headers,
                        allow_redirects=False,timeout=aiohttp.ClientTimeout(total=45)) as response:
                    boundary.last_status=response.status
                    data=bytearray();limit=8*1024*1024 if 200<=response.status<300 else 65536
                    async for chunk in response.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data)>limit:raise ValueError('Matrix response exceeds private size bound')
                    try:value=json.loads(data)
                    except (ValueError,UnicodeError):value=None
                    if not 200<=response.status<300:
                        known={'M_UNKNOWN_TOKEN','M_MISSING_TOKEN','M_FORBIDDEN','M_NOT_FOUND','M_LIMIT_EXCEEDED',
                            'M_BAD_JSON','M_NOT_JSON','M_TOO_LARGE','M_INVALID_PARAM','M_UNRECOGNIZED','M_UNKNOWN',
                            'M_UNAUTHORIZED','M_RESOURCE_LIMIT_EXCEEDED'}
                        code=value.get('errcode') if isinstance(value,dict) else None
                        if code not in known:code=None
                        error=make_request_error(response.status,'Matrix request refused',code,'Matrix request refused')
                        milliseconds=value.get('retry_after_ms') if isinstance(value,dict) else None
                        delay=milliseconds/1000 if type(milliseconds) in {int,float} else None
                        if delay is None:
                            try:delay=float(response.headers.get('Retry-After','5'))
                            except ValueError:delay=5
                        if not math.isfinite(delay):delay=5
                        error.retry_after=min(86400,max(1,delay))
                        boundary.last_retry_after=error.retry_after
                        raise error
                    if not isinstance(value,dict):raise ValueError('Matrix response has no native JSON object')
                    return value,response
            except aiohttp.ClientError:
                # No provider response bodies, request headers or credentials
                # enter logs through a raw SDK exception string.
                raise ConnectionError('Matrix private connection unavailable') from None
        # SDK request logging runs before our wire admission. Do not let an
        # unapproved credential query/body reach that logger, even at DEBUG.
        api._log_request=MethodType(lambda self,*args,**kwargs:None,api)
        api.request=MethodType(request,api);api._send=MethodType(send,api)
        api.default_retry_count=0
        return client
