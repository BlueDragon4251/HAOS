#!/usr/bin/env python3
"""Actual SDK WS protobuf/assembly/ACK and owning-thread SQLite capture; no socket auth."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_feishu import scope,PreparedFeishuPolicy
    from haos.gateway_feishu_cache import RawEvents
    from haos.gateway_feishu_ingress import capture,install as install_ingress
    from haos.gateway_feishu_ws_frames import Bridge,install
    from haos.gateway_feishu_admission import Refused,MAX_EVENT
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.redaction import Redactor
    cases=[]
    async def exercise(root):
        from plugins.platforms.feishu import adapter as native
        from gateway.config import PlatformConfig
        assert native._load_lark_oapi()
        from lark_oapi.ws.client import Client,Frame,FrameType,MessageType
        from lark_oapi.ws.model import ClientConfig
        from lark_oapi.core.enum import LogLevel
        value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-ws-frame-fixture','domain':'feishu',
            'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
        binding={'id':'owner','connector':'feishu','sender':'ou_'+'b'*32,'chat':'oc_'+'c'*32,'scope':scope(value),
            'thread':'','identity':'personal','capabilities':['create','read'],'generation':'d'*64,'since':1}
        policy=lambda:PreparedFeishuPolicy({'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding]})
        live=[True]
        def current():
            if not live[0]:raise PermissionError('fixture publication withdrawn')
        inbox=NativeInbox(root/'native.db',Redactor([value['app_secret']]));originals=RawEvents(root/'raw.db',inbox.redactor,current)
        home=root/'home';home.mkdir(mode=0o700)
        with private_scope(home,{'HERMES_SAFE_MODE':'1'}):adapter=install_ingress(durable_adapter(native.FeishuAdapter(PlatformConfig(enabled=True))))
        adapter._haos_native=SimpleNamespace(connector='feishu',policy=policy,inbox=inbox);adapter._haos_feishu_value=value
        adapter._haos_feishu_check=current;adapter._haos_feishu_raw=originals
        owner_thread=threading.get_ident();observed=[];acks=[]
        def commit(raw):
            assert threading.get_ident()==owner_thread
            result=capture(adapter,raw);observed.append(result);return result
        bridge=Bridge(asyncio.get_running_loop(),commit,current)
        class Connection:
            async def send(self,raw):
                frame=Frame();frame.ParseFromString(raw);body=json.loads(frame.payload)
                if body['code']==200:
                    async def verify_commit():
                        assert threading.get_ident()==owner_thread
                        assert observed and inbox.db.execute('SELECT 1 FROM native_inbox WHERE id=?',(observed[-1],)).fetchone()
                    if threading.get_ident()==owner_thread:await verify_commit()
                    else:await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(verify_commit(),bridge.loop))
                acks.append(body['code'])
            async def close(self):pass
        clients=[]
        def client(on_exit=None):
            result=Client(value['app_id'],value['app_secret'],log_level=LogLevel.ERROR,event_handler=None)
            install(result,current,bridge,on_exit=on_exit);result._conn=Connection();clients.append(result);return result
        def payload(number):
            stamp=str(int(time.time()*1000)-1000)
            return json.dumps({'schema':'2.0','header':{'event_id':format(number,'032x'),'event_type':'im.message.receive_v1',
                'app_id':value['app_id'],'tenant_key':value['tenant_key'],'create_time':stamp},
                'event':{'sender':{'sender_id':{'open_id':binding['sender']},'sender_type':'user','tenant_key':value['tenant_key']},
                    'message':{'message_id':'om_'+format(number,'032x'),'create_time':stamp,'chat_id':binding['chat'],
                        'chat_type':'p2p','message_type':'text','content':json.dumps({'text':'Actual native WS source.'})}}}).encode()
        def frame(data,identity='fixture_message',total='1',sequence='0',**extra):
            result=Frame();result.SeqID=0;result.LogID=0;result.method=FrameType.DATA.value;result.service=1;result.payload=data
            for key,item in {'message_id':identity,'trace_id':'fixture_trace','sum':total,'seq':sequence,'type':MessageType.EVENT.value,**extra}.items():
                header=result.headers.add();header.key=key;header.value=item
            return result.SerializeToString()
        async def refused(target,raw,reason=None):
            before=len(acks)
            try:await target._handle_message(raw)
            except Refused as error:
                if reason:assert error.reason==reason,(error.reason,reason)
            else:raise AssertionError('unsafe native WS frame admitted')
            assert len(acks)==before
        try:
            target=client();raw=payload(1);await target._handle_message(frame(raw));assert acks==[200]
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
            cases.append('actual_SDK_protobuf_event_handler_ACK_is_encoded_only_after_native_original_and_input_SQLite_commit')
            await target._handle_message(frame(raw));assert acks==[200,200] and inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
            cases.append('actual_SDK_replayed_frame_preserves_one_durable_native_input')
            raw=payload(2);cut=len(raw)//2;before=len(acks)
            await target._handle_message(frame(raw[cut:],'fragmented','2','1'));assert len(acks)==before
            await target._handle_message(frame(raw[:cut],'fragmented','2','0'))
            assert acks[-1]==200 and not target._cache.records and not target._cache.proofs
            cases.append('actual_native_SDK_assembles_out_of_order_fragments_and_ACKs_only_complete_committed_event')
            for total,sequence in [('99999999','0'),('17','0'),('2','2'),('2','-1'),('01','0')]:
                await refused(target,frame(b'x',total=total,sequence=sequence),'unsupported-fragments')
            cases.append('oversized_total_negative_or_out_of_range_sequence_and_alias_numbers_refused_before_SDK_allocation')
            duplicate=Frame();duplicate.ParseFromString(frame(payload(3)));header=duplicate.headers.add();header.key='sum';header.value='1'
            await refused(target,duplicate.SerializeToString(),'unsupported-frame')
            missing=Frame();missing.ParseFromString(frame(payload(3)));missing.ClearField('SeqID')
            await refused(target,missing.SerializePartialToString(),'unsupported-frame')
            await refused(target,frame(b'x',type=MessageType.CARD.value),'unsupported-frame')
            await refused(target,frame(b'x'*(MAX_EVENT+1)),'unsupported-frame')
            cases.append('duplicate_proto_headers_missing_required_fields_cards_and_oversized_payload_never_reach_event_callback_or_ACK')
            await target._handle_message(frame(b'first','collision','2','0'))
            await refused(target,frame(b'other','collision','2','0'),'fragment-conflict')
            await refused(target,frame(b'next','collision','3','1'),'fragment-conflict')
            cases.append('changed_duplicate_fragment_or_fragment_count_cannot_replace_existing_assembly')
            large=client();await large._handle_message(frame(b'x'*600000,'large','2','0'))
            await refused(large,frame(b'y'*600000,'large','2','1'),'unsupported-fragments')
            assert sum(map(len,large._cache.proofs['large']['parts'].values()))==600000
            cases.append('aggregate_fragment_size_refused_before_mutating_retained_partial_buffer')
            limited=client()
            for number in range(32):await limited._handle_message(frame(b'x','pending_'+str(number),'2','0'))
            await refused(limited,frame(b'x','one_too_many','2','0'),'fragment-capacity')
            assert len(limited._cache.proofs)==32
            cases.append('bounded_partial_message_count_preserves_existing_32_incomplete_assemblies')
            await asyncio.sleep(5.1);limited._cache.sweep();assert not limited._cache.proofs and not limited._cache.records
            cases.append('real_fragment_TTL_expiry_releases_only_volatile_unacknowledged_assemblies')
            target._configure(ClientConfig({'PingInterval':10}));assert target._ping_interval==10 and target._reconnect_interval==120 and target._auto_reconnect is False
            try:target._configure(ClientConfig({'PingInterval':0}))
            except Refused:pass
            else:raise AssertionError('zero-delay SDK ping loop admitted')
            cases.append('partial_real_SDK_configuration_preserves_safe_defaults_and_refuses_busy_loop_interval')
            originals.db.execute("CREATE TEMP TRIGGER fixture_stop BEFORE INSERT ON feishu_raw_events BEGIN SELECT RAISE(ABORT,'fixture storage unavailable'); END")
            before=inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]
            await target._handle_message(frame(payload(4)));assert acks[-1]==500
            assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==before
            originals.db.execute('DROP TRIGGER fixture_stop')
            cases.append('actual_SQLite_capture_failure_returns_native_SDK_500_not_success_ACK')
            threaded=client();await asyncio.to_thread(lambda:asyncio.run(threaded._handle_message(frame(payload(5)))))
            assert acks[-1]==200 and inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==before+1
            cases.append('actual_SDK_thread_blocks_for_owning_loop_SQLite_capture_without_cross_thread_database_use')
            exits=[];inline=client(on_exit=exits.append);start=len(acks)
            class Stream(Connection):
                def __init__(self):self.calls=0
                async def recv(self):
                    if self.calls==2:raise ConnectionError('fixture stream closed')
                    assert len(acks)==start+self.calls
                    self.calls+=1;return frame(payload(10+self.calls),'sequential_'+str(self.calls))
            inline._conn=Stream();await inline._receive_message_loop()
            assert len(acks)==start+2 and exits==['transport-unavailable'] and inline._conn is None
            cases.append('actual_SDK_receive_loop_applies_inline_commit_backpressure_and_disconnects_on_stream_failure_without_task_fanout')
            live[0]=False
            try:await target._handle_message(frame(payload(20)))
            except PermissionError:pass
            else:raise AssertionError('withdrawn publication processed SDK frame')
            cases.append('current_owner_withdrawal_prevents_native_frame_processing')
        finally:originals.close();inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-feishu-ws-frames-') as directory:asyncio.run(exercise(Path(directory)))
    report={'passed':len(cases),'cases':cases,'actual_SDK_protobuf_assembly_ACK_native_codec_and_SQLite':True,
        'actual_thread_to_owner_loop_handoff':True,'socket_send_and_transport_authentication_are_fixtures':True,
        'connected_WS_TLS_endpoint_kernel_identity_or_live_account_verified':False,'public_registry_activation_established_by_this_probe':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
