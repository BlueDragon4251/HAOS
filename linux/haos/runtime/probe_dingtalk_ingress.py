#!/usr/bin/env python3
"""Actual pinned DingTalk handler, HAOS durable MRO and private relay contracts."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
    from gateway.config import PlatformConfig
    from plugins.platforms.dingtalk.adapter import DingTalkAdapter
    from haos.gateway import digest,Conflict
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    from haos.gateway_dingtalk_cache import RawEvents
    from haos.gateway_dingtalk_ingress import install,capture,dispatch_stored
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.redaction import Redactor
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
    cases=[]
    async def exercise(directory):
        live=[True];seen=[];accept=[True];redactor=Redactor([value['client_secret']])
        inbox=NativeInbox(directory/'inbox.db',redactor);relay=RelayInbox(directory/'relay.db',redactor)
        def current():
            if not live[0]:raise PermissionError('fixture publication withdrawn')
        environment={'HERMES_SAFE_MODE':'1','GATEWAY_ALLOW_ALL_USERS':'false'}
        with private_scope(directory,environment):
            adapter=install(durable_adapter(DingTalkAdapter(PlatformConfig(enabled=True,extra={
                'client_id':value['client_id'],'client_secret':value['client_secret'],
                'robot_code':value['robot_code'],'card_template_id':''}))))
        adapter._haos_native=SimpleNamespace(connector='dingtalk',policy=policy,inbox=inbox)
        adapter._haos_dingtalk_check=current;adapter._haos_dingtalk_value=value
        adapter._haos_dingtalk_home=directory;adapter._haos_dingtalk_environment=environment
        raw=RawEvents(directory/'originals.db',redactor,current);adapter._haos_dingtalk_raw=raw
        def receive(event):
            assert event.raw_message is None and event.source.user_id_alt is None
            envelope=adapter_envelope(event,'dingtalk');assert redactor.clean(envelope)==envelope
            seen.append(envelope)
            if isinstance(accept[0],Exception):raise accept[0]
            if accept[0]:relay.admit(policy(),'dingtalk',envelope)
            return accept[0]
        adapter.set_durable_message_handler(receive)
        def retain(data):return capture(adapter,json.dumps(data,ensure_ascii=False).encode())
        key=retain({**body,'senderStaffId':'unapproved-alias','senderNick':'not authority','isAdmin':True})
        assert await dispatch_stored(adapter,key) is True
        assert len(seen)==1 and seen[0]['sender']==grant['sender'] and seen[0]['scope']==scope(value)
        assert seen[0]['text']==body['text']['content'] and seen[0]['is_bot'] is False
        assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='committed'
        assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==1
        assert adapter._session_webhooks=={} and adapter._message_contexts=={}
        cases.append('actual_pinned_DingTalk_on_message_and_durable_MRO_commit_exact_independent_source_to_relay_without_staff_alias_raw_secret_or_volatile_session_authority')
        assert await dispatch_stored(adapter,key) is False and len(seen)==1
        cases.append('committed_native_input_replay_cannot_invoke_handler_or_create_second_relay_obligation')
        retry=retain({**body,'msgId':'retry-native-source'});accept[0]=OSError('fixture durable handler failed')
        try:await dispatch_stored(adapter,retry)
        except OSError:pass
        else:raise AssertionError('handler failure consumed retained source')
        row=inbox.db.execute('SELECT state,attempt FROM native_inbox WHERE id=?',(retry,)).fetchone()
        assert row['state']=='pending' and row['attempt']==1
        # Explicit fixture deadline advance, not a production retry bypass.
        inbox.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(retry,));accept[0]=True
        assert await dispatch_stored(adapter,retry) is True
        assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
        cases.append('real_native_decode_handler_failure_retains_retry_and_native_volatile_dedup_does_not_consume_retry')
        voice={**body,'msgId':'recognized-voice-source','msgtype':'audio','content':{'recognition':'Approved vendor-recognized voice text.'}}
        voice.pop('text');grant['allow_voice']=True
        key=retain(voice);assert await dispatch_stored(adapter,key) is True
        assert seen[-1]['text']==voice['content']['recognition']
        cases.append('actual_native_vendor_recognized_voice_goal_uses_separate_voice_consent_without_claiming_HAOS_ASR')
        ignored=retain({**body,'msgId':'ignored-source'});accept[0]=False
        assert await dispatch_stored(adapter,ignored) is False
        assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(ignored,)).fetchone()[0]=='ignored'
        cases.append('explicit_false_durable_handler_result_is_ignored_never_a_mission_acceptance')
        unconnected={**body,'msgId':'resource-not-connected','msgtype':'picture','content':{'downloadCode':'private-resource-code-fixture'}}
        unconnected.pop('text');grant['allow_media']=True
        key=retain(unconnected);before=len(seen)
        try:await dispatch_stored(adapter,key)
        except PermissionError:pass
        else:raise AssertionError('unsealed SDK resource reached native agent input')
        assert len(seen)==before and inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='pending'
        cases.append('unconnected_private_resource_stays_retained_and_cannot_enter_native_agent_input_as_code_or_URL')
        from dingtalk_stream import ChatbotMessage
        try:await adapter._on_message(ChatbotMessage.from_dict(body))
        except PermissionError:pass
        else:raise AssertionError('direct native handler bypassed retained source')
        try:adapter.build_source(chat_id=grant['chat'],user_id=grant['sender'],message_id=body['msgId'])
        except PermissionError:pass
        else:raise AssertionError('source built outside retained context')
        cases.append('direct_native_callback_and_source_build_cannot_bypass_durable_context')
        for method,args in [('send',(grant['chat'],'unapproved reply')),('_get_access_token',()),
                            ('_send_emotion',('unapproved-message','unapproved-chat','unapproved-emoji'))]:
            try:await getattr(adapter,method)(*args)
            except PermissionError:pass
            else:raise AssertionError('unreviewed native credentialed operation allowed')
        cases.append('unconnected_native_reply_token_and_reaction_methods_have_no_ambient_private_capability')
        live[0]=False
        try:retain(body)
        except PermissionError:pass
        else:raise AssertionError('withdrawn profile captured source')
        assert len(seen)==before
        cases.append('withdrawn_publication_prevents_new_capture_before_native_decode')
        raw.close();inbox.close();relay.close()
    with tempfile.TemporaryDirectory(prefix='haos-dingtalk-ingress-') as td:
        asyncio.run(exercise(Path(td)))
    result={'cases':cases,'scope':'Actual pinned handler/MRO and SQLite relay with fixture current-publication callback; controller unavailable.',
        'actual_controller_mission_live_message_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
