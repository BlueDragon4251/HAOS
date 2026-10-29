#!/usr/bin/env python3
"""Actual pinned Feishu dispatch, journals, relay and controller; no live transport."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import digest
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    from haos.gateway_feishu_cache import RawEvents
    from haos.gateway_feishu_ingress import capture,dispatch_stored,install
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    from haos.store import MissionStore
    from haos.controller import Controller
    from gateway.config import PlatformConfig
    from plugins.platforms.feishu.adapter import FeishuAdapter
    cases=[]
    async def exercise(root):
        value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-ingress-fixture','domain':'feishu',
            'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
        binding={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),
            'thread':'','identity':'personal','capabilities':['create','read','cancel','pause','resume','answer'],'generation':'d'*64,'since':1}
        config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding]};epoch=digest(config)
        policy=lambda:PreparedFeishuPolicy(config)
        def current():
            if digest(config)!=epoch:raise PermissionError('fixture owner publication changed')
        redactor=Redactor([value['app_secret']]);inbox=NativeInbox(root/'native.db',redactor)
        originals=RawEvents(root/'originals.db',redactor,current);relay=RelayInbox(root/'relay.db',redactor)
        store=MissionStore(root/'controller.db');controller=Controller(store,'unused-local-fixture',set());controller.gateway_policy=policy
        home=root/'home';home.mkdir(mode=0o700)
        env={'HERMES_SAFE_MODE':'1','FEISHU_APP_ID':value['app_id'],'FEISHU_APP_SECRET':value['app_secret'],
            'FEISHU_DOMAIN':value['domain'],'FEISHU_BOT_OPEN_ID':value['bot_open_id'],'FEISHU_GROUP_POLICY':'allowlist',
            'FEISHU_ALLOWED_USERS':binding['sender'],'FEISHU_ALLOW_ALL_USERS':'false','GATEWAY_ALLOW_ALL_USERS':'false',
            'FEISHU_ALLOW_BOTS':'none','FEISHU_REQUIRE_MENTION':'false','FEISHU_REACTIONS':'false'}
        with private_scope(home,env):adapter=install(durable_adapter(FeishuAdapter(PlatformConfig(enabled=True))))
        adapter._haos_native=SimpleNamespace(connector='feishu',policy=policy,inbox=inbox)
        adapter._haos_feishu_check=current;adapter._haos_feishu_value=value;adapter._haos_feishu_raw=originals
        adapter._haos_feishu_home=home;adapter._haos_feishu_environment=env
        observed=[]
        def receive(event):
            envelope=adapter_envelope(event,'feishu');assert event.source.user_id_alt is None
            relay.admit(policy(),'feishu',envelope);observed.append(event);return True
        adapter.set_durable_message_handler(receive)
        stamp=str(int(time.time()*1000)-1000)
        def resource(number,text,*,group=False):
            message={'message_id':'om_'+format(number,'032x'),'create_time':stamp,'chat_id':binding['chat'],
                'chat_type':'group' if group else 'p2p','message_type':'text','content':json.dumps({'text':text})}
            if group:message['mentions']=[{'key':'@_user_1','id':{'open_id':value['bot_open_id']},'name':'HAOS'}]
            return json.dumps({'schema':'2.0','header':{'event_id':format(number,'032x'),'event_type':'im.message.receive_v1',
                'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp},
                'event':{'sender':{'sender_id':{'open_id':binding['sender'],'user_id':'unapproved-user-alias'},
                    'sender_type':'user','tenant_key':value['tenant_key']},'message':message}},ensure_ascii=False).encode()
        async def controller_next():
            pending=relay.next(policy());assert pending
            result=await controller.gateway_dispatch({'method':'gateway.receive','params':{'connector':'feishu','envelope':pending['envelope']}})
            relay.admitted(pending['id'],result['mission_id']);return pending,result
        try:
            first=resource(1,'An actual isolated Feishu mission')
            key=capture(adapter,first);assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='pending'
            assert await dispatch_stored(adapter,key)
            pending,result=await controller_next();mid=result['mission_id']
            assert len(store.list())==1 and store.get(mid)['actor']=='gateway:personal'
            assert pending['envelope']['text']=='An actual isolated Feishu mission'
            assert pending['envelope']['scope']==scope(value) and observed[-1].source.user_id==binding['sender']
            cases.append('actual_native_Feishu_decode_durable_relay_and_independent_controller_create_one_correctly_scoped_mission')
            assert observed[-1].source.user_id!='unapproved-user-alias'
            cases.append('actual_native_user_ID_preference_cannot_replace_the_independently_approved_app_open_ID')
            assert capture(adapter,first)==key and not await dispatch_stored(adapter,key)
            assert relay.next(policy()) is None and len(store.list())==1
            assert inbox.db.execute('SELECT COUNT(*) FROM feishu_source_context').fetchone()[0]==1
            cases.append('terminal_native_payload_compaction_preserves_reply_context_and_replay_never_creates_a_second_mission')
            status_key=capture(adapter,resource(2,'@_user_1 /status '+mid,group=True))
            assert await dispatch_stored(adapter,status_key)
            pending,_=await controller_next();assert pending['envelope']['text']=='/status '+mid and len(store.list())==1
            cases.append('actual_group_self_mention_codec_keeps_exact_HAOS_status_command_and_current_sender_chat_authority')
            cancel_key=capture(adapter,resource(3,'/cancel '+mid));assert await dispatch_stored(adapter,cancel_key)
            await controller_next();assert store.get(mid)['state']=='cancelled'
            cases.append('actual_native_command_reaches_independent_controller_cancel_right_without_native_agent_or_plugin_execution')
            wrong=json.loads(resource(4,'Unknown sender must not run'));wrong['event']['sender']['sender_id']['open_id']='ou_'+'0'*32
            before=inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]
            try:capture(adapter,json.dumps(wrong).encode())
            except PermissionError:pass
            else:raise AssertionError('unknown sender captured')
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==before
            cases.append('unknown_sender_never_enters_the_raw_or_native_journal_even_when_native_DM_pairing_would_allow_it')
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
            for call in [lambda:adapter._on_message_event(P2ImMessageReceiveV1(json.loads(first))),lambda:adapter._on_card_action_trigger({})]:
                try:call()
                except PermissionError:pass
                else:raise AssertionError('unretained callback executed')
            try:await adapter._handle_message_event_data(P2ImMessageReceiveV1(json.loads(first)))
            except PermissionError:pass
            else:raise AssertionError('raw native decode bypassed retained claim')
            cases.append('raw_native_callbacks_cards_and_unclaimed_decoder_calls_cannot_bypass_independent_retained_context')
            for operation in [lambda:adapter.send(binding['chat'],'No transport capability'),lambda:adapter.connect()]:
                try:await operation()
                except PermissionError:pass
                else:raise AssertionError('unreviewed transport operation ran')
            cases.append('prepared_adapter_cannot_send_or_connect_before_reviewed_account_bound_transport_is_installed')
            max_pages=relay.db.execute('PRAGMA max_page_count').fetchone()[0]
            pages=relay.db.execute('PRAGMA page_count').fetchone()[0];relay.db.execute('PRAGMA max_page_count='+str(pages))
            retry_key=capture(adapter,resource(5,'Recoverable private relay storage goal. '*700))
            try:await dispatch_stored(adapter,retry_key)
            except sqlite3.DatabaseError:pass
            else:raise AssertionError('full relay storage falsely acknowledged native dispatch')
            row=inbox.db.execute('SELECT state,attempt,next_attempt FROM native_inbox WHERE id=?',(retry_key,)).fetchone()
            assert row['state']=='pending' and row['attempt']==1 and row['next_attempt']>time.time()
            assert originals.get(policy(),'feishu',value,json.loads(inbox.db.execute('SELECT payload FROM native_inbox WHERE id=?',(retry_key,)).fetchone()[0])['raw_id'])['envelope']['text'].startswith('Recoverable')
            relay.db.execute('PRAGMA max_page_count='+str(max_pages))
            await asyncio.sleep(2.2)
            assert await dispatch_stored(adapter,retry_key);await controller_next()
            assert len(store.list())==2 and not await dispatch_stored(adapter,retry_key)
            cases.append('actual_relay_SQLite_full_fault_retains_original_and_native_input_then_bounded_retry_creates_only_one_mission')
        finally:
            await adapter.disconnect();originals.close();inbox.close();relay.close();store.close()
    with tempfile.TemporaryDirectory(prefix='haos-feishu-native-ingress-') as td:asyncio.run(exercise(Path(td)))
    report={'passed':len(cases),'cases':cases,'actual_pinned_native_decode_SQLite_relay_and_controller':True,
        'transport_authentication_owner_publication_and_direct_controller_calls_are_fixtures':True,
        'model_inference_or_external_messages':False,'public_feishu_enabled':False,
        'media_transport_owner_GUI_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
