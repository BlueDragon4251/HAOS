#!/usr/bin/env python3
"""Actual authenticated backend artifacts into bounded prepared Feishu output."""
import asyncio
import hashlib
import math
import struct
import wave
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace


async def session(base,token,workspace):
    from PIL import Image
    from websockets.asyncio.client import connect
    from gateway.config import PlatformConfig
    from plugins.platforms.feishu.adapter import FeishuAdapter
    from hermes_state import SessionDB
    from haos.hermes import HermesConnection,websocket_url
    from haos.controller import Controller
    from haos.store import MissionStore
    from haos.gateway_feishu import PreparedFeishuPolicy,scope as account_scope
    from haos.gateway_feishu_output import Output
    from haos.gateway_matrix_profile import scope
    from haos.gateway_raw import NativeInbox
    from haos.gateway import digest
    from haos.redaction import Redactor
    root=workspace/'feishu-private';root.mkdir(mode=0o700)
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-output-fixture','domain':'feishu',
        'tenant_key':'tenant_fixture_01','bot_open_id':'ou_'+'a'*32,'connection_mode':'websocket'}
    sender='ou_'+'b'*32;chat='oc_'+'c'*32
    binding={'id':'owner','connector':'feishu','sender':sender,'chat':chat,'scope':account_scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'allow_outbound_media':True,'generation':'b'*64,'since':1}
    config={'version':1,'connectors':[{'id':'feishu','platform':'feishu'}],'bindings':[binding]};policy=lambda:PreparedFeishuPolicy(config)
    image=BytesIO();Image.new('RGB',(3,2),(10,20,30)).save(image,format='PNG')
    files={'image.png':image.getvalue(),'document.txt':b'A bounded actual exported Feishu document.'}
    audio=BytesIO()
    with wave.open(audio,'wb') as target:
        target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000)
        target.writeframes(b''.join(struct.pack('<h',int(10000*math.sin(i*2*math.pi*440/16000))) for i in range(16000)))
    files['voice.wav']=audio.getvalue()
    for name,data in files.items():(workspace/name).write_bytes(data)
    result_text='Feishu result fixture\n'+'\n'.join('MEDIA:'+str(workspace/name) for name in files)
    async def ignore(*_args):pass
    async with connect(websocket_url(base,token),proxy=None) as channel:
        rpc=HermesConnection(channel,ignore,ignore)
        try:native=await rpc.request('session.create',{'source':'herald_os','cwd':str(workspace),'close_on_disconnect':True})
        finally:await rpc.close()
    db=SessionDB(workspace.parent/'.hermes/state.db')
    try:db.create_session(native['stored_session_id'],source='herald_os',cwd=str(workspace))
    finally:db.close()
    store=MissionStore(root/'controller.db');controller=Controller(store,websocket_url(base,token),set());controller.gateway_policy=policy
    event={'platform':'feishu','sender':sender,'chat':chat,'scope':account_scope(value),'thread':'',
        'message_id':'om_'+'c'*32,'is_bot':False,'text':'Create result files.'}
    admitted=await controller.gateway.receive(policy(),'feishu',event,None);mid=admitted['mission_id']
    store.claim();store.session(mid,native['session_id'],native['stored_session_id']);store.settle(mid,'completed',result=result_text)
    deliveries=[]
    while (delivery:=controller.gateway.next_delivery(policy())) is not None:deliveries.append(delivery)
    delivery=next(item for item in deliveries if 'MEDIA:' in item['content'])
    inbox=NativeInbox(root/'native.db',Redactor([value['app_secret']]))
    home=root/'home';home.mkdir(mode=0o700)
    env={'HERMES_SAFE_MODE':'1','FEISHU_APP_ID':value['app_id'],'FEISHU_APP_SECRET':value['app_secret'],
        'FEISHU_DOMAIN':value['domain'],'FEISHU_BOT_OPEN_ID':value['bot_open_id'],'FEISHU_ALLOW_ALL_USERS':'false',
        'GATEWAY_ALLOW_ALL_USERS':'false','FEISHU_ALLOW_BOTS':'none','FEISHU_REQUIRE_MENTION':'false'}
    with scope(home,env):adapter=FeishuAdapter(PlatformConfig(enabled=True))
    adapter._haos_native=SimpleNamespace(connector='feishu',policy=policy,inbox=inbox)
    route={'binding_id':binding['id'],'binding_digest':digest(binding)}
    def current():policy().current_binding(route)
    adapter._haos_feishu_check=current;
    with scope(home,env):adapter._mark_connected()
    output=Output(adapter);calls=[];cases=[];encodings=[]
    from haos import speech_client
    from haos.audio_opus import encode,result
    actual_opus=speech_client.opus
    async def conversion_transport(data,current):
        current();encodings.append(True)
        encoded=result(encode(data),hashlib.sha256(data).hexdigest());current();return encoded
    speech_client.opus=conversion_transport
    async def call(method,params):
        calls.append((method,dict(params)));return await controller.gateway_dispatch({'method':method,'params':params})
    try:
        prepared=await output.prepare(delivery,call)
        assert [item['data'] for item in prepared['items'][:2]]==list(files.values())[:2]
        assert prepared['items'][2]['data'].startswith(b'OggS') and prepared['items'][2]['file_type']=='opus'
        from haos.speech import decode
        assert decode(prepared['items'][2]['data'])[1]==16000
        assert [item['name'] for item in prepared['items']]==['result-0.png','result-1.txt','result-2.ogg']
        assert [item['kind'] for item in prepared['items']]==['image','file','file']
        assert [item['file_type'] for item in prepared['items']]==['','stream','opus']
        assert 'MEDIA:' not in prepared['text'] and str(workspace) not in prepared['text']
        assert all('path' not in item for item in prepared['items'])
        cases.append('actual_authenticated_backend_exports_only_exact_marked_completed_source_session_files_as_private_bytes')
        (workspace/'document.txt').write_bytes(b'Changed source must not replace a durable snapshot.')
        repeated=await output.prepare(delivery,call);assert repeated==prepared and len(encodings)==1
        cases.append('actual_exported_WAV_uses_native_Opus_codec_and_durable_exact_byte_replay_without_reencoding')
        cases.append('durable_controller_snapshot_does_not_reread_a_changed_agent_file_on_repeated_preparation')
        before=len(calls)
        try:await controller.gateway_dispatch({'method':'gateway.output.begin','params':{
            'delivery':delivery['id'],'attempt':delivery['attempt'],'path':'/owner/private.png'}})
        except PermissionError:pass
        else:raise AssertionError('unmarked owner path was exported')
        cases.append('arbitrary_or_unmarked_host_path_cannot_become_a_Feishu_output_export')
        binding['allow_outbound_media']=False
        try:await output.prepare(delivery,call)
        except PermissionError:pass
        else:raise AssertionError('withdrawn binding prepared old Feishu output')
        assert len(calls)==before
        cases.append('owner_withdrawal_refuses_the_old_delivery_before_any_further_private_read')
        route['binding_digest']=digest(binding)
        stripped=await output.prepare({**delivery,**route},call)
        assert not stripped['items'] and 'separate owner approval' in stripped['text'] and len(calls)==before
        cases.append('fresh_route_without_output_consent_strips_paths_and_performs_no_private_file_reads')
    finally:speech_client.opus=actual_opus;inbox.close();store.close()
    return {'passed':len(cases),'cases':cases,'actual_authenticated_backend_artifact_reader':True,
        'completed_session_and_connected_Feishu_transport_are_fixtures':True,'speech_RPC_transport_is_fixture_actual_codec':True,'public_registry_activation_established_by_this_probe':False,
        'upload_or_reply_worker_external_Feishu_or_inference_acceptance':False}


if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from probe_backend import probe
    report=probe(Path(sys.argv[2]).resolve(strict=True),session_probe=session)
    Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
