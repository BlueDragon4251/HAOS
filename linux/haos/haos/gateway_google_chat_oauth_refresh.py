"""Private actual Google credentials refresh, bounded and durably fenced."""
import asyncio
import hashlib
import json
import time

from .gateway_google_chat_oauth import SCOPES
from .gateway_google_chat_oauth_tokens import TokenVault,Deferred
from .gateway_google_chat_oauth_sdk import private,_VerifiedGrant,_GRANT_SEAL


async def access(store,policy,connector,account,selected,before_io,*,http=None,certificate_request=None):
    private()
    if not callable(before_io):raise PermissionError('current private operation capability required')
    before_io();vault=TokenVault(store);snapshot=vault.load(policy(),connector,account,selected)
    row=snapshot['row'];payload=snapshot['payload'];config=snapshot['configuration']['installed']
    def current():
        private();before_io()
        from .gateway_google_chat_oauth import route
        binding=route(policy(),connector,account,selected['binding_id'],selected['binding_digest'])
        if binding['sender']!=row['subject']:raise PermissionError('Google refresh stable source user changed')
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import Request
    from .gateway_google_chat_http import single_request_http,TokenError
    from .redaction import Redactor
    redactor=store.inbox.redactor
    redactor.secrets=Redactor([*redactor.secrets,*[payload[k] for k in ['token','refresh_token','client_secret','rapt_token'] if payload.get(k)]]).secrets
    sdk=Credentials.from_authorized_user_info(payload,scopes=list(SCOPES))
    if sdk.valid:current();return sdk,snapshot
    intent=vault.begin_refresh(snapshot)
    base_request=Request(http=http if http is not None else single_request_http(current,redactor=redactor));observed={}
    def request(*args,**kwargs):
        response=base_request(*args,**kwargs)
        if response.status==200:
            value=json.loads(response.data)
            observed.update({key:value[key] for key in ['access_token','refresh_token'] if isinstance(value.get(key),str)})
        return response
    def refresh():
        current();sdk.refresh(request);current()
        granted=sdk.granted_scopes
        if granted is not None and (not isinstance(granted,(list,tuple)) or any(not isinstance(item,str) for item in granted) or set(granted)!=set(SCOPES)):
            raise PermissionError('Google user refresh lost required scopes')
        if not sdk.valid or sdk.client_id!=config['client_id'] or sdk.client_secret!=config['client_secret']:
            raise PermissionError('Google user refresh returned unusable or different credentials')
        if sdk.id_token:
            from google.oauth2 import id_token
            from .gateway_google_chat_auth import CertificateRequest
            claims=id_token.verify_oauth2_token(sdk.id_token,certificate_request or CertificateRequest(current),audience=config['client_id'])
            if (claims.get('sub')!=row['subject'].split('/',1)[1] or claims.get('azp',config['client_id'])!=config['client_id']
                    or claims.get('aud')!=config['client_id'] or type(claims.get('iat')) is not int or type(claims.get('exp')) is not int
                    or not 0<claims['exp']-claims['iat']<=7200 or claims['exp']<=time.time()):
                raise PermissionError('refreshed Google identity differs from the approved stable user or client')
            nonce=claims.get('nonce')
            if nonce is not None and (not isinstance(nonce,str) or hashlib.sha256(nonce.encode()).hexdigest()!=row['nonce_sha256']):
                raise PermissionError('refreshed Google nonce differs from retained enrollment')
        current();encoded=json.dumps(json.loads(sdk.to_json()),sort_keys=True,separators=(',',':'))
        return _VerifiedGrant(intent,row['subject'],encoded,row['nonce_sha256'],_GRANT_SEAL)
    try:
        verified=await asyncio.to_thread(refresh);current();vault.finish_refresh(snapshot,intent,verified)
    except Exception as error:
        if isinstance(error,TokenError):
            status='rate-limited' if error.category=='rate-limited' else 'authentication-refused' if error.category=='authentication-refused' else 'refresh-uncertain'
            delay=error.retry_after if status=='rate-limited' else 0
        elif isinstance(error,PermissionError):status='authentication-refused';delay=0
        else:status='refresh-uncertain';delay=0
        # If commit itself was ambiguous, preserve its durable state rather
        # than blindly overwriting a possible confirmed refresh receipt.
        state=store.db.execute('SELECT state FROM google_chat_oauth_refreshes WHERE id=?',(intent,)).fetchone()
        if state is not None and state['state']=='writing':vault.failed_refresh(snapshot,intent,status,retry_after=delay)
        if observed and state is not None and state['state']!='confirmed':
            from .gateway_google_chat_oauth import quarantine_refresh
            quarantine_refresh(store,snapshot,intent,observed,'identity-refused' if status=='authentication-refused' else 'storage-unavailable')
        raise Deferred(status,delay) from None
    current();return sdk,vault.load(policy(),connector,account,selected)
