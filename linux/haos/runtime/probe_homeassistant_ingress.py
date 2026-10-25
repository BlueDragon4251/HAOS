#!/usr/bin/env python3
"""Prepared actual pinned HA state decoder plus private SQLite/relay admission."""
import asyncio
import copy
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import GatewayPolicy
    from haos.gateway_homeassistant_ingress import PreparedHomeAssistantPolicy,snapshot,envelope,capture,dispatch_stored,install
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes');os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from gateway.platform_registry import PlatformEntry
        from plugins.platforms.homeassistant import adapter as module
        class Context:
            def register_platform(self,**kwargs): self.entry=PlatformEntry(**kwargs)
        context=Context();module.register(context)
        uid='a'*32;entity='input_text.owner_request'
        config={'version':1,'connectors':[{'id':'ha','platform':'homeassistant'}],'bindings':[{
            'id':'owner','connector':'ha','sender':uid,'chat':entity,'scope':'','thread':'',
            'identity':'ha-owner','capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-10000}]}
        policy=lambda:PreparedHomeAssistantPolicy(config)
        def denied(action):
            try:action()
            except (ValueError,PermissionError):return
            raise AssertionError('unapproved prepared HA authority admitted')
        denied(lambda:GatewayPolicy(config));cases.append('public_owner_policy_still_refuses_unfinished_homeassistant')
        native=NativeInbox(directory/'native.db',Redactor())
        relay=RelayInbox(directory/'relay.db',Redactor())
        adapter=install(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True,token='local-only-fixture-token',extra={
            'url':'https://fixture.invalid','watch_all':True,'cooldown_seconds':30}))))
        adapter._haos_native=SimpleNamespace(connector='ha',policy=policy,inbox=native)
        accepted=[];fail=[False]
        def receive(event):
            source=adapter_envelope(event,'homeassistant')
            with sqlite3.connect(directory/'native.db') as observer:
                assert observer.execute('SELECT state FROM native_inbox WHERE message_id=?',(source['message_id'],)).fetchone()==('processing',)
            if fail[0]:raise ConnectionError('disposable local admission interruption')
            relay.admit(policy(),'ha',source);accepted.append(source)
            return True
        adapter.set_durable_message_handler(receive)
        def event(number=1):
            stamp=datetime.now(timezone.utc).isoformat()
            context={'id':str(number).zfill(32),'user_id':uid,'parent_id':None}
            return {'event_type':'state_changed','time_fired':stamp,'context':context,
                'data':{'entity_id':entity,'user_id':'forged-data-user','old_state':{'state':'old'},
                    'new_state':{'entity_id':entity,'state':'new','last_updated':stamp,'context':dict(context),
                        'attributes':{'friendly_name':'Owner request'}}}}
        original=event();authority=snapshot(policy(),'ha')
        key=capture(adapter,original,authority);assert await dispatch_stored(adapter,key)
        assert accepted[0]['sender']==uid and accepted[0]['chat']==entity and len(accepted[0]['message_id'])==64
        assert accepted[0]['text']=='[Home Assistant] Owner request (input_text.owner_request): changed from \'old\' to \'new\''
        cases.append('actual_native_state_codec_after_observable_commit_uses_original_context_user_entity_and_stable_id')
        assert not await dispatch_stored(adapter,key) and len(accepted)==1
        cases.append('raw_replay_cannot_repeat_native_relay_admission')
        try:await adapter._handle_ha_event(original)
        except PermissionError:pass
        else:raise AssertionError('native callback bypassed retained context')
        cases.append('direct_native_callback_is_denied')
        changes=[]
        def altered(name,modify):
            value=copy.deepcopy(original);modify(value);changes.append((name,value))
        altered('service_context_without_authenticated_user',lambda e:e['context'].update(user_id=None))
        altered('invented_sender_in_payload_cannot_replace_missing_authenticated_context',lambda e:e.pop('context'))
        altered('new_state_context_user_mismatch',lambda e:e['data']['new_state']['context'].update(user_id='b'*32))
        altered('new_state_context_id_mismatch',lambda e:e['data']['new_state']['context'].update(id='b'*32))
        altered('entity_identity_mismatch',lambda e:e['data']['new_state'].update(entity_id='switch.unapproved'))
        altered('naive_original_timestamp',lambda e:e.update(time_fired='2026-10-25T12:00:00'))
        altered('missing_original_update_timestamp',lambda e:e['data']['new_state'].pop('last_updated'))
        altered('unchanged_state_has_no_mission',lambda e:e['data']['new_state'].update(state='old'))
        altered('invalid_state_type',lambda e:e['data']['new_state'].update(state={'forged':'state'}))
        altered('invalid_attributes_type',lambda e:e['data']['new_state'].update(attributes='not-an-object'))
        altered('invalid_old_state_type',lambda e:e['data']['old_state'].update(state=[]))
        altered('unrelated_event_type',lambda e:e.update(event_type='call_service'))
        altered('oversized_native_metadata',lambda e:e['data']['new_state']['attributes'].update(unapproved_blob='x'*65536))
        for name,value in changes:
            assert envelope(adapter,value) is None
            cases.append(name)
        unknown=event(2);unknown['context']['user_id']='b'*32;unknown['data']['new_state']['context']['user_id']='b'*32
        denied(lambda:capture(adapter,unknown,authority));cases.append('unknown_authentic_context_user_is_not_automatically_paired')
        unknown=event(3);unknown['data']['entity_id']='switch.unapproved';unknown['data']['new_state']['entity_id']='switch.unapproved'
        denied(lambda:capture(adapter,unknown,authority));cases.append('native_watch_all_filter_cannot_widen_owner_entity_authority')
        future=event(4);future_stamp=(datetime.now(timezone.utc)+timedelta(seconds=301)).isoformat()
        future['time_fired']=future_stamp;future['data']['new_state']['last_updated']=future_stamp
        denied(lambda:capture(adapter,future,authority));cases.append('future_original_timestamp_has_no_replay_authority')
        old=event(5);old_stamp=(datetime.now(timezone.utc)-timedelta(seconds=20)).isoformat()
        old['time_fired']=old_stamp;old['data']['new_state']['last_updated']=old_stamp
        denied(lambda:capture(adapter,old,authority));cases.append('original_before_owner_grant_is_refused')
        retry=event(6);key=capture(adapter,retry,authority);fail[0]=True
        try:await dispatch_stored(adapter,key)
        except ConnectionError:pass
        else:raise AssertionError('native admission interruption disappeared')
        assert native.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='pending'
        cases.append('native_admission_failure_keeps_raw_obligation_pending')
        native.close();native=NativeInbox(directory/'native.db',Redactor());adapter._haos_native.inbox=native
        fail[0]=False;await asyncio.sleep(2.1)
        assert await dispatch_stored(adapter,key) and len(accepted)==2
        cases.append('actual_sqlite_reopen_retry_is_not_consumed_by_native_cooldown')
        more=event(7);key=capture(adapter,more,authority)
        config['bindings'][0]['generation']='b'*64
        assert not await dispatch_stored(adapter,key) and len(accepted)==2
        denied(lambda:capture(adapter,event(8),authority))
        cases.append('regrant_revokes_retained_and_old_capture_snapshot_authority')
        native.close();relay.close()
    with tempfile.TemporaryDirectory(prefix='haos-ha-native-ingress-') as value:asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_pinned_native_decoder':True,'actual_sqlite_and_relay':True,
        'public_gateway_enabled':False,'transport_authentication_accepted':False,'external_connections':False,
        'homeassistant_device_tools_enabled_for_agent':False,'live_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
