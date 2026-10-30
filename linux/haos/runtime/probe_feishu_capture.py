#!/usr/bin/env python3
"""Actual codec/SQLite original custody and crash-gap replay; no transport auth."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import digest,Conflict
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    from haos.gateway_feishu_cache import RawEvents,LIMIT
    from haos.gateway_feishu_admission import Refused
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-capture-fixture','domain':'feishu',
        'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
    grant={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':1}
    config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[grant]}
    stamp=str(int(time.time()*1000)-1000)
    event={'schema':'2.0','header':{'event_id':'e'*32,'event_type':'im.message.receive_v1',
        'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp},
        'event':{'sender':{'sender_id':{'open_id':grant['sender']},'sender_type':'user','tenant_key':value['tenant_key']},
            'message':{'message_id':'om_'+'f'*32,'create_time':stamp,'chat_id':grant['chat'],'chat_type':'p2p','message_type':'text',
                'content':json.dumps({'text':'Durable source fixture.'})}}}
    def raw(data):return json.dumps(data,ensure_ascii=False).encode()
    policy=PreparedFeishuPolicy(config);redactor=Redactor([value['app_secret']]);epoch=digest(config)
    live=[True]
    def current():
        if digest(config)!=epoch or not live[0]:raise PermissionError('fixture owner publication changed')
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-feishu-custody-') as td:
        root=Path(td);home=root/'home';home.mkdir(mode=0o700)
        with private_scope(home,{'HERMES_SAFE_MODE':'1'}):
            path=root/'originals.db';cache=RawEvents(path,redactor,current)
            first=cache.capture(policy,'feishu',value,raw(event));assert first['envelope']['text']=='Durable source fixture.'
            assert cache.capture(policy,'feishu',value,raw(event))==first
            assert cache.db.execute('SELECT COUNT(*) FROM feishu_raw_events').fetchone()[0]==1
            cases.append('actual_native_codec_and_private_SQLite_commit_original_before_any_transport_acknowledgement_or_agent_dispatch')
            cache.close();cache=RawEvents(path,redactor,current)
            restored=cache.get(policy,'feishu',value,first['id']);assert restored['raw']==raw(event) and restored['envelope']==first['envelope']
            assert path.stat().st_mode&0o777==0o600
            inbox=NativeInbox(root/'native.db',redactor)
            key=inbox.admit(policy,'feishu',restored['envelope'],{'raw_id':first['id']},received_at=restored['received_at'])
            assert key==first['source_key']
            cases.append('actual_close_reopen_after_original_commit_recovers_the_gap_before_native_input_admission')
            claim=inbox.claim(key,policy);assert claim and claim['payload']=={'raw_id':first['id']}
            inbox.close();inbox=NativeInbox(root/'native.db',redactor)
            claim=inbox.claim(key,policy);assert claim and cache.get(policy,'feishu',value,claim['payload']['raw_id'])['raw']==raw(event)
            inbox.complete(key,True)
            assert inbox.admit(policy,'feishu',restored['envelope'],{'raw_id':first['id']},received_at=restored['received_at'])==key
            assert inbox.claim(key,policy) is None
            row=inbox.db.execute('SELECT envelope,payload FROM native_inbox WHERE id=?',(key,)).fetchone();assert tuple(row)==('{}','{}')
            cases.append('actual_native_processing_crash_reopens_pending_then_terminal_input_compaction_never_readmits_it')
            retry=deepcopy(event);retry['header']['event_id']='a'*32;retry['header']['create_time']=str(int(stamp)+1)
            assert cache.capture(policy,'feishu',value,raw(retry))==first
            assert cache.get(policy,'feishu',value,first['id'])['raw']==raw(event)
            cases.append('transport_redelivery_nonce_changes_preserve_the_first_verified_original_without_duplicate_rows')
            changed=deepcopy(event);changed['event']['message']['content']=json.dumps({'text':'changed immutable body'})
            try:cache.capture(policy,'feishu',value,raw(changed))
            except Conflict:pass
            else:raise AssertionError('same message changed its retained body')
            assert cache.get(policy,'feishu',value,first['id'])['raw']==raw(event)
            cases.append('same_message_cannot_replace_original_body_even_if_delivery_identifiers_are_reused')
            rotated={**value,'app_secret':'rotated-private-fixture'}
            try:cache.get(policy,'feishu',rotated,first['id'])
            except PermissionError:pass
            else:raise AssertionError('old source moved to new credentials')
            cases.append('retained_source_cannot_move_between_private_credential_epochs')
            large=deepcopy(event);large['event']['message']['message_id']='om_'+'1'*32
            large['event']['message']['content']=json.dumps({'text':'🤖'*32000})
            captured=cache.capture(policy,'feishu',value,raw(large));assert len(raw(large))>65536
            large_key=inbox.admit(policy,'feishu',captured['envelope'],{'raw_id':captured['id']},received_at=captured['received_at'])
            claimed=inbox.claim(large_key,policy);assert len(json.dumps(claimed['payload']).encode())<1024
            assert cache.get(policy,'feishu',value,claimed['payload']['raw_id'])['envelope']['text']=='🤖'*32000
            cases.append('maximum_UTF8_goal_survives_an_original_larger_than_the_native_payload_limit_via_an_opaque_durable_reference')
            fault=deepcopy(event);fault['event']['message']['message_id']='om_'+'2'*32
            before=cache.db.execute('SELECT COUNT(*) FROM feishu_raw_events').fetchone()[0]
            def withdraw():live[0]=False;return 0
            cache.db.create_function('fixture_withdraw',0,withdraw)
            cache.db.execute('CREATE TEMP TRIGGER withdraw_after_insert AFTER INSERT ON feishu_raw_events BEGIN SELECT fixture_withdraw(); END')
            try:cache.capture(policy,'feishu',value,raw(fault))
            except PermissionError:pass
            else:raise AssertionError('revocation during transaction committed source')
            live[0]=True;cache.db.execute('DROP TRIGGER withdraw_after_insert')
            assert cache.db.execute('SELECT COUNT(*) FROM feishu_raw_events').fetchone()[0]==before and not cache.db.in_transaction
            cases.append('current_authority_callback_failure_inside_transaction_rolls_back_new_original_without_touching_previous_data')
            unknown=deepcopy(event);unknown['event']['sender']['sender_id']['open_id']='ou_'+'0'*32
            try:cache.capture(policy,'feishu',value,raw(unknown))
            except Refused:pass
            else:raise AssertionError('unknown source retained')
            assert cache.db.execute('SELECT COUNT(*) FROM feishu_raw_events').fetchone()[0]==before
            cases.append('unknown_sender_cannot_fill_the_private_original_cache')
            quota=root/'quota';quota.mkdir(mode=0o700);capacity=RawEvents(quota/'originals.db',redactor,current)
            full=deepcopy(event);full['header']['padding']='x'*900000
            for index in range(128):
                full['event']['message']['message_id']='om_'+format(index,'032x')
                try:capacity.capture(policy,'feishu',value,raw(full))
                except (Conflict,sqlite3.DatabaseError):
                    assert index>0;break
            else:raise AssertionError('bounded original-event storage never refused growth')
            assert not capacity.db.in_transaction
            assert capacity.db.execute('PRAGMA page_count').fetchone()[0]*capacity.db.execute('PRAGMA page_size').fetchone()[0]<=LIMIT
            assert capacity.db.execute('SELECT COUNT(*) FROM feishu_raw_events').fetchone()[0]==index
            capacity.close()
            cases.append('actual_SQlite_physical_quota_refuses_growth_without_open_transaction_or_removing_previous_originals')
            original=cache.db.execute('SELECT data FROM feishu_raw_events WHERE id=?',(first['id'],)).fetchone()[0]
            cache.db.execute('UPDATE feishu_raw_events SET data=? WHERE id=?',(b'damaged',first['id']))
            try:cache.get(policy,'feishu',value,first['id'])
            except Conflict:pass
            else:raise AssertionError('corrupted original was accepted')
            cache.db.execute('UPDATE feishu_raw_events SET data=? WHERE id=?',(original,first['id']))
            cases.append('damaged_original_bytes_are_refused_instead_of_silently_replaced_by_redelivery')
            proof=cache.db.execute('SELECT metadata FROM feishu_raw_events WHERE id=?',(first['id'],)).fetchone()[0]
            damaged=json.loads(proof);damaged['plugin_override']=True
            cache.db.execute('UPDATE feishu_raw_events SET metadata=? WHERE id=?',(json.dumps(damaged),first['id']))
            try:cache.get(policy,'feishu',value,first['id'])
            except Conflict:pass
            else:raise AssertionError('unexpected source proof fields accepted')
            cache.db.execute('UPDATE feishu_raw_events SET metadata=? WHERE id=?',(proof,first['id']))
            cases.append('damaged_or_extended_original_proof_cannot_add_plugin_fields_or_change_native_projection')
            config['bindings'][0]['generation']='0'*64
            try:cache.get(PreparedFeishuPolicy(config),'feishu',value,first['id'])
            except PermissionError:pass
            else:raise AssertionError('withdrawn publication read original')
            cases.append('withdrawn_current_publication_cannot_decode_or_replay_retained_original')
            cache.close();inbox.close()
            from haos.gateway_feishu_source_recovery import sources,purge
            parent=root/'profiles';parent.mkdir(mode=0o700);profile='feishu-'+digest(['feishu',value])
            folder=parent/profile;folder.mkdir(mode=0o700);path.rename(folder/'originals.db')
            inventory=sources(PreparedFeishuPolicy(config),profile,'original',parent=parent)
            selected=next(row for row in inventory['sources'] if row['id']==first['id'])
            assert selected['purge_allowed'] and selected['stored_bytes']==len(raw(event))
            assert raw(event).decode() not in json.dumps(inventory)
            decision={'profile':profile,'kind':'original','id':first['id'],'snapshot_sha256':selected['snapshot_sha256'],
                'owner_uid':1000,'note_sha256':'a'*64,'confirmed':True}
            removed=purge(PreparedFeishuPolicy(config),decision,parent=parent)
            assert removed['removed_payload_bytes']==len(raw(event)) and removed['tombstones_retained']
            assert purge(PreparedFeishuPolicy(config),decision,parent=parent)['removed_payload_bytes']==0
            cases.append('actual_native_captured_original_explicitly_purged_only_after_grant_change_with_audited_idempotent_tombstone')
            config['bindings'][0]['generation']='d'*64
            cache=RawEvents(folder/'originals.db',redactor,current)
            try:cache.capture(PreparedFeishuPolicy(config),'feishu',value,raw(event))
            except PermissionError:pass
            else:raise AssertionError('purged native original automatically restored')
            assert cache.db.execute('SELECT COUNT(*) FROM feishu_raw_events WHERE id=?',(first['id'],)).fetchone()[0]==1
            cache.close()
            cases.append('actual_native_redelivery_after_owner_purge_preserves_tombstone_and_refuses_automatic_byte_restoration')
    report={'passed':len(cases),'cases':cases,'actual_pinned_codec_and_private_SQLite':True,
        'transport_authentication_owner_publication_and_service_identity_are_fixtures':True,
        'network_resources_agent_missions_or_external_messages':False,'public_registry_activation_established_by_this_probe':False,
        'installed_owner_or_hardware_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
