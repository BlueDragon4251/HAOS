#!/usr/bin/env python3
"""Actual native WS discovery POST and actual verified WSS/SDK frame ACK, loopback only."""
import asyncio
from contextlib import redirect_stdout,redirect_stderr
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import time
from unittest.mock import patch


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_feishu import DOMAINS
    from haos import gateway_feishu_ws_http as wire
    from haos.gateway_feishu_ws_frames import Bridge,install as frames
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    from haos.gateway_feishu_cache import RawEvents
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    from haos.gateway_matrix_profile import scope as private_scope
    from webhook_tls_fixture import create
    cases=[]
    async def exercise(root):
        from aiohttp import web,WSMsgType
        from plugins.platforms.feishu import adapter as native
        assert native._load_lark_oapi()
        import lark_oapi.ws.client as sdk
        from lark_oapi.core.enum import LogLevel
        value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-ws-http-fixture','domain':'feishu',
            'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
        binding={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),
            'thread':'','identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':1}
        policy=PreparedFeishuPolicy({'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding]})
        create(root,'fixture.invalid');server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        seen=[];state={'mode':'ok','allowed':True,'url':None};ticket='private-fixture-websocket-ticket';acknowledged=asyncio.Event();redirect_hits=[]
        cache=RawEvents(root/'originals.db',Redactor([value['app_secret']]),lambda:None);inbox=NativeInbox(root/'native.db',cache.redactor)
        def commit(raw):
            item=cache.capture(policy,'feishu',value,raw)
            return inbox.admit(policy,'feishu',item['envelope'],{'raw_id':item['id']},received_at=item['received_at'])
        async def socket(request):
            assert request.secure and request.query.get('ticket')==ticket
            if state['mode']=='wsredirect':raise web.HTTPTemporaryRedirect('/must-never-follow')
            connection=web.WebSocketResponse();await connection.prepare(request)
            stamp=str(int(time.time()*1000)-1000)
            data=json.dumps({'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1','app_id':value['app_id'],
                'tenant_key':value['tenant_key'],'create_time':stamp},'event':{'sender':{'sender_id':{'open_id':binding['sender']},
                'sender_type':'user','tenant_key':value['tenant_key']},'message':{'message_id':'om_'+'f'*32,'create_time':stamp,
                    'chat_id':binding['chat'],'chat_type':'p2p','message_type':'text','content':json.dumps({'text':'Actual native WSS source 1.'})}}}).encode()
            frame=sdk.Frame();frame.SeqID=0;frame.LogID=0;frame.method=sdk.FrameType.DATA.value;frame.service=1;frame.payload=data
            for key,item in {'message_id':'fixture_ws_message','trace_id':'fixture_trace','sum':'1','seq':'0','type':'event'}.items():
                header=frame.headers.add();header.key=key;header.value=item
            await connection.send_bytes(frame.SerializeToString())
            response=await connection.receive(timeout=10);assert response.type==WSMsgType.BINARY
            reply=sdk.Frame();reply.ParseFromString(response.data);body=json.loads(reply.payload)
            assert body['code']==200 and inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
            acknowledged.set();await connection.close();return connection
        async def redirected(_request):redirect_hits.append(True);return web.Response(status=500)
        app=web.Application();app.router.add_get('/ws/v2',socket);app.router.add_get('/must-never-follow',redirected)
        runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=server_tls);await site.start()
        ws_port=site._server.sockets[0].getsockname()[1]
        state['url']='wss://localhost:'+str(ws_port)+'/ws/v2?device_id=fixture-device&service_id=1&ticket='+ticket
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_args):pass
            def do_POST(self):
                assert self.path=='/callback/ws/endpoint' and self.headers['Accept-Encoding']=='identity'
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert body=={'AppID':value['app_id'],'AppSecret':value['app_secret']}
                assert 'channel' in self.headers['User-Agent'];seen.append(self.path);mode=state['mode']
                status=302 if mode=='httpredirect' else int(mode) if mode in {'401','429','500'} else 200
                if mode=='duplicate':raw=b'{"code":0,"code":0}'
                elif mode=='infinite':raw=b'{"code":0,"data":1e999}'
                elif mode=='oversize':raw=b'x'*16385
                else:
                    url='ws://localhost:1/unapproved' if mode=='plaintext' else state['url']
                    raw=json.dumps({'code':0,'data':{'URL':url,'ClientConfig':{'ReconnectCount':-1,'ReconnectInterval':120,
                        'ReconnectNonce':30,'PingInterval':120}}}).encode()
                if mode=='withdraw':state['allowed']=False
                self.send_response(status);self.send_header('Content-Length',str(len(raw)))
                if status==302:self.send_header('Location','/must-never-follow')
                self.end_headers();self.wfile.write(raw)
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.socket=server_tls.wrap_socket(http.socket,server_side=True)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        origin='https://localhost:'+str(http.server_port);old=DOMAINS['feishu'];old_suffix=wire.WS_SUFFIXES['feishu'];old_ports=wire.WS_PORTS
        old_websockets=sdk.websockets;old_logger=sdk.logger;DOMAINS['feishu']=origin;wire.WS_SUFFIXES['feishu']=('localhost',);wire.WS_PORTS=frozenset({None,443,ws_port})
        clients=[]
        def current():
            if not state['allowed']:raise PermissionError('fixture owner publication withdrawn')
        def client():
            result=sdk.Client(value['app_id'],value['app_secret'],log_level=LogLevel.DEBUG,domain=origin,extra_ua_tags=['channel'])
            clients.append(result);guard=wire.Discovery(value,current,cache.redactor);guard.install(result);return result,guard
        try:
            with patch.dict(os.environ,{'REQUESTS_CA_BUNDLE':str(root/'ca.pem'),'SSL_CERT_FILE':str(root/'ca.pem')}):
                client_value,guard=client();before=len(seen)
                try:client_value._get_conn_url()
                except wire.Failure as error:assert error.kind=='missing-capability'
                else:raise AssertionError('native WS discovery escaped explicit connection capability')
                assert len(seen)==before
                cases.append('actual_native_discovery_requires_explicit_private_connection_capability_before_network')
                for mode,kind in [('httpredirect','redirect-refused'),('401','authentication-refused'),('429','rate-limited'),
                    ('500','server-refused'),('duplicate','invalid-response'),('infinite','invalid-response'),
                    ('oversize','response-too-large'),('plaintext','unapproved-endpoint')]:
                    state['mode']=mode
                    with guard.connection_scope():
                        try:client_value._get_conn_url()
                        except wire.Failure as error:assert error.kind==kind,(mode,error.kind,kind)
                        else:raise AssertionError('unsafe WS endpoint response admitted')
                    cases.append('native_endpoint_'+mode+'_refused_before_WSS_connection')
                state['mode']='withdraw'
                with guard.connection_scope():
                    try:client_value._get_conn_url()
                    except PermissionError:pass
                    else:raise AssertionError('withdrawn endpoint response released')
                state['allowed']=True;state['mode']='ok'
                cases.append('owner_withdrawal_during_actual_endpoint_HTTP_response_prevents_socket_capability_release')
                bridge=Bridge(asyncio.get_running_loop(),commit,current);frames(client_value,current,bridge)
                with guard.connection_scope():
                    await client_value._connect()
                    await asyncio.wait_for(acknowledged.wait(),10)
                    assert client_value._conn_url==state['url']
                    await client_value._disconnect()
                assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
                key=inbox.db.execute('SELECT id FROM native_inbox').fetchone()[0]
                retained=inbox.claim(key,policy);assert retained is not None
                restored=cache.get(policy,'feishu',value,retained['payload']['raw_id'])
                assert restored['envelope']==retained['envelope'] and restored['envelope']['text']=='Actual native WSS source 1.'
                inbox.complete(key,True)
                cases.append('actual_native_endpoint_SDK_and_verified_WSS_handshake_receive_protobuf_and_ACK_only_after_actual_native_SQLite_capture')
                (root/'untrusted').mkdir();create(root/'untrusted','untrusted.invalid')
                state['mode']='ok';untrusted,untrusted_guard=client();frames(untrusted,current,bridge)
                with patch.dict(os.environ,{'SSL_CERT_FILE':str(root/'untrusted'/'ca.pem')}),untrusted_guard.connection_scope():
                    try:await untrusted._connect()
                    except ssl.SSLError:pass
                    else:raise AssertionError('untrusted WSS issuer accepted')
                assert untrusted._conn is None
                cases.append('actual_WSS_untrusted_issuer_rejected_even_after_successful_verified_endpoint_HTTP')
                state['mode']='wsredirect';other,other_guard=client();frames(other,current,bridge)
                with other_guard.connection_scope():
                    try:await other._connect()
                    except Exception:pass
                    else:raise AssertionError('redirected WSS handshake became connection')
                assert not redirect_hits and other._conn is None
                cases.append('actual_WSS_HTTP_redirect_is_not_followed_and_never_connects_alternate_socket_path')
                assert cache.redactor.text(state['url'])!=state['url'] and cache.redactor.text(ticket)!=ticket
                cases.append('private_endpoint_URL_and_query_capabilities_registered_before_native_connection_diagnostics')
        finally:
            for item in clients:
                try:await item._disconnect()
                except Exception:pass
                if hasattr(item._cache,'_cron'):item._cache._cron.cancel()
            DOMAINS['feishu']=old;wire.WS_SUFFIXES['feishu']=old_suffix;wire.WS_PORTS=old_ports;sdk.websockets=old_websockets;sdk.logger=old_logger
            http.shutdown();http.server_close();thread.join(timeout=5);await runner.cleanup();cache.close();inbox.close()
    diagnostics=io.StringIO()
    with tempfile.TemporaryDirectory(prefix='haos-feishu-ws-http-') as directory:
        with redirect_stdout(diagnostics),redirect_stderr(diagnostics),private_scope(Path(directory),{'HERMES_SAFE_MODE':'1'}):
            asyncio.run(exercise(Path(directory)))
    assert 'private Feishu transport diagnostic' in diagnostics.getvalue()
    assert 'private-feishu-ws-http-fixture' not in diagnostics.getvalue() and 'private-fixture-websocket-ticket' not in diagnostics.getvalue()
    cases.append('actual_native_SDK_debug_connection_diagnostics_do_not_persist_app_secret_endpoint_URL_or_session_ticket')
    report={'passed':len(cases),'cases':cases,'actual_native_SDK_endpoint_HTTP_verified_WSS_protobuf_and_SQLite':True,
        'all_network_targets_loopback_fixtures':True,'owner_grant_and_transport_account_are_fixtures':True,
        'kernel_WS_profile_identity_reconnection_GUI_or_live_acceptance_verified':False,'public_registry_activation_established_by_this_probe':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
