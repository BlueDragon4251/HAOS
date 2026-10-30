"""Prepared private actual Google OAuth SDK with a bounded per-session transport."""
import asyncio
import hashlib
import json
from urllib.parse import urlsplit,parse_qs

from .gateway_google_chat_oauth import AUTH_URI,TOKEN_URI,REDIRECT_URI,CHAT_SCOPE,SCOPES


from dataclasses import dataclass,field

_GRANT_SEAL=object()


@dataclass(frozen=True)
class _VerifiedGrant:
    pending_id:str
    subject:str
    credential_json:str=field(repr=False)
    nonce_sha256:str
    seal:object=field(repr=False)


def _checked_grant(value):
    if not isinstance(value,_VerifiedGrant) or value.seal is not _GRANT_SEAL:
        raise PermissionError('actual private Google SDK verified grant required; no serialized claim authority')
    private();return value


def private():
    from .gateway_runtime import require_runtime_identity
    require_runtime_identity()


def flow(row):
    private()
    # Keep the actual pinned Hermes OAuth protocol contract; its CLI/global
    # token files and in-chat setup handler are never enabled in HAOS.
    from plugins.platforms.google_chat import oauth as native
    if native._REDIRECT_URI!=REDIRECT_URI or native.SCOPES!=[CHAT_SCOPE]:raise PermissionError('pinned Google Chat OAuth protocol changed')
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(json.loads(row['client']),scopes=list(SCOPES),state=row['state'],
        redirect_uri=REDIRECT_URI,code_verifier=row['verifier'],autogenerate_code_verifier=False)


def authorization(row):
    private();sdk=flow(row)
    try:
        url,state=sdk.authorization_url(state=row['state'],nonce=row['nonce'],access_type='offline',prompt='consent',include_granted_scopes='false')
    finally:sdk.oauth2session.close()
    parsed=urlsplit(url);params=parse_qs(parsed.query,strict_parsing=True,max_num_fields=16)
    expected=hashlib.sha256(row['verifier'].encode()).digest()
    import base64
    challenge=base64.urlsafe_b64encode(expected).rstrip(b'=').decode()
    if (parsed.scheme!='https' or parsed.netloc!='accounts.google.com' or parsed.path!='/o/oauth2/auth' or parsed.fragment
            or state!=row['state'] or params.get('state')!=[row['state']] or params.get('nonce')!=[row['nonce']]
            or params.get('redirect_uri')!=[REDIRECT_URI] or params.get('code_challenge')!=[challenge]
            or params.get('code_challenge_method')!=['S256'] or params.get('response_type')!=['code']
            or set(params.get('scope',[''])[0].split())!=set(SCOPES)):
        raise PermissionError('actual Google OAuth authorization differs from private PKCE intent')
    return {'id':row['id'],'authorization_url':url,'subject':row['subject'],'expires_at':row['expires_at'],
        'network_requested':False,'message_sent':False,'private_verifier_or_credentials_returned':False}


def transport(sdk,current,redactor,*,http=None):
    private();current()
    import requests
    from .gateway_google_chat_http import single_request_http,token_response
    wire=http if http is not None else single_request_http(current,redactor=redactor)
    class SingleExchange(requests.adapters.BaseAdapter):
        count=0
        def send(self,request,**_kwargs):
            private();current();self.count+=1
            if request.url!=TOKEN_URI or request.method!='POST' or self.count!=1:
                raise PermissionError('one fixed Google OAuth code exchange required; no redirect or SDK retry')
            body=request.body
            if not isinstance(body,(str,bytes)):raise ValueError('bounded Google OAuth form required')
            response,data=wire.request(TOKEN_URI,method='POST',body=body,headers=dict(request.headers),redirections=0)
            response,data=token_response(TOKEN_URI,response,data,redactor=redactor);current()
            result=requests.Response();result.status_code=response.status;result.headers=requests.structures.CaseInsensitiveDict(dict(response))
            result._content=data;result.encoding='utf-8';result.url=TOKEN_URI;result.request=request
            return result
        def close(self):
            if hasattr(wire,'close'):wire.close()
    sdk.oauth2session.trust_env=False;sdk.oauth2session.adapters.clear();sdk.oauth2session.mount('https://',SingleExchange())


async def exchange(store,policy,connector,account,identity,returned_url,*,owner_uid,http=None,certificate_request=None):
    private()
    row,code=store.exchange(policy(),connector,account,identity,returned_url,owner_uid=owner_uid)
    def current():
        private();store._current(row,policy(),connector,account)
    redactor=store.inbox.redactor
    from .redaction import Redactor
    config=json.loads(row['client'])['installed']
    redactor.secrets=Redactor([*redactor.secrets,config['client_secret'],row['verifier'],code]).secrets
    sdk=flow(row);transport(sdk,current,redactor,http=http)
    def request():
        current();sdk.fetch_token(code=code,include_client_id=True,timeout=10,allow_redirects=False)
        tokens=sdk.oauth2session.token
        if not isinstance(tokens,dict) or set(str(tokens.get('scope','')).split())!=set(SCOPES):
            # oauthlib can normalize the returned scope into a sequence.
            if not isinstance(tokens.get('scope'),(list,tuple)) or set(tokens['scope'])!=set(SCOPES):
                raise PermissionError('Google OAuth did not grant the exact requested Chat/OpenID scopes')
        signed=tokens.get('id_token')
        if not isinstance(signed,str) or not 1<=len(signed)<=16384:raise PermissionError('signed Google stable-user identity token required')
        from google.oauth2 import id_token
        from .gateway_google_chat_auth import CertificateRequest
        claims=id_token.verify_oauth2_token(signed,certificate_request or CertificateRequest(current),audience=config['client_id'])
        current();subject=store.identity(row,claims);credentials=sdk.credentials
        if credentials.client_id!=config['client_id'] or credentials.client_secret!=config['client_secret'] or not credentials.refresh_token:
            raise PermissionError('exact refreshable Google user credentials required')
        return {'subject':subject,'credentials':json.loads(credentials.to_json()),'claims_nonce_sha256':hashlib.sha256(row['nonce'].encode()).hexdigest()}
    try:result=await asyncio.to_thread(request)
    finally:sdk.oauth2session.close()
    current()
    # This opaque private result is accepted only by the token journal. Never
    # serialize it in an Owner/Agent response.
    return row,_VerifiedGrant(row['id'],result['subject'],json.dumps(result['credentials'],sort_keys=True,separators=(',',':')),result['claims_nonce_sha256'],_GRANT_SEAL)
