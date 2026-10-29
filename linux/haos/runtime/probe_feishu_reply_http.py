#!/usr/bin/env python3
"""Actual native send and SDK reply over closed, verified loopback TLS."""
import asyncio
from contextlib import redirect_stderr
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import logging
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
from unittest.mock import patch


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_feishu import DOMAINS
    from haos.gateway_feishu_http import Failure,sdk_scope
    from haos.gateway_feishu_reply_http import ReplyBoundary
    from haos.gateway_feishu_send import wire_target,bind_single_native_send
    from haos.gateway_matrix_profile import scope
    from haos.redaction import Redactor
    from haos.gateway_runtime import SafeFormatter
    from webhook_tls_fixture import create
    cases=[];seen=[];state={'mode':'ok','expected':None,'allowed':True}
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-reply-http-fixture','domain':'feishu',
        'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def reply(self,status,body,**headers):
            data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)))
            for name,item in headers.items():self.send_header(name,item)
            self.end_headers();self.wfile.write(data)
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path=='/open-apis/auth/v3/tenant_access_token/internal':
                assert body=={'app_id':value['app_id'],'app_secret':value['app_secret']}
                seen.append('auth')
                if state['mode']=='auth401':return self.reply(401,{'code':0})
                return self.reply(200,{'code':0,'tenant_access_token':'fixture-private-reply-token','expire':7200})
            expected=state['expected'];assert self.path=='/open-apis/im/v1/messages/'+expected['reply_to']+'/reply'
            assert self.headers['Authorization']=='Bearer fixture-private-reply-token'
            assert body=={'content':expected['content'],'msg_type':expected['msg_type'],'uuid':expected['uuid'],
                'reply_in_thread':bool(expected['thread_id'])}
            seen.append(('reply',deepcopy(body)));mode=state['mode']
            if mode=='drop':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();self.close_connection=True;return
            if mode=='429':return self.reply(429,{'code':0})
            if mode=='redirect':return self.reply(307,{'code':0},Location='/never-create-new-topic')
            if mode=='missing':return self.reply(200,{'code':230011,'msg':'source message missing'})
            if mode=='invalidpost':return self.reply(200,{'code':230001,'msg':'content format of the post type is incorrect'})
            self.reply(200,{'code':0,'data':{'message_id':'om_'+'d'*32,'chat_id':expected['chat_id']}})
    with tempfile.TemporaryDirectory(prefix='haos-feishu-reply-http-') as directory:
        root=Path(directory);create(root,'fixture.invalid');server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        server.socket=tls.wrap_socket(server.socket,server_side=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='https://localhost:'+str(server.server_port);old=DOMAINS['feishu'];DOMAINS['feishu']=origin
        try:
            with patch.dict(os.environ,{'REQUESTS_CA_BUNDLE':str(root/'ca.pem')}),scope(root,{'HERMES_SAFE_MODE':'1'}):
                from plugins.platforms.feishu import adapter as native
                from gateway.config import PlatformConfig
                assert native._load_lark_oapi()
                redactor=Redactor([value['app_secret']]);capture=io.StringIO();handler=logging.StreamHandler(capture);handler.setFormatter(SafeFormatter(redactor))
                old_handlers=list(native.logger.handlers);old_propagate=native.logger.propagate
                native.logger.handlers=[handler];native.logger.propagate=False
                try:
                    with redirect_stderr(capture),sdk_scope():
                        for label,mode,body,topic in [('text','ok','Actual native TLS reply ä 🤖.',''),
                            ('markdown','ok','**Native markdown reply**',''),('native_topic','ok','Actual topic reply.','omt_'+'e'*32),
                            ('dropped_connection','drop','May have been accepted.',''),('rate_limit','429','Not accepted.',''),
                            ('redirect','redirect','No route fallback.',''),('missing_source','missing','No top-level fallback.',''),
                            ('post_fallback','invalidpost','**No implicit second post**',''),('authentication','auth401','No token, no write.','')]:
                            state['mode']=mode;state['allowed']=True;adapter=native.FeishuAdapter(PlatformConfig(enabled=True))
                            blueprint={'chat_id':'oc_'+'c'*32,'thread_id':topic,'source_id':'om_'+'f'*32,'body':body,'uuid':'a'*32}
                            exact=wire_target(adapter,blueprint);state['expected']=exact;bind_single_native_send(adapter,exact)
                            client=native._build_lark_client(value['app_id'],value['app_secret'],origin);adapter._client=client
                            boundary=ReplyBoundary(value,lambda:None,lambda purpose,target:state['allowed'] and purpose=='reply' and target==exact,redactor)
                            before=len([item for item in seen if isinstance(item,tuple)])
                            with boundary.operation(client._config,'reply',exact) as operation:
                                result=await_send(native,adapter,blueprint)
                                if mode=='ok':
                                    assert result.success and result.message_id=='om_'+'d'*32
                                    assert operation['reply_response']['data']['chat_id']==exact['chat_id']
                                else:assert result.success is False
                                assert operation['write_started'] is (mode!='auth401')
                                if mode!='auth401':
                                    try:client.im.v1.message.reply(native.FeishuAdapter._build_reply_message_request(exact['reply_to'],
                                        native.FeishuAdapter._build_reply_message_body(content=exact['content'],msg_type=exact['msg_type'],
                                            reply_in_thread=bool(topic),uuid_value=exact['uuid'])))
                                    except Failure:pass
                                    else:raise AssertionError('second native HTTP write escaped one-intent capability')
                            after=len([item for item in seen if isinstance(item,tuple)])
                            assert after-before==(0 if mode=='auth401' else 1)
                            cases.append('actual_native_'+label+'_uses_at_most_one_exact_reply_and_no_new_topic_or_hidden_retry')
                        state['mode']='ok';state['expected']=exact
                        # Changed body/UUID/target cannot begin an API write even with an authenticated token.
                        boundary=ReplyBoundary(value,lambda:None,lambda *_:True,redactor)
                        with boundary.operation(client._config,'reply',exact) as operation:
                            before=len(seen)
                            bad=native.FeishuAdapter._build_reply_message_body(content=exact['content'],msg_type=exact['msg_type'],reply_in_thread=False,uuid_value='b'*32)
                            try:client.im.v1.message.reply(native.FeishuAdapter._build_reply_message_request(exact['reply_to'],bad))
                            except Failure as error:assert error.kind=='changed-reply'
                            else:raise AssertionError('changed native UUID admitted')
                            assert not operation['write_started'] and not any(isinstance(item,tuple) for item in seen[before:])
                        cases.append('changed_native_UUID_refused_before_any_message_write')
                finally:native.logger.handlers=old_handlers;native.logger.propagate=old_propagate
                assert value['app_secret'] not in capture.getvalue() and 'fixture-private-reply-token' not in capture.getvalue()
                cases.append('actual_native_send_failure_and_SDK_diagnostics_remain_credential_redacted')
        finally:DOMAINS['feishu']=old;server.shutdown();server.server_close();thread.join(timeout=5)
    report={'passed':len(cases),'cases':cases,'actual_native_send_and_SDK_verified_TLS':True,
        'only_loopback_fixture_replies_no_external_messages':True,'owner_grant_callbacks_are_fixtures':True,
        'durable_delivery_worker_and_public_send_connected':False,'public_feishu_enabled':False,'live_account_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


def await_send(native,adapter,blueprint):
    return asyncio.run(native.FeishuAdapter.send(adapter,blueprint['chat_id'],blueprint['body'],reply_to=blueprint['source_id'],
        metadata={'thread_id':blueprint['thread_id']}))


if __name__=='__main__':main()
