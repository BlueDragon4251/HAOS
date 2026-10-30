"""Bounded Google SDK callback-token validation in the private transport.

No token or foreign credential file is returned or persisted. The callback
listener, durable original store and independent grants remain separate gates.
"""
import hashlib
import json
import threading
import time
from types import SimpleNamespace
import urllib.request

from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object
from .gateway_google_chat_admission import Refused

CERTS='https://www.googleapis.com/oauth2/v1/certs'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):raise Refused('certificate-service-unavailable')


class CertificateRequest:
    def __init__(self,current):
        if not callable(current):raise TypeError('current private transport authority required')
        self.current=current;self.lock=threading.Lock();self.cached=None;self.deadline=0
        # Cert requests contain no account auth. Ignore ambient credentialed
        # proxies; this is the product's isolated transport, not a global hook.
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())

    def __call__(self,url,method='GET',**kwargs):
        self.current()
        if url!=CERTS or method!='GET' or kwargs:raise Refused('invalid-certificate-request')
        with self.lock:
            if self.cached is not None and time.monotonic()<self.deadline:return SimpleNamespace(status=200,data=self.cached)
            try:
                with self.opener.open(urllib.request.Request(CERTS,method='GET'),timeout=5) as response:
                    if response.status!=200 or response.geturl()!=CERTS:raise Refused('certificate-service-unavailable')
                    length=response.headers.get('Content-Length')
                    if length is not None and (not length.isdecimal() or int(length)>131072):raise Refused('certificate-service-unavailable')
                    raw=response.read(131073)
                if len(raw)>131072:raise Refused('certificate-service-unavailable')
                value=json.loads(raw.decode('utf-8'),object_pairs_hook=_object,parse_constant=finite)
                # The Google OAuth2 endpoint is an X509 map. Refuse JWK mode:
                # its SDK branch constructs an independent unbounded fetcher.
                if (not isinstance(value,dict) or not 1<=len(value)<=32 or any(
                        not isinstance(k,str) or not 1<=len(k)<=128 or k=='keys' or not isinstance(v,str)
                        or not 1<=len(v.encode())<=16384 or not v.startswith('-----BEGIN CERTIFICATE-----') for k,v in value.items())):
                    raise Refused('certificate-service-unavailable')
            except Refused:raise
            except Exception:raise Refused('certificate-service-unavailable') from None
            self.current();self.cached=raw;self.deadline=time.monotonic()+300
            return SimpleNamespace(status=200,data=raw)


class TokenVerifier:
    def __init__(self,audience,expected_email,current,*,certificate_request=None):
        if (not isinstance(audience,str) or not 1<=len(audience)<=2048 or not isinstance(expected_email,str)
                or not 1<=len(expected_email)<=320 or not callable(current)):
            raise ValueError('exact saved callback audience, identity and current authority required')
        self.audience=audience;self.email=expected_email;self.current=current
        self.request=certificate_request if certificate_request is not None else CertificateRequest(current)

    def verify(self,headers):
        self.current()
        # The HTTP server passes raw pairs, retaining duplicate Authorization
        # fields instead of a mapping that silently chooses one credential.
        if not isinstance(headers,(list,tuple)) or len(headers)>64:raise Refused('invalid-authentication')
        tokens=[]
        for pair in headers:
            if not isinstance(pair,(list,tuple)) or len(pair)!=2:raise Refused('invalid-authentication')
            name,value=pair
            if (not isinstance(name,str) or not isinstance(value,str) or not 1<=len(name)<=128
                    or len(value)>16384 or any(c in name+value for c in ['\r','\n','\0'])):raise Refused('invalid-authentication')
            if name.lower()=='authorization':tokens.append(value)
        if len(tokens)!=1 or not tokens[0].startswith('Bearer '):raise Refused('invalid-authentication')
        token=tokens[0][7:]
        if not token or any(not 33<=ord(c)<=126 for c in token) or ' ' in token:raise Refused('invalid-authentication')
        from google.oauth2 import id_token
        try:
            claims=id_token.verify_oauth2_token(token,self.request,audience=self.audience)
            if (claims.get('email')!=self.email or claims.get('email_verified') is not True
                    or type(claims.get('iat')) is not int or type(claims.get('exp')) is not int
                    or not 0<claims['exp']-claims['iat']<=7200):raise ValueError('unexpected caller')
        except Refused:raise
        except Exception:raise Refused('invalid-authentication') from None
        self.current()
        return {'caller_sha256':hashlib.sha256(self.email.encode()).hexdigest(),
            'token_sha256':hashlib.sha256(token.encode()).hexdigest(),'authenticated_at':time.time()}
