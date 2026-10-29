#!/usr/bin/env python3
"""Actual Hermes media lookup and Robot SDK/SPI/models over verified loopback TLS."""
import asyncio,json,socket,ssl,sys,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    import httpx,requests,dingtalk_stream.stream as stream
    from plugins.platforms.dingtalk import adapter as native
    from gateway.config import PlatformConfig
    from haos import gateway_dingtalk_http as token_wire,gateway_dingtalk_tea as tea
    from haos.gateway_dingtalk_http import Boundary,QuietLogger,sdk_scope
    from haos.gateway_dingtalk_tea import Lookup
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    value = {'client_id': 'ding_private_fixture_app', 'client_secret': 'private-dingtalk-custody-fixture',
             'corp_id': 'ding_fixture_corporation', 'robot_code': 'ding_fixture_robot'}
    grant = {'id': 'owner', 'connector': 'dingtalk', 'sender': '$:LWCP_v1:$opaque-owner',
             'chat': 'cidExactConversation/+=', 'scope': scope(value), 'thread': '',
             'identity': 'personal', 'capabilities': ['create', 'read'], 'generation': 'a' * 64,
             'since': 1, 'require_mention': True}
    config = {'version': 1, 'connectors': [{'id': 'dingtalk', 'platform': 'dingtalk'}], 'bindings': [grant]}
    policy = lambda: PreparedDingTalkPolicy(config)
    now = int(time.time() * 1000)
    body = {'msgId': 'nativeMessage-123', 'createAt': now - 1000, 'senderId': grant['sender'],
            'conversationId': grant['chat'], 'conversationType': '1', 'chatbotCorpId': value['corp_id'],
            'senderCorpId': value['corp_id'], 'robotCode': value['robot_code'], 'msgtype': 'text',
            'text': {'content': 'Durably approved native goal.'},
            'sessionWebhook': 'https://oapi.dingtalk.com/robot/sendBySession?session=private-original-session',
            'sessionWebhookExpiredTime': now + 7200000}
    cases=[];state={'mode':'ok'};seen=[];live=[True]
    code='private-resource-code-fixture';access='private-resource-access-token'
    class Server(ThreadingHTTPServer):
        def handle_error(self,*_args):pass
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers.get('Accept-Encoding')=='identity' and self.headers.get('Cookie') is None
            seen.append(self.path);mode=state['mode'];status=200
            if self.path=='/v1.0/oauth2/accessToken':
                assert body=={'appKey':value['client_id'],'appSecret':value['client_secret']}
                data={'accessToken':access,'expireIn':7200};mode='ok'
            else:
                assert self.path=='/v1.0/robot/messageFiles/download'
                assert body=={'downloadCode':code,'robotCode':value['robot_code']}
                assert self.headers['x-acs-dingtalk-access-token']==access and self.headers['Host']=='api.dingtalk.com'
                data={'downloadUrl':'https://cdn.fixture.invalid/object?cap=private-file-capability'}
                if mode in {'401','429','500','302'}:status=int(mode)
                if mode=='bad-url':data['downloadUrl']='http://cdn.fixture.invalid/object'
                if mode=='ip-url':data['downloadUrl']='https://127.0.0.1/object'
                if mode=='app-secret-in-url':data['downloadUrl']='https://cdn.fixture.invalid/object?cap='+value['client_secret']
                if mode=='token-in-url':data['downloadUrl']='https://cdn.fixture.invalid/object?cap='+access
                if mode=='bool-url':data['downloadUrl']=True
            raw=json.dumps(data).encode()
            if mode=='duplicate':raw=b'{"downloadUrl":"https://cdn.fixture.invalid/a","downloadUrl":"https://cdn.fixture.invalid/b"}'
            if mode=='nonfinite':raw=b'{"downloadUrl":"https://cdn.fixture.invalid/a","extra":NaN}'
            if mode=='large':raw=json.dumps({**data,'padding':'x'*70000}).encode()
            if mode=='drop':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if mode=='withdraw':live[0]=False
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)+(10 if mode=='truncated' else 0)))
            self.send_header('Connection','close');self.send_header('Set-Cookie','private-native-lookup=not-forwarded')
            if mode=='302':self.send_header('Location','https://unreviewed.invalid/never')
            if mode=='encoding':self.send_header('Content-Encoding','gzip')
            self.end_headers()
            try:self.wfile.write(raw);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            self.close_connection=True
    with tempfile.TemporaryDirectory(prefix='haos-dingtalk-lookup-') as td:
        directory=Path(td);create(directory,'lookup.fixture.invalid')
        server=Server(('127.0.0.1',0),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(directory/'certificate.pem',directory/'key.pem');server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='https://localhost:'+str(server.server_port)
        verified=ssl.create_default_context(cafile=str(directory/'ca.pem'));actual_client=httpx.AsyncClient
        def fixture_client(**kwargs):return actual_client(**kwargs,**({} if state['mode']=='untrusted-tls' else {'verify':verified}))
        original_api,original_stream,original_tea=token_wire.API,stream.DINGTALK_OPENAPI_ENDPOINT,tea.API
        token_wire.API=stream.DINGTALK_OPENAPI_ENDPOINT=tea.API=origin
        def current():
            if not live[0]:raise PermissionError('fixture publication withdrawn')
        async def exercise():
            redactor=Redactor();owner=Boundary(value,current,redactor);client=owner.client()
            owner.session=requests.Session();owner.session.trust_env=False;owner.session.headers.clear()
            owner.session.headers['Accept-Encoding']='identity';owner.session.verify=str(directory/'ca.pem')
            with private_scope(directory,{'HERMES_SAFE_MODE':'1'}):
                adapter=native.DingTalkAdapter(PlatformConfig(enabled=True,extra={'client_id':value['client_id'],
                    'client_secret':value['client_secret'],'robot_code':value['robot_code']}))
            adapter._stream_client=client;adapter._robot_sdk=native.dingtalk_robot_client.Client(
                native.open_api_models.Config(protocol='https',region_id='central'))
            with sdk_scope(),owner.operation('token',client):token=await adapter._get_access_token()
            assert token==access and token in owner.tokens
            logger=native.logger;native.logger=QuietLogger()
            try:
                for mode in ['ok','401','429','500','302','bad-url','ip-url','app-secret-in-url','token-in-url',
                    'bool-url','duplicate','nonfinite','large','drop','truncated','encoding','untrusted-tls','withdraw']:
                    live[0]=True;state['mode']=mode;obj={'downloadCode':code};before=len(seen)
                    lookup=Lookup(owner,token,code,current)
                    with patch.object(httpx,'AsyncClient',fixture_client),tea.sdk_scope(lookup):
                        await adapter._fetch_download_url(code,value['robot_code'],token,obj,'downloadCode')
                    assert len(seen)==before+(0 if mode=='untrusted-tls' else 1)
                    if mode=='ok':
                        assert obj['downloadCode']==lookup.url=='https://cdn.fixture.invalid/object?cap=private-file-capability'
                        assert redactor.text(lookup.url)!=lookup.url
                    else:
                        assert obj['downloadCode']==code
                        if mode in {'401','429','500','302'}:
                            assert lookup.failure=={'401':'authentication-refused','429':'rate-limited','500':'server-refused','302':'redirect-refused'}[mode]
                        elif mode=='untrusted-tls':assert lookup.failure=='tls-refused'
                        elif mode!='withdraw':assert lookup.failure is not None
                    cases.append('actual_Hermes_fetch_download_url_Robot_generated_SDK_SPI_response_model_verified_TLS_'+mode+'_one_closed_request_no_token_or_code_to_agent')
                live[0]=True
                for wrong_code,wrong_robot in [('unapproved-private-resource',value['robot_code']),(code,'ding_other_robot')]:
                    obj={'downloadCode':code};lookup=Lookup(owner,token,code,current);before=len(seen)
                    with tea.sdk_scope(lookup):
                        await adapter._fetch_download_url(wrong_code,wrong_robot,token,obj,'downloadCode')
                    assert len(seen)==before and obj['downloadCode']==code and not lookup.used
                cases.append('actual_SDK_builder_changed_resource_or_robot_identity_refused_before_network')
                try:Lookup(owner,'unobserved-private-token',code,current)
                except PermissionError:pass
                else:raise AssertionError('unobserved SDK token accepted')
                cases.append('unobserved_private_token_cannot_authorize_Robot_lookup')
            finally:native.logger=logger;owner.close()
        try:asyncio.run(exercise())
        finally:
            token_wire.API=original_api;stream.DINGTALK_OPENAPI_ENDPOINT=original_stream;tea.API=original_tea
            server.shutdown();server.server_close();thread.join(timeout=5)
    result={'cases':cases,'scope':'Actual Hermes token/media helpers and Robot SDK request/SPI/response over real verified loopback TLS; only API origins and fixture CA are substituted.',
        'binary_content_fetch_UID_mission_live_account_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
