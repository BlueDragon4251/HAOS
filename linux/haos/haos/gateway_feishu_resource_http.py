"""Closed binary SDK reads for an exact independently approved message resource."""
from contextlib import contextmanager
from copy import deepcopy
import re
import time
from urllib.parse import urlsplit

from .gateway_feishu import MESSAGE_ID
from .gateway_feishu_http import Boundary,Failure,active
from .gateway_media import MAX_BYTES,MAX_IMAGE_BYTES


def target(value):
    if (not isinstance(value,dict) or set(value)!={'message_id','file_key','types'}
            or not isinstance(value['message_id'],str) or not MESSAGE_ID.fullmatch(value['message_id'])
            or not isinstance(value['file_key'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,256}',value['file_key'])
            or value['types'] not in [['image'],['file'],['audio','file'],['media','file']]):
        raise Failure('unapproved-operation')
    return deepcopy(value)


class ResourceBoundary(Boundary):
    @contextmanager
    def operation(self,config,purpose,blueprint):
        if purpose!='resource':raise Failure('unapproved-operation')
        exact=target(blueprint)
        with self._operation(config,purpose,exact) as state:
            state['resource_requests']=[]
            yield state

    def check(self,state):
        super().check(state)
        if state.get('resource_blocked'):raise Failure(state['resource_blocked'])

    def request(self,real,method,url,**kwargs):
        state=active()
        if state['boundary'] is not self:raise Failure('wrong-account')
        address=urlsplit(url) if isinstance(url,str) else None
        if address is not None and method=='POST' and address.path in {
                '/open-apis/auth/v3/tenant_access_token/internal','/open-apis/auth/v3/app_access_token/internal'}:
            try:return super().request(real,method,url,**kwargs)
            except Failure as error:
                state['resource_failure']=error.kind
                if error.kind in {'authentication-refused','rate-limited','tls-refused'}:state['resource_blocked']=error.kind
                raise
        exact=target(state['target']);expected='/open-apis/im/v1/messages/'+exact['message_id']+'/resources/'+exact['file_key']
        if (address is None or address.scheme!='https' or address.scheme+'://'+address.netloc!=self.origin
                or address.username or address.password or address.query or address.fragment
                or method!='GET' or address.path!=expected or kwargs.get('data') is not None
                or set(kwargs)-{'headers','params','data','timeout'}):raise Failure('unapproved-operation')
        params=kwargs.get('params');index=len(state['resource_requests'])
        if index>=len(exact['types']) or params!=[('type',exact['types'][index])]:raise Failure('unapproved-query')
        try:headers=dict(kwargs.get('headers') or {})
        except (ValueError,TypeError):raise Failure('invalid-headers') from None
        if (len(headers)>16 or any(not isinstance(key,str) or not isinstance(value,str) or len(key)>128 or len(value)>16384
                or any(ord(char)<32 or ord(char)==127 for char in key+value) for key,value in headers.items())):
            raise Failure('invalid-headers')
        folded={key.lower():value for key,value in headers.items()}
        if len(folded)!=len(headers) or set(folded)-{'authorization','accept','content-type','user-agent'}:
            raise Failure('invalid-headers')
        bearer=folded.get('authorization','')
        if not bearer.startswith('Bearer ') or self.tokens.get(bearer[7:],0)<=time.time():
            raise Failure('unknown-private-token')
        self.check(state);state['resource_requests'].append(exact['types'][index]);headers['Accept-Encoding']='identity'
        try:response=real('GET',url,headers=headers,params=params,data=None,timeout=(3,10),stream=True,allow_redirects=False,verify=True)
        except Exception as error:
            import requests
            raise Failure('tls-refused' if isinstance(error,requests.exceptions.SSLError) else 'transport-unavailable') from None
        try:
            code=response.status_code
            if code in {401,403,429}:
                state['resource_blocked']='rate-limited' if code==429 else 'authentication-refused'
                raise Failure(state['resource_blocked'])
            if 300<=code<400:raise Failure('redirect-refused')
            if code!=200 or response.headers.get('Content-Range') is not None:raise Failure('server-refused')
            if response.headers.get('Content-Encoding','identity').lower()!='identity':raise Failure('invalid-response')
            limit=MAX_IMAGE_BYTES if exact['types']==['image'] else MAX_BYTES
            length=response.headers.get('Content-Length')
            transfer=response.headers.get('Transfer-Encoding')
            if transfer is not None and (transfer.lower()!='chunked' or length is not None):raise Failure('invalid-response')
            if length is not None and (not length.isascii() or not length.isdecimal() or not 0<int(length)<=limit):
                raise Failure('response-too-large')
            mime=response.headers.get('Content-Type','application/octet-stream').split(';',1)[0].strip().lower()
            if not re.fullmatch('[a-z0-9][a-z0-9.+-]{0,126}/[a-z0-9][a-z0-9.+-]{0,126}',mime):raise Failure('invalid-response')
            chunks=[];size=0
            while True:
                self.check(state);chunk=response.raw.read1(16384,decode_content=False)
                if not chunk:break
                size+=len(chunk)
                if size>limit:raise Failure('response-too-large')
                chunks.append(chunk)
            raw=b''.join(chunks)
            if not raw or length is not None and int(length)!=len(raw):raise Failure('truncated-response')
            if any(secret.encode() in raw for secret in self.redactor.secrets):raise Failure('credential-reflection')
            # Native SDK treats every HTTP-200 binary response as success. Its
            # JSON API errors must never masquerade as an owner's attachment.
            disposition=response.headers.get('Content-Disposition','')
            attachment=(len(disposition)<=2048 and not any(ord(char)<32 or ord(char)==127 for char in disposition)
                and re.match(r'(?i)(attachment|inline)\s*;.*\bfilename\s*=',disposition) is not None)
            if mime=='application/json' and not attachment:
                import json
                from .gateway_feishu_http import finite
                from .gateway_line_ingress import _object
                try:body=json.loads(raw,object_pairs_hook=_object,parse_constant=finite)
                except (ValueError,UnicodeError,RecursionError):body=None
                if isinstance(body,dict) and type(body.get('code')) is int:
                    state['resource_blocked']='rate-limited' if body['code']==99991400 else 'server-refused'
                    raise Failure(state['resource_blocked'])
            self.check(state);state.pop('resource_failure',None)
            # Vendor filenames and arbitrary response headers are not host paths
            # or capabilities. The real SDK decodes these bounded original bytes.
            response.headers.clear();response.headers.update({'Content-Type':mime,
                'Content-Length':str(len(raw)),'Content-Disposition':'attachment; filename="attachment.bin"'})
            response._content=raw;response._content_consumed=True
            return response
        except Failure as error:state['resource_failure']=error.kind;raise
        except Exception:
            state['resource_failure']='transport-unavailable'
            raise Failure('transport-unavailable') from None
        finally:response.close()
