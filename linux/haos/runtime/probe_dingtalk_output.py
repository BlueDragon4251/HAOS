#!/usr/bin/env python3
"""Actual authenticated backend artifacts into bounded prepared DingTalk output."""
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
    from plugins.platforms.dingtalk.adapter import DingTalkAdapter
    from hermes_state import SessionDB
    from haos.hermes import HermesConnection,websocket_url
    from haos.controller import Controller
    from haos.store import MissionStore
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope as account_scope
    from haos.gateway_dingtalk_output import Output
    from haos.gateway_matrix_profile import scope
    from haos.gateway_raw import NativeInbox
    from haos.gateway import digest
    from haos.redaction import Redactor
    root=workspace/'dingtalk-private';root.mkdir(mode=0o700)
    value={'client_id':'ding_fixture_app','client_secret':'private-dingtalk-output-fixture',
        'corp_id':'ding_fixture_corp','robot_code':'ding_fixture_robot','reply_mode':'robot'}
    sender='$:LWCP_v1:$opaque-owner';chat='cidExactConversation/+='
    binding={'id':'owner','connector':'dingtalk','sender':sender,'chat':chat,'scope':account_scope(value),
        'thread':'','identity':'personal','capabilities':['create','read'],'allow_outbound_media':True,
        'allow_voice':True,'allow_video':True,'generation':'b'*64,'since':1}
    config={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[binding]};policy=lambda:PreparedDingTalkPolicy(config)
    image=BytesIO();Image.new('RGB',(3,2),(10,20,30)).save(image,format='PNG')
    files={'image.png':image.getvalue(),'document.txt':b'A bounded actual exported DingTalk document.'}
    audio=BytesIO()
    with wave.open(audio,'wb') as target:
        target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000)
        target.writeframes(b''.join(struct.pack('<h',int(10000*math.sin(i*2*math.pi*440/16000))) for i in range(16000)))
    files['voice.wav']=audio.getvalue()
    from video_fixture import movie
    files['video.mp4']=movie()
    for name,data in files.items():(workspace/name).write_bytes(data)
    result_text='DingTalk result fixture\n'+'\n'.join('MEDIA:'+str(workspace/name) for name in files)
    async def ignore(*_args):pass
    async with connect(websocket_url(base,token),proxy=None) as channel:
        rpc=HermesConnection(channel,ignore,ignore)
        try:native=await rpc.request('session.create',{'source':'herald_os','cwd':str(workspace),'close_on_disconnect':True})
        finally:await rpc.close()
    db=SessionDB(workspace.parent/'.hermes/state.db')
    try:db.create_session(native['stored_session_id'],source='herald_os',cwd=str(workspace))
    finally:db.close()
    store=MissionStore(root/'controller.db');controller=Controller(store,websocket_url(base,token),set());controller.gateway_policy=policy
    event={'platform':'dingtalk','sender':sender,'chat':chat,'scope':account_scope(value),'thread':'',
        'message_id':'native-controller-source','is_bot':False,'text':'Create result files.'}
    admitted=await controller.gateway.receive(policy(),'dingtalk',event,None);mid=admitted['mission_id']
    store.claim();store.session(mid,native['session_id'],native['stored_session_id']);store.settle(mid,'completed',result=result_text)
    deliveries=[]
    while (delivery:=controller.gateway.next_delivery(policy())) is not None:deliveries.append(delivery)
    delivery=next(item for item in deliveries if 'MEDIA:' in item['content'])
    inbox=NativeInbox(root/'native.db',Redactor([value['client_secret']]))
    home=root/'home';home.mkdir(mode=0o700)
    env={'HERMES_SAFE_MODE':'1'}
    with scope(home,env):adapter=DingTalkAdapter(PlatformConfig(enabled=True,extra={
        'client_id':value['client_id'],'client_secret':value['client_secret'],'robot_code':value['robot_code']}))
    adapter._haos_native=SimpleNamespace(connector='dingtalk',policy=policy,inbox=inbox)
    adapter._haos_dingtalk_value=value;adapter._haos_dingtalk_live=True
    route={'binding_id':binding['id'],'binding_digest':digest(binding)}
    def current():policy().current_binding(route)
    adapter._haos_dingtalk_check=current;adapter.native_health=lambda:{'status':'connected-ws'}
    from haos.gateway_dingtalk_delivery import Publisher
    adapter._haos_dingtalk_publisher=Publisher(adapter)
    with scope(home,env):adapter._mark_connected()
    output=Output(adapter);calls=[];cases=[];encodings=[]
    from haos import speech_client
    from haos.audio_amr import encode,result
    from haos.media_thumbnail import thumbnail,result as preview_result
    actual_amr=speech_client.amr;actual_thumbnail=speech_client.thumbnail;previews=[]
    async def conversion_transport(data,current):
        current();encodings.append(True)
        encoded=result(encode(data),hashlib.sha256(data).hexdigest());current();return encoded
    speech_client.amr=conversion_transport
    async def preview_transport(data,current):
        current();previews.append(True);checked=preview_result(thumbnail(data),hashlib.sha256(data).hexdigest());current();return checked
    speech_client.thumbnail=preview_transport
    async def call(method,params):
        calls.append((method,dict(params)));return await controller.gateway_dispatch({'method':method,'params':params})
    try:
        prepared=await output.prepare(delivery,call)
        assert prepared['items'][0]['data']==files['image.png']
        import zipfile
        with zipfile.ZipFile(BytesIO(prepared['items'][1]['data'])) as archive:
            assert archive.namelist()==['result-1.txt'] and archive.read('result-1.txt')==files['document.txt']
        assert prepared['items'][2]['data'].startswith(b'#!AMR\n')
        from haos.speech import decode
        assert abs(decode(prepared['items'][2]['data'])[1]-16000)<=320
        assert [item['name'] for item in prepared['items']]==['result-0.png','result-1.zip','result-2.amr','result-3.mp4']
        assert [item['kind'] for item in prepared['items']]==['image','file','voice','video']
        assert prepared['items'][3]['data']==files['video.mp4'] and prepared['items'][3]['duration_ms']==1000
        cover=prepared['items'][3]['cover']
        assert cover['source_sha256']==hashlib.sha256(files['video.mp4']).hexdigest() and cover['name']=='cover-3.png'
        assert cover['data'].startswith(b'\x89PNG\r\n\x1a\n')
        assert 'MEDIA:' not in prepared['text'] and str(workspace) not in prepared['text']
        assert all('path' not in item for item in prepared['items'])
        cases.append('actual_authenticated_backend_exports_only_exact_marked_completed_source_session_files_as_private_bytes')
        (workspace/'document.txt').write_bytes(b'Changed source must not replace a durable snapshot.')
        repeated=await output.prepare(delivery,call);assert repeated==prepared and len(encodings)==1 and len(previews)==1
        cases.append('actual_exported_WAV_uses_native_AMR_and_MP4_uses_native_PNG_preview_with_durable_exact_byte_replay_without_reencoding')
        cases.append('durable_controller_snapshot_does_not_reread_a_changed_agent_file_on_repeated_preparation')
        before=len(calls)
        try:await controller.gateway_dispatch({'method':'gateway.output.begin','params':{
            'delivery':delivery['id'],'attempt':delivery['attempt'],'path':'/owner/private.png'}})
        except PermissionError:pass
        else:raise AssertionError('unmarked owner path was exported')
        cases.append('arbitrary_or_unmarked_host_path_cannot_become_a_DingTalk_output_export')
        binding['allow_outbound_media']=False
        try:await output.prepare(delivery,call)
        except PermissionError:pass
        else:raise AssertionError('withdrawn binding prepared old DingTalk output')
        assert len(calls)==before
        cases.append('owner_withdrawal_refuses_the_old_delivery_before_any_further_private_read')
        route['binding_digest']=digest(binding)
        stripped=await output.prepare({**delivery,**route},call)
        assert not stripped['items'] and 'separate owner approval' in stripped['text'] and len(calls)==before
        cases.append('fresh_route_without_output_consent_strips_paths_and_performs_no_private_file_reads')
    finally:speech_client.amr=actual_amr;speech_client.thumbnail=actual_thumbnail;inbox.close();store.close()
    return {'passed':len(cases),'cases':cases,'actual_authenticated_backend_artifact_reader':True,
        'completed_session_and_connected_DingTalk_transport_are_fixtures':True,'speech_RPC_transport_is_fixture_actual_AMR_and_MP4_PNG_codecs':True,'public_registry_activation_established_by_this_probe':False,
        'upload_or_reply_worker_external_DingTalk_or_inference_acceptance':False}


if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from probe_backend import probe
    report=probe(Path(sys.argv[2]).resolve(strict=True),session_probe=session)
    Path(sys.argv[3]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
