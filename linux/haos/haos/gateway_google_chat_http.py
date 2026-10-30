"""Per-client bounded HTTP with one transmission and no redirect/global hooks."""
import time
import json
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs



class TokenError(RuntimeError):
    def __init__(self,category,status,delay,reason):
        self.category=category;self.http_status=status;self.retry_after=delay;self.reason=reason
        super().__init__('private Google token operation failed')


def token_response(uri,response,data,*,redactor=None):
    if uri!='https://oauth2.googleapis.com/token':return response,data
    if response.status==200:
        try:
            from .gateway_line_ingress import _object
            from .gateway_dingtalk_admission import finite
            value=json.loads(data.decode('utf-8'),object_pairs_hook=_object,parse_constant=finite)
            if (not isinstance(value,dict) or not isinstance(value.get('access_token'),str)
                    or not 1<=len(value['access_token'])<=16384 or any(not 33<=ord(c)<=126 for c in value['access_token'])
                    or value.get('token_type')!='Bearer' or type(value.get('expires_in')) is not int
                    or not 1<=value['expires_in']<=86400):raise ValueError('invalid token response')
            if redactor is not None:
                from .redaction import Redactor
                aliases=[value[k] for k in ['access_token','refresh_token','id_token','rapt_token'] if isinstance(value.get(k),str)]
                if any(len(s)>16384 for s in aliases):raise ValueError('bounded private token fields required')
                secrets=Redactor([*redactor.secrets,*aliases]).secrets
                if len(secrets)>4096 or sum(len(s) for s in secrets)>8*1024*1024:raise ValueError('private redaction capacity reached')
                redactor.secrets=secrets
        except (ValueError,UnicodeError,TypeError,RecursionError):raise TokenError('authentication-refused',200,0,'invalid-token-response') from None
        return response,data
    from .gateway_google_chat_retry import retry_after
    status=response.status;category='rate-limited' if status==429 else 'authentication-refused' if status in {400,401,403} else 'transport-unavailable'
    reason='token-refused'
    try:
        from .gateway_line_ingress import _object
        from .gateway_dingtalk_admission import finite
        value=json.loads(data.decode('utf-8'),object_pairs_hook=_object,parse_constant=finite)
        if isinstance(value,dict) and value.get('error') in {'invalid_grant','invalid_client','unauthorized_client','access_denied',
                'temporarily_unavailable','rate_limit_exceeded','invalid_scope'}:reason=value['error']
    except (ValueError,UnicodeError,TypeError,RecursionError):pass
    delay=retry_after(SimpleNamespace(resp=response)) if status==429 else 0
    raise TokenError(category,status,delay,reason)


def single_request_http(current,*,fixture_origin=None,limit=1048576,redactor=None,oauth_revoke=False):
    if type(oauth_revoke) is not bool:raise ValueError('explicit private OAuth revocation transport required')
    if not callable(current) or type(limit) is not int or not 1<=limit<=8388608:raise ValueError('bounded private HTTP authority required')
    import httplib2
    from .redaction import Redactor
    if redactor is not None and not isinstance(redactor,Redactor):raise TypeError('shared private credential redactor required')
    if fixture_origin is not None:
        parsed=urlsplit(fixture_origin)
        if ((parsed.scheme,parsed.hostname) not in {('http','127.0.0.1'),('https','localhost')}
                or not parsed.port or parsed.path not in {'','/'} or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('only explicit loopback fixture transport override supported')
    class SingleRequestHttp(httplib2.Http):
        def __init__(self):
            super().__init__(timeout=10,proxy_info=None)
            self.follow_redirects=False;self.follow_all_redirects=False

        def request(self,uri,method='GET',body=None,headers=None,redirections=0,connection_type=None):
            current();parsed=urlsplit(uri)
            official=(parsed.scheme=='https' and parsed.port in {None,443}
                and (parsed.hostname=='chat.googleapis.com' or parsed.hostname=='oauth2.googleapis.com' and (parsed.path=='/token'
                    or oauth_revoke and parsed.path=='/revoke' and method=='POST' and not parsed.query)))
            fixture=fixture_origin is not None and uri.startswith(fixture_origin.rstrip('/')+'/')
            if (not (official or fixture) or parsed.username or parsed.password or parsed.fragment
                    or method not in {'GET','POST'} or connection_type is not None):
                raise PermissionError('exact private Google Chat or OAuth HTTP operation required')
            if body is not None and (not isinstance(body,(str,bytes)) or len(body.encode() if isinstance(body,str) else body)>9*1024*1024):
                raise ValueError('bounded Google HTTP request bytes required')
            if redactor is not None:
                aliases=[]
                for name,value in (headers or {}).items():
                    if name.lower()=='authorization':
                        if not isinstance(value,str) or not 1<=len(value)<=16384:raise ValueError('bounded private Google authorization required')
                        aliases.extend([value,value.split(' ',1)[-1]])
                if parsed.hostname=='oauth2.googleapis.com' and body:
                    parts=parse_qs(body.decode('utf-8') if isinstance(body,bytes) else body,strict_parsing=True)
                    for name in ['assertion','client_secret','refresh_token']:
                        aliases.extend(parts.get(name,[]))
                secrets=Redactor([*redactor.secrets,*aliases]).secrets
                if len(secrets)>4096 or sum(len(s) for s in secrets)>8*1024*1024:raise ValueError('private Google credential redaction capacity reached')
                # Capture SDK-generated access/assertion values before wire I/O
                # or native error/log handling can observe a reflected token.
                redactor.secrets=secrets
            headers=dict(headers or {});headers={k:v for k,v in headers.items() if k.lower()!='accept-encoding'}
            headers['accept-encoding']='identity'
            response,data=super().request(uri,method=method,body=body,headers=headers,redirections=0)
            # google-auth otherwise retries token endpoint 429/5xx internally.
            # Keep token errors finite and leave retry timing to the journal.
            return token_response(uri,response,data,redactor=redactor)

        def _request(self,conn,host,absolute_uri,request_uri,method,body,headers,redirections,cachekey):
            # httplib2's default _conn_request reconnects and repeats a POST
            # after BadStatusLine, even with googleapiclient num_retries=0.
            # Keep a single wire attempt; leave uncertain reconciliation to
            # the persistent operation ledger. No global RETRIES mutation.
            current();deadline=time.monotonic()+15
            try:
                if conn.sock is None:conn.connect()
                current();conn.request(method,request_uri,body,headers)
                response=conn.getresponse()
                length=response.getheader('Content-Length');encoding=response.getheader('Content-Encoding','identity')
                if (length is not None and (not length.isdecimal() or int(length)>limit) or encoding!='identity'):
                    raise ValueError('Google HTTP response exceeds approved bounds or encoding')
                content=bytearray()
                while True:
                    current()
                    if time.monotonic()>deadline:raise TimeoutError('private Google HTTP operation deadline')
                    block=response.read(min(8192,limit+1-len(content)))
                    if not block:break
                    content.extend(block)
                    if len(content)>limit:raise ValueError('Google HTTP response exceeds approved bound')
                current();return httplib2.Response(response),bytes(content)
            finally:conn.close()
    return SingleRequestHttp()
