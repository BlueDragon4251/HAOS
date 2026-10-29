#!/usr/bin/env python3
"""Actual native DingTalk sender/httpx/TLS with fixture-only origin substitution."""
import asyncio
import base64
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
from unittest.mock import patch
import time


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    import httpx
    from gateway.config import PlatformConfig
    from plugins.platforms.dingtalk.adapter import DingTalkAdapter
    from haos.gateway import digest
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    from haos.gateway_dingtalk_send import specification,wire_target,invoke_native,ExpiredSession
    from haos.gateway_dingtalk_reply_http import Boundary,Refused
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
    native_payload={'msgtype':'markdown','markdown':{'title':'Hermes','text':'Native reply.\n\n1. numbered item\n```text\ncode\n```'}}
    class Server(ThreadingHTTPServer):
        def handle_error(self,*_args):pass
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_args):pass
        def do_POST(self):
            assert self.path=='/robot/sendBySession?session=private-original-session'
            assert self.headers.get('Cookie') is None and self.headers.get('Accept-Encoding')=='identity'
            received=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert received==native_payload;seen.append(received)
            mode=state['mode'];status=200;data={'errcode':0,'errmsg':'ok'}
            if mode in {'401','429','302','500'}:status=int(mode)
            if mode=='native-error':data={'errcode':40014,'errmsg':'private-original-session'}
            if mode=='bool-code':data['errcode']=False
            raw=json.dumps(data).encode()
            if mode=='duplicate':raw=b'{"errcode":0,"errcode":1,"errmsg":"ok"}'
            if mode=='nonfinite':raw=b'{"errcode":0,"errmsg":"ok","extra":NaN}'
            if mode=='large':raw=json.dumps({**data,'padding':'x'*70000}).encode()
            if mode=='drop':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if mode=='withdraw':live[0]=False
            self.send_response(status);self.send_header('Content-Type','text/plain' if mode=='wrong-type' else 'application/json')
            self.send_header('Content-Length',str(len(raw)+(10 if mode=='truncated' else 0)))
            self.send_header('Connection','close');self.send_header('Set-Cookie','private-fixture=never-forward')
            if mode=='429':self.send_header('Retry-After','120')
            if mode=='302':self.send_header('Location','https://unapproved.invalid/never')
            if mode=='encoding':self.send_header('Content-Encoding','gzip')
            self.end_headers()
            try:self.wfile.write(raw);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            self.close_connection=True
    with tempfile.TemporaryDirectory(prefix='haos-dingtalk-reply-') as td:
        directory=Path(td);create(directory,'reply.fixture.invalid')
        server=Server(('127.0.0.1',0),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(directory/'certificate.pem',directory/'key.pem')
        server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        verified=ssl.create_default_context(cafile=str(directory/'ca.pem'))
        actual_client=httpx.AsyncClient
        class Loopback(httpx.AsyncBaseTransport):
            def __init__(self):self.real=httpx.AsyncHTTPTransport(verify=verified,retries=0)
            async def handle_async_request(self,request):
                assert request.method=='POST' and request.url.host=='oapi.dingtalk.com' and request.url.scheme=='https'
                assert request.url.port in {None,443}
                target=request.url.copy_with(host='localhost',port=server.server_port)
                forwarded=httpx.Request(request.method,target,headers=request.headers,content=request.content,extensions=request.extensions)
                return await self.real.handle_async_request(forwarded)
            async def aclose(self):await self.real.aclose()
        def fixture_client(**kwargs):
            assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
            return actual_client(**kwargs,transport=Loopback())
        async def exercise():
            def current():
                if not live[0]:raise PermissionError('fixture owner withdrawal')
            with private_scope(directory,{'HERMES_SAFE_MODE':'1'}):
                adapter=DingTalkAdapter(PlatformConfig(enabled=True,extra={
                    'client_id':value['client_id'],'client_secret':value['client_secret'],
                    'robot_code':value['robot_code'],'card_template_id':''}))
            raw=json.dumps(body).encode()
            intent={'binding_id':grant['id'],'binding_digest':digest(grant),'delivery_id':'b'*64,'attempt':1,
                'source_id':body['msgId'],'source_sha256':hashlib.sha256(raw).hexdigest(),
                'source_base64':base64.b64encode(raw).decode(),'body':'Native reply.\n1. numbered item\n    ```text\ncode\n    ```'}
            for mode in ('ok','native-error','401','429','302','500','drop','truncated','bool-code',
                         'duplicate','nonfinite','large','wrong-type','encoding','withdraw'):
                live[0]=True;state['mode']=mode;redactor=Redactor();blueprint=specification(value,policy(),'dingtalk',intent,redactor)
                target=wire_target(adapter,blueprint);assert target['payload']==native_payload
                transport=Boundary(target,blueprint['session_expires_at'],current,redactor);before=len(seen)
                with patch.object(httpx,'AsyncClient',fixture_client):
                    try:result=await invoke_native(adapter,blueprint,transport,current)
                    except PermissionError:
                        assert mode=='withdraw' and transport.state=='uncertain'
                    else:
                        if mode=='ok':
                            assert result['state']=='confirmed' and result['acceptance_id'].startswith('haos-dingtalk-')
                            assert result['remote_message_id'] is None and result['recipient_read_verified'] is False
                        elif mode in {'native-error','401','429'}:
                            assert result=={'state':'rejected','error':{'native-error':'native-refused','401':'authentication-refused','429':'rate-limited'}[mode],
                                'retry_after':120 if mode=='429' else 0}
                        else:assert result=={'state':'uncertain'}
                assert len(seen)==before+1 and adapter._http_client is None
                assert 'private-original-session' not in json.dumps(result if mode!='withdraw' else {})
                live[0]=True
                try:await transport.post(target['url'],json=target['payload'],timeout=15.0)
                except Refused:pass
                else:raise AssertionError('second native write allowed under same closed intent')
                assert len(seen)==before+1
                await transport.close();cases.append('actual_native_sender_verified_TLS_httpx_'+mode+'_one_write_closed_vendor_ACK_honest_local_receipt_or_refusal_uncertainty')
            for change in ({'source_id':'different-message'},{'source_sha256':'0'*64},{'body':'private-original-session'},
                           {'body':value['client_secret']},{'attempt':True},{'source_base64':'not-base64'}):
                try:specification(value,policy(),'dingtalk',{**intent,**change},Redactor())
                except (ValueError,PermissionError):pass
                else:raise AssertionError('mutated source/intent or private reflection admitted')
            cases.append('actual_original_native_projection_refuses_wrong_source_hash_message_private_reflection_attempt_and_encoding')
            grant['capabilities']=['create']
            try:specification(value,policy(),'dingtalk',{**intent,'binding_digest':digest(grant)},Redactor())
            except PermissionError:pass
            else:raise AssertionError('create-only grant authorized reply')
            grant['capabilities']=['create','read'];cases.append('creation_only_owner_grant_cannot_authorize_native_reply')
            expired={**body,'sessionWebhookExpiredTime':now-500};raw=json.dumps(expired).encode()
            try:specification(value,policy(),'dingtalk',{**intent,'source_base64':base64.b64encode(raw).decode(),
                'source_sha256':hashlib.sha256(raw).hexdigest()},Redactor())
            except ExpiredSession:pass
            else:raise AssertionError('expired session started native write')
            cases.append('expired_original_session_refused_without_write_or_implicit_alternate_route')
        try:asyncio.run(exercise())
        finally:server.shutdown();server.server_close();thread.join(timeout=5)
    result={'cases':cases,'scope':'Actual native sender and httpx with real verified loopback TLS; only fixture transport substitutes the official origin.',
        'parent_journal_UID_live_messages_and_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
