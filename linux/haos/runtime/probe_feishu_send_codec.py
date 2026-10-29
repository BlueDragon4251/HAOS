#!/usr/bin/env python3
"""Actual pinned native reply formatting/builders, without any API transport."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import digest
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    from haos.gateway_feishu_send import specification,wire_target,bind_single_native_send
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.redaction import Redactor
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-feishu-reply-codec-') as directory:
        home=Path(directory)
        with private_scope(home,{'HERMES_SAFE_MODE':'1'}):
            from plugins.platforms.feishu.adapter import FeishuAdapter,_load_lark_oapi
            from gateway.config import PlatformConfig
            from lark_oapi.core.json import JSON
            assert _load_lark_oapi()
            value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-send-codec-fixture','domain':'feishu',
                'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
            binding={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),
                'thread':'','identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':1}
            config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding]};policy=PreparedFeishuPolicy(config)
            stamp=str(int(time.time()*1000)-1000)
            source={'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1',
                'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp},
                'event':{'sender':{'sender_id':{'open_id':binding['sender']},'sender_type':'user','tenant_key':value['tenant_key']},
                    'message':{'message_id':'om_'+'f'*32,'create_time':stamp,'chat_id':binding['chat'],'chat_type':'p2p',
                        'message_type':'text','content':json.dumps({'text':'Approved source goal.'})}}}
            def blueprint(body):
                raw=json.dumps(source).encode()
                return {'binding_id':binding['id'],'binding_digest':digest(binding),'delivery_id':'a'*64,'attempt':1,
                    'source_id':source['event']['message']['message_id'],'source_base64':base64.b64encode(raw).decode(),
                    'source_sha256':hashlib.sha256(raw).hexdigest(),'body':body}
            redactor=Redactor([value['app_secret']]);original=blueprint('Actual native reply ä 🤖.')
            for body in ['Actual native reply ä 🤖.','**Native markdown**\n\n| A | B |\n|---|---|\n| one | two |']:
                item=specification(value,policy,'feishu',blueprint(body),redactor)
                assert item['uuid']==specification(value,policy,'feishu',{**blueprint(body),'attempt':2},redactor)['uuid']
                adapter=FeishuAdapter(PlatformConfig(enabled=True));target=wire_target(adapter,item);bind_single_native_send(adapter,target)
                seen=[]
                def reply(request):
                    seen.append(request);encoded=json.loads(JSON.marshal(request.body))
                    assert request.paths['message_id']==item['source_id']
                    assert encoded=={'content':target['content'],'msg_type':target['msg_type'],'reply_in_thread':False,'uuid':item['uuid']}
                    return SimpleNamespace(success=lambda:True,data=SimpleNamespace(message_id='om_'+'d'*32))
                adapter._client=SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(message=SimpleNamespace(reply=reply))))
                result=asyncio.run(FeishuAdapter.send(adapter,item['chat_id'],item['body'],reply_to=item['source_id'],metadata={'thread_id':''}))
                assert result.success and result.message_id=='om_'+'d'*32 and len(seen)==1
                cases.append('actual_native_'+target['msg_type']+'_send_formatter_and_reply_builder_preserve_original_route_and_stable_UUID')
                try:asyncio.run(adapter._feishu_send_with_retry(chat_id=item['chat_id'],msg_type=target['msg_type'],payload=target['content'],reply_to=None,metadata={'thread_id':''}))
                except PermissionError:pass
                else:raise AssertionError('native retry or top-level fallback admitted')
                assert len(seen)==1
                cases.append('actual_native_'+target['msg_type']+'_send_retry_or_top_level_route_fallback_refused_after_one_intent')
            for field,new in [('body',value['app_secret']),('source_id','om_'+'d'*32),('source_sha256','0'*64),('source_base64','bad'),
                ('body','x'*4001),('body',''),('attempt',True),('binding_digest','f'*64)]:
                try:specification(value,policy,'feishu',{**original,field:new},redactor)
                except (PermissionError,ValueError):pass
                else:raise AssertionError('changed native reply intent admitted: '+field)
            cases.append('changed_source_digest_original_identity_grant_credentials_size_and_attempt_refused')
    report={'passed':len(cases),'cases':cases,'actual_pinned_native_formatter_send_and_SDK_builders':True,
        'API_client_response_is_fixture_no_network':True,'durable_delivery_worker_or_public_send_connected':False,
        'public_feishu_enabled':False,'external_messages_or_live_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
