#!/usr/bin/env python3
"""Real SDK token/discovery builders over verified loopback HTTPS; no messages."""
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import requests
    import dingtalk_stream.stream as sdk
    from dingtalk_stream import ChatbotMessage
    from gateway.config import PlatformConfig
    from plugins.platforms.dingtalk import adapter as native
    from haos import gateway_dingtalk_http as wire
    from haos.gateway_dingtalk_http import Boundary,Failure,sdk_scope
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    value={'client_id':'ding_private_fixture_app','client_secret':'private-dingtalk-http-fixture',
        'corp_id':'ding_fixture_corporation','robot_code':'ding_fixture_robot'}
    state={'mode':'ok'};seen=[];live=[True];cases=[]
    class Server(ThreadingHTTPServer):
        def handle_error(self,*_args):pass  # Expected TLS/client-close fixture faults.
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers.get('Cookie') is None and self.headers.get('Accept-Encoding')=='identity'
            seen.append(self.path)
            if self.path=='/v1.0/oauth2/accessToken':
                assert body=={'appKey':value['client_id'],'appSecret':value['client_secret']}
                result={'accessToken':'private-dingtalk-access-token-fixture','expireIn':300 if state['mode']=='short' else 7200,'requestId':'public-fixture-request'}
            else:
                assert self.path=='/v1.0/gateway/connections/open'
                assert body['clientId']==value['client_id'] and body['clientSecret']==value['client_secret'] and body['localIp']==''
                assert body['subscriptions']==[{'type':'CALLBACK','topic':ChatbotMessage.TOPIC}]
                result={'endpoint':'wss://wss-open-connection.dingtalk.com:443/connect','ticket':'private-dingtalk-ticket-fixture','requestId':'public-fixture-request'}
            mode=state['mode'];status=200
            if mode in {'401','429','500'}:status=int(mode);result={'error':value['client_secret']}
            if mode=='bad-ttl':result['expireIn']=True
            if mode=='bad-token':result['accessToken']='short'
            if mode=='bad-endpoint':result['endpoint']='wss://other.invalid/connect'
            if mode=='bad-ticket':result['ticket']='short'
            raw=json.dumps(result).encode()
            if mode=='duplicate':raw=b'{"accessToken":"private-fixture-access-token","expireIn":7200,"expireIn":1}'
            if mode=='nonfinite':raw=b'{"accessToken":"private-fixture-access-token","expireIn":NaN}'
            if mode=='large':raw=json.dumps({'padding':'x'*70000}).encode()
            if mode=='drop':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if mode=='redirect':status=302
            if mode=='withdraw':live[0]=False
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)+(12 if mode=='truncated' else 0)))
            self.send_header('Connection','close');self.send_header('Set-Cookie','private-session=must-not-be-forwarded')
            if mode=='redirect':self.send_header('Location','https://other.invalid/private')
            if mode=='encoding':self.send_header('Content-Encoding','gzip')
            self.end_headers()
            try:self.wfile.write(raw);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            self.close_connection=True
    with tempfile.TemporaryDirectory(prefix='haos-dingtalk-http-') as td:
        root=Path(td);create(root,'dingtalk.fixture.invalid')
        server=Server(('127.0.0.1',0),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(root/'certificate.pem',root/'key.pem');server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='https://localhost:'+str(server.server_port)
        original_api,original_sdk,original_connection=wire.API,sdk.DINGTALK_OPENAPI_ENDPOINT,sdk.DingTalkStreamClient.OPEN_CONNECTION_API
        wire.API=base;sdk.DINGTALK_OPENAPI_ENDPOINT=base;sdk.DingTalkStreamClient.OPEN_CONNECTION_API=base+'/v1.0/gateway/connections/open'
        def current():
            if not live[0]:raise PermissionError('fixture owner publication withdrawn')
        def boundary(trusted=True):
            result=Boundary(value,current,Redactor());result.session=requests.Session();result.session.trust_env=False
            result.session.headers.clear();result.session.headers['Accept-Encoding']='identity'
            if trusted:result.session.verify=str(root/'ca.pem')
            return result
        def run(b,client,purpose):
            with sdk_scope(),b.operation(purpose,client) as operation:
                result=client.get_access_token() if purpose=='token' else client.open_connection()
            return result,operation['requests']
        try:
            b=boundary();client=b.client();result,count=run(b,client,'token')
            assert result=='private-dingtalk-access-token-fixture' and count==1 and b.failure is None
            again,count=run(b,client,'token');assert again==result and count==0 and len(seen)==1
            assert b.redactor.text(result)!=result
            cases.append('actual_native_SDK_token_builder_and_verified_TLS_preserve_vendor_metadata_and_reuse_only_observed_private_cache')
            adapter=native.DingTalkAdapter(PlatformConfig(enabled=True,extra={'client_id':value['client_id'],'client_secret':value['client_secret']}))
            client.register_callback_handler(ChatbotMessage.TOPIC,native._IncomingHandler(adapter))
            connection,count=run(b,client,'connection')
            assert count==1 and connection['ticket']=='private-dingtalk-ticket-fixture' and b.failure is None
            assert b.redactor.text(connection['ticket'])!=connection['ticket']
            cases.append('actual_SDK_connection_builder_has_only_native_chatbot_subscription_and_no_extra_IP_probe_or_forwarded_cookie')
            second=boundary();foreign=second.client();foreign._access_token=deepcopy(client._access_token);before=len(seen)
            try:run(second,foreign,'token')
            except Failure as error:assert error.kind=='invalid-token'
            else:raise AssertionError('unobserved private SDK cache reused')
            assert len(seen)==before;second.close()
            cases.append('another_private_boundary_cannot_reuse_an_unobserved_SDK_access_token')
            client._access_token['requestId']='changed metadata';before=len(seen)
            try:run(b,client,'token')
            except Failure as error:assert error.kind=='invalid-token'
            else:raise AssertionError('SDK cache proof changed')
            assert len(seen)==before;b.close()
            cases.append('changed_private_SDK_cache_metadata_is_refused_before_network')
            b=boundary();client=b.client();state['mode']='short';before=len(seen)
            assert run(b,client,'token')[1]==run(b,client,'token')[1]==1 and len(seen)==before+2
            b.close();cases.append('actual_SDK_native_expiry_buffer_refreshes_short_lived_tokens_without_mocking_time')
            for mode,kind in [('401','authentication-refused'),('429','rate-limited'),('500','server-refused'),
                    ('redirect','redirect-refused'),('encoding','invalid-response'),('duplicate','invalid-response'),
                    ('nonfinite','invalid-response'),('large','response-too-large'),('bad-ttl','invalid-response'),
                    ('bad-token','invalid-response'),('truncated','truncated-response'),('drop','transport-unavailable')]:
                state['mode']=mode;b=boundary();client=b.client();before=len(seen);logs=StringIO()
                with redirect_stdout(logs),redirect_stderr(logs):result,count=run(b,client,'token')
                assert result is None and b.failure==kind and count==1 and len(seen)==before+1,(mode,b.failure)
                assert value['client_secret'] not in logs.getvalue() and 'private-dingtalk-access-token-fixture' not in logs.getvalue()
                b.close();cases.append('actual_SDK_'+mode+'_response_refused_with_finite_private_diagnostic_and_no_hidden_retry_or_secret_log')
            for mode in ['bad-endpoint','bad-ticket']:
                state['mode']=mode;b=boundary();client=b.client();client.register_callback_handler(ChatbotMessage.TOPIC,native._IncomingHandler(adapter))
                result,count=run(b,client,'connection');assert result is None and b.failure=='invalid-response' and count==1
                b.close();cases.append('actual_native_discovery_'+mode+'_cannot_become_an_unreviewed_socket_capability')
            state['mode']='ok';b=boundary(False);client=b.client();before=len(seen)
            result,count=run(b,client,'token');assert result is None and b.failure=='tls-refused' and len(seen)==before
            b.close();cases.append('actual_TLS_untrusted_issuer_refused_before_auth_request_without_verify_false')
            b=boundary();client=b.client();client.register_all_event_handler(sdk.EventHandler());before=len(seen)
            result,count=run(b,client,'connection');assert result is None and len(seen)==before and count==0
            b.close();cases.append('actual_SDK_wildcard_event_subscription_is_denied_before_HTTP')
            b=boundary();client=b.client();client.credential.client_secret='changed-private-app-secret';before=len(seen)
            try:run(b,client,'token')
            except PermissionError:pass
            else:raise AssertionError('native SDK credential changed')
            assert len(seen)==before;b.close();cases.append('changed_private_client_identity_cannot_request_another_app_token')
            state['mode']='withdraw';b=boundary();client=b.client()
            try:run(b,client,'token')
            except PermissionError:pass
            else:raise AssertionError('withdrawn owner publication returned a token')
            live[0]=True;b.close();cases.append('owner_withdrawal_during_actual_HTTP_read_cannot_return_a_cached_or_fresh_capability')
        finally:
            wire.API=original_api;sdk.DINGTALK_OPENAPI_ENDPOINT=original_sdk;sdk.DingTalkStreamClient.OPEN_CONNECTION_API=original_connection
            server.shutdown();server.server_close();thread.join(timeout=5)
    result={'passed':len(cases),'cases':cases,'actual_native_SDK_requests_and_verified_loopback_TLS':True,
        'API_origin_and_fixture_CA_substitution_only_in_this_probe':True,'owner_publication_and_UID_are_fixtures':True,
        'live_or_installed_dingtalk_acceptance':False,'external_accounts_messages_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
