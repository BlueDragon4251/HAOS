#!/usr/bin/env python3
"""Actual native Lark SDK through a bounded, verified loopback TLS read boundary."""
import asyncio
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import logging
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
from unittest.mock import patch


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_feishu import DOMAINS
    from haos.gateway_feishu_http import Boundary,Failure,sdk_scope
    from haos.gateway_matrix_profile import scope
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    cases=[];seen=[];state={'mode':'ok','allowed':True,'current':True}
    message='om_'+'a'*32
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-http-fixture',
        'domain':'feishu','tenant_key':'tenant_fixture','bot_open_id':'ou_'+'b'*32,'connection_mode':'websocket'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def reply(self,status,body,**headers):
            raw=body if isinstance(body,bytes) else json.dumps(body).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)))
            for key,item in headers.items():self.send_header(key,item)
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_POST(self):
            assert self.path=='/open-apis/auth/v3/tenant_access_token/internal'
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['app_id']==value['app_id'] and body['app_secret'] in {value['app_secret'],value['app_secret']+'-rotated'}
            seen.append(('auth',body['app_secret']))
            self.reply(200,{'code':0,'tenant_access_token':'fixture-private-token-'+str(len(seen)),'expire':7200})
        def do_GET(self):
            assert self.headers['Authorization'].startswith('Bearer fixture-private-token-')
            seen.append(('GET',self.path));mode=state['mode']
            if mode=='redirect':return self.reply(302,{},Location='/must-never-follow')
            if mode in {'401','429','500'}:return self.reply(int(mode),{'code':0})
            if mode=='oversize':return self.reply(200,b' '* (1024*1024+1))
            if mode=='duplicate':return self.reply(200,b'{"code":0,"code":0}')
            if mode=='infinite':return self.reply(200,b'{"code":0,"value":1e999}')
            if mode=='malformed':return self.reply(200,b'{')
            if mode=='truncated':
                self.send_response(200);self.send_header('Content-Length','100');self.end_headers()
                self.wfile.write(b'{');self.close_connection=True;return
            if mode=='withdraw':state['allowed']=False
            if self.path.endswith('/bot/v3/info'):
                return self.reply(200,{'code':0,'bot':{'open_id':value['bot_open_id'],'app_name':'Fixture Bot'}})
            assert self.path=='/open-apis/im/v1/messages/'+message
            self.reply(200,{'code':0,'data':{'items':[{'message_id':message,'body':{'content':'{"text":"fixture"}'}}]}})
    def current():
        if not state['current']:raise PermissionError('fixture publication withdrawn')
    def authorize(purpose,target):
        return state['allowed'] and (purpose=='account' and target=={} or purpose=='message' and target=={'message_id':message})
    def refused(call,kind=None):
        before=len(seen)
        try:call()
        except Failure as error:
            if kind:assert error.kind==kind,(error.kind,kind)
        else:raise AssertionError('unapproved SDK operation succeeded')
        return len(seen)-before
    with tempfile.TemporaryDirectory(prefix='haos-feishu-http-') as directory:
        root=Path(directory);create(root,'fixture.invalid')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        old=dict(DOMAINS);origin='https://localhost:'+str(server.server_port);DOMAINS['feishu']=origin;DOMAINS['lark']=origin
        try:
            with patch.dict(os.environ,{'REQUESTS_CA_BUNDLE':str(root/'ca.pem')}),scope(root,{'HERMES_SAFE_MODE':'1'}):
                from plugins.platforms.feishu import adapter as native
                assert native._load_lark_oapi()
                from lark_oapi.core.http.transport import Transport
                from lark_oapi.core.log import logger
                boundary=Boundary(value,current,authorize,Redactor())
                client=native._build_lark_client(value['app_id'],value['app_secret'],origin)
                def account():return client.request(native._tenant_get_request('/open-apis/bot/v3/info'))
                def read():return client.im.v1.message.get(native.FeishuAdapter._build_get_message_request(message))
                capture=io.StringIO();parent_capture=io.StringIO();parent_handler=logging.StreamHandler(parent_capture)
                logging.getLogger().addHandler(parent_handler)
                with redirect_stderr(capture),sdk_scope():
                    logger.setLevel(10)
                    assert refused(account,'missing-capability')==0
                    cases.append('native_SDK_without_private_operation_cannot_authenticate_or_reach_network')
                    with boundary.operation(client._config,'account',{}):
                        assert json.loads(account().raw.content)['bot']['open_id']==value['bot_open_id']
                        assert json.loads(account().raw.content)['code']==0
                    assert len([row for row in seen if row[0]=='auth'])==1
                    cases.append('actual_native_SDK_verifies_TLS_obtains_private_token_and_reuses_account_scoped_cache')
                    with boundary.operation(client._config,'message',{'message_id':message}):
                        assert read().data.items[0].message_id==message
                        assert refused(account,'unapproved-operation')==0
                    cases.append('exact_owner_message_read_uses_actual_native_builder_and_rejects_account_lookup_in_message_scope')
                    assert refused(lambda:boundary.operation(client._config,'message',{'message_id':'om_'+'c'*32}).__enter__(),'withdrawn-grant')==0
                    cases.append('unapproved_message_is_rejected_before_token_or_network_access')
                    for mode,kind in [('redirect','redirect-refused'),('401','authentication-refused'),('429','rate-limited'),
                        ('500','server-refused'),('oversize','response-too-large'),('duplicate','invalid-response'),
                        ('infinite','invalid-response'),('malformed','invalid-response'),('truncated','transport-unavailable')]:
                        state['mode']=mode
                        with boundary.operation(client._config,'account',{}):assert refused(account,kind)==1
                        cases.append('actual_native_SDK_'+mode+'_response_refused_without_retry_or_redirect')
                    state['mode']='withdraw'
                    with boundary.operation(client._config,'account',{}):assert refused(account,'withdrawn-grant')==1
                    state['allowed']=True;state['mode']='ok'
                    cases.append('owner_grant_withdrawn_during_actual_HTTP_read_prevents_SDK_response_release')
                    with boundary.operation(client._config,'account',{}):
                        client._config.domain='https://unapproved.invalid'
                        assert refused(account,'changed-client')==0
                        client._config.domain=origin
                        assert refused(lambda:asyncio.run(Transport.aexecute(client._config,native._tenant_get_request('/open-apis/bot/v3/info'))),'async-transport-unavailable')==0
                    cases.append('mutated_client_and_separate_async_SDK_transport_cannot_bypass_private_boundary')
                    for changed in [dict(value,app_secret=value['app_secret']+'-rotated'),dict(value,domain='lark')]:
                        other=Boundary(changed,current,authorize,Redactor());other_client=native._build_lark_client(changed['app_id'],changed['app_secret'],origin)
                        before=len([row for row in seen if row[0]=='auth'])
                        with other.operation(other_client._config,'account',{}):
                            assert json.loads(other_client.request(native._tenant_get_request('/open-apis/bot/v3/info')).raw.content)['code']==0
                        assert len([row for row in seen if row[0]=='auth'])==before+1
                    cases.append('same_app_id_rotated_secret_and_other_brand_cannot_reuse_first_account_token')
                    with boundary.operation(client._config,'account',{}):
                        for headers in [{'Authorization':'Bearer unregistered-fixture-token'},{'Cookie':'fixture=1'},{'Host':'unapproved.invalid'},{'Transfer-Encoding':'chunked'},
                            {'Authorization':'Bearer x','authorization':'Bearer y'}]:
                            assert refused(lambda:boundary.request(None,'GET',origin+'/open-apis/bot/v3/info',headers=headers))==0
                    cases.append('forged_bearer_cookie_and_case_duplicated_authorization_refused_before_network')
                logging.getLogger().removeHandler(parent_handler)
                assert value['app_secret'] not in parent_capture.getvalue()
                assert all(token not in parent_capture.getvalue() for token in boundary.tokens)
                output=capture.getvalue()
                assert output and value['app_secret'] not in output
                assert all(token not in output for token in boundary.tokens)
                cases.append('actual_native_SDK_debug_logs_redacted_and_raw_records_not_propagated_to_parent_handlers')
                (root/'untrusted').mkdir();create(root/'untrusted','untrusted.invalid')
                with patch.dict(os.environ,{'REQUESTS_CA_BUNDLE':str(root/'untrusted'/'ca.pem')}),sdk_scope():
                    with boundary.operation(client._config,'account',{}):assert refused(account,'tls-refused')==0
                cases.append('untrusted_TLS_issuer_refused_before_HTTP_application_request')
        finally:
            DOMAINS.clear();DOMAINS.update(old);server.shutdown();server.server_close();thread.join(timeout=5)
    report={'passed':len(cases),'cases':cases,'actual_native_SDK_and_verified_TLS':True,
        'all_targets_loopback_fixtures':True,'public_feishu_enabled':False,
        'kernel_identity_publication_transport_delivery_GUI_or_live_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
