#!/usr/bin/env python3
"""Actual pinned Feishu SDK builders/models/HTTP; not an enabled HAOS transport."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib.metadata import version
import json
from pathlib import Path
import sys
import tempfile
import threading


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_matrix_profile import scope
    from haos.gateway_feishu import DOMAINS
    assert version('lark-oapi')=='1.6.8' and version('requests-toolbelt')=='1.0.0'
    cases=[];requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def reply(self,status,value):
            raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_POST(self):
            assert self.path=='/open-apis/auth/v3/tenant_access_token/internal'
            size=int(self.headers['Content-Length']);assert 1<=size<=4096
            value=json.loads(self.rfile.read(size));requests.append(('auth',value['app_id']))
            assert value['app_secret']=='private-feishu-sdk-fixture'
            if value['app_id'].endswith('denied'):
                return self.reply(401,{'code':99991663,'msg':'fixture authentication refused'})
            self.reply(200,{'code':0,'msg':'ok','tenant_access_token':'fixture-sdk-tenant-token','expire':7200})
        def do_GET(self):
            assert self.headers['Authorization']=='Bearer fixture-sdk-tenant-token'
            requests.append(('GET',self.path))
            if self.path.startswith('/open-apis/im/v1/messages/'):
                return self.reply(429,{'code':99991400,'msg':'fixture rate limit'})
            assert self.path=='/open-apis/bot/v3/info'
            self.reply(200,{'code':0,'msg':'ok','bot':{'activate_status':2,'app_name':'Fixture Bot','open_id':'ou_'+'a'*32}})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='haos-feishu-sdk-') as directory:
            with scope(Path(directory),{'HERMES_SAFE_MODE':'1'}):
                from plugins.platforms.feishu import adapter as native
                assert native._load_lark_oapi() and native.FEISHU_AVAILABLE
                from lark_oapi.core.json import JSON
                from lark_oapi.api.im.v1 import P2ImMessageReceiveV1,CreateMessageRequestBody,ReplyMessageRequestBody
                assert native._sdk_domain('feishu')==DOMAINS['feishu'] and native._sdk_domain('lark')==DOMAINS['lark']
                cases.append('actual_pinned_native_lazy_loader_binds_Lark_1_6_8_models_and_exact_brand_domains')
                text=json.dumps({'text':'Actual native SDK fixture: ä 🤖'},ensure_ascii=False)
                body=native.FeishuAdapter._build_create_message_body(receive_id='oc_'+'b'*32,msg_type='text',content=text,uuid_value='c'*32)
                assert isinstance(body,CreateMessageRequestBody)
                request=native.FeishuAdapter._build_create_message_request('chat_id',body)
                assert request.uri=='/open-apis/im/v1/messages' and request.http_method.name=='POST'
                assert request.queries==[('receive_id_type','chat_id')] and json.loads(JSON.marshal(body))=={
                    'receive_id':'oc_'+'b'*32,'msg_type':'text','content':text,'uuid':'c'*32}
                cases.append('actual_native_create_builder_preserves_exact_chat_UTF8_body_and_explicit_idempotency_uuid')
                reply=native.FeishuAdapter._build_reply_message_body(content=text,msg_type='text',reply_in_thread=True,uuid_value='d'*32)
                assert isinstance(reply,ReplyMessageRequestBody) and json.loads(JSON.marshal(reply))['reply_in_thread'] is True
                request=native.FeishuAdapter._build_reply_message_request('om_'+'e'*32,reply)
                assert request.uri=='/open-apis/im/v1/messages/:message_id/reply' and request.paths['message_id']=='om_'+'e'*32
                cases.append('actual_native_reply_builder_preserves_exact_source_message_thread_flag_and_uuid')
                event={'schema':'2.0','header':{'event_id':'f'*32,'event_type':'im.message.receive_v1',
                    'app_id':'cli_0123456789abcdef','tenant_key':'tenant_fixture'},
                    'event':{'sender':{'sender_id':{'open_id':'ou_'+'a'*32,'user_id':'unapproved-alias'},'sender_type':'user','tenant_key':'tenant_fixture'},
                        'message':{'message_id':'om_'+'b'*32,'create_time':'1234567890000','chat_id':'oc_'+'c'*32,
                            'chat_type':'group','message_type':'text','content':text,'thread_id':'omt_'+'d'*32,'root_id':'om_'+'e'*32}}}
                decoded=P2ImMessageReceiveV1(event)
                assert decoded.header.app_id==event['header']['app_id'] and decoded.header.tenant_key=='tenant_fixture'
                assert decoded.event.sender.sender_id.open_id=='ou_'+'a'*32
                assert decoded.event.sender.sender_id.user_id=='unapproved-alias'
                cases.append('actual_Lark_receive_model_keeps_exact_application_tenant_open_id_and_distinct_user_alias')
                assert type(decoded.event.message.create_time) is str and decoded.event.message.create_time=='1234567890000'
                assert decoded.event.message.thread_id=='omt_'+'d'*32 and decoded.event.message.root_id=='om_'+'e'*32
                cases.append('actual_Lark_receive_model_retains_string_millisecond_time_and_native_topic_separate_from_quoted_root')
                # Only this fixture substitutes the API domain with loopback.
                client=native._build_lark_client('cli_fixture_sdk_01234567','private-feishu-sdk-fixture','http://127.0.0.1:'+str(server.server_port))
                raw=client.request(native._tenant_get_request('/open-apis/bot/v3/info'))
                assert raw.raw.status_code==200 and json.loads(raw.raw.content)['bot']['open_id']=='ou_'+'a'*32
                assert len([row for row in requests if row[0]=='auth'])==1
                cases.append('actual_native_Lark_client_obtains_tenant_token_and_authenticates_exact_bot_information_HTTP_request')
                client.request(native._tenant_get_request('/open-apis/bot/v3/info'))
                assert len([row for row in requests if row[0]=='auth'])==1
                cases.append('actual_Lark_native_token_cache_reuses_token_within_one_fixture_account')
                limited=client.im.v1.message.get(native.FeishuAdapter._build_get_message_request('om_'+'a'*32))
                assert limited.raw.status_code==429 and limited.code==99991400 and limited.success() is False
                cases.append('actual_Lark_HTTP_rate_limit_preserves_status_and_native_failure_code_without_false_success')
                denied=native._build_lark_client('cli_fixture_denied','private-feishu-sdk-fixture','http://127.0.0.1:'+str(server.server_port))
                from lark_oapi.core.exception import ObtainAccessTokenException
                try:denied.request(native._tenant_get_request('/open-apis/bot/v3/info'))
                except ObtainAccessTokenException:pass
                else:raise AssertionError('native authentication failure became success')
                cases.append('actual_Lark_HTTP_authentication_rejection_does_not_reach_bot_lookup')
        report={'passed':len(cases),'cases':cases,'lark_oapi':version('lark-oapi'),'actual_native_Hermes_and_SDK':True,
            'all_HTTP_targets_are_loopback_fixtures':True,'HAOS_transport_delivery_or_GUI_connected':False,
            'public_feishu_enabled':False,'live_account_or_external_messages_or_installed_acceptance':False}
        if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=='__main__':main()
