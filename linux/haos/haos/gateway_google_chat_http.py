"""Per-client bounded HTTP with one transmission and no redirect/global hooks."""
import time
from urllib.parse import urlsplit


def single_request_http(current,*,fixture_origin=None,limit=1048576):
    if not callable(current) or type(limit) is not int or not 1<=limit<=8388608:raise ValueError('bounded private HTTP authority required')
    import httplib2
    if fixture_origin is not None:
        parsed=urlsplit(fixture_origin)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path not in {'','/'}:
            raise ValueError('only explicit loopback fixture transport override supported')
    class SingleRequestHttp(httplib2.Http):
        def __init__(self):
            super().__init__(timeout=10,proxy_info=None)
            self.follow_redirects=False;self.follow_all_redirects=False

        def request(self,uri,method='GET',body=None,headers=None,redirections=0,connection_type=None):
            current();parsed=urlsplit(uri)
            official=(parsed.scheme=='https' and parsed.port in {None,443}
                and (parsed.hostname=='chat.googleapis.com' or parsed.hostname=='oauth2.googleapis.com' and parsed.path=='/token'))
            fixture=fixture_origin is not None and uri.startswith(fixture_origin.rstrip('/')+'/')
            if (not (official or fixture) or parsed.username or parsed.password or parsed.fragment
                    or method not in {'GET','POST'} or connection_type is not None):
                raise PermissionError('exact private Google Chat or OAuth HTTP operation required')
            if body is not None and (not isinstance(body,(str,bytes)) or len(body.encode() if isinstance(body,str) else body)>9*1024*1024):
                raise ValueError('bounded Google HTTP request bytes required')
            headers=dict(headers or {});headers={k:v for k,v in headers.items() if k.lower()!='accept-encoding'}
            headers['accept-encoding']='identity'
            return super().request(uri,method=method,body=body,headers=headers,redirections=0)

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
