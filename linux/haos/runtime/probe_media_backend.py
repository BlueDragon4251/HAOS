#!/usr/bin/env python3
"""Real pinned server plus HAOS upload/mission/native-byte-attachment contracts."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys


async def session(base,token,workspace,*,platform='line'):
    from websockets.asyncio.client import connect
    from haos.controller import Controller
    from haos.gateway import GatewayPolicy
    from haos.gateway_media import describe,CHUNK_BYTES,MAX_BYTES
    from haos.hermes import HermesConnection
    from haos.hermes_media import attach
    from haos.store import MissionStore
    store=MissionStore(workspace/'controller.db')
    controller=Controller(store,'unused-private-fixture-origin',set())
    sender='U'+'a'*32 if platform=='line' else '+12025550101'
    scope='U'+'d'*32 if platform=='line' else 'AC'+'a'*32+':+12025550100'
    config={'version':1,'connectors':[{'id':platform,'platform':platform}],'bindings':[{
        'id':'owner','connector':platform,'sender':sender,'chat':sender,'scope':scope,
        'thread':'','identity':'personal','capabilities':['create','read'],'allow_media':True,'allow_video':True,'generation':'b'*64,'since':1}]}
    controller.gateway_policy=lambda:GatewayPolicy(config)
    event={'platform':platform,'sender':sender,'chat':sender,'scope':scope,'thread':'',
        'message_id':'c'*64 if platform=='line' else 'MM'+'c'*32,'is_bot':False,'text':'Inspect the approved image, document and video files.'}
    from io import BytesIO
    from PIL import Image
    buffer=BytesIO();Image.new('RGB',(2,2),(10,20,30)).save(buffer,format='PNG');png=buffer.getvalue()
    prefix=b'actual private mission attachment\n'
    document=prefix+b'd'*((MAX_BYTES if platform=='line' else 500000)-len(prefix))
    import av
    videos=[]
    for container in (['mp4'] if platform=='line' else ['3gp','3g2']):
        video_buffer=BytesIO()
        with av.open(video_buffer,'w',format=container) as target:
            stream=target.add_stream('mpeg4',rate=5);stream.width=16;stream.height=16;stream.pix_fmt='yuv420p'
            frame=av.VideoFrame(16,16,'yuv420p')
            for plane in frame.planes:plane.update(bytes([80])*plane.buffer_size)
            for packet in stream.encode(frame):target.mux(packet)
            for packet in stream.encode(None):target.mux(packet)
        videos.append((video_buffer.getvalue(),container))
    ids=[];methods=[]
    try:
        for data,kind in [(png,'image'),(document,'document'),*[(data,'video') for data,fmt in videos]]:
            meta=describe(data,kind)
            started=await controller.gateway_dispatch({'method':'gateway.media.begin','params':{'connector':platform,'envelope':event,'descriptor':meta}})
            for offset in range(0,len(data),CHUNK_BYTES):
                result=await controller.gateway_dispatch({'method':'gateway.media.chunk','params':{
                    'id':started['id'],'offset':offset,'data':base64.b64encode(data[offset:offset+CHUNK_BYTES]).decode()}})
            assert result['ready'];ids.append(started['id'])
        admitted=await controller.gateway_dispatch({'method':'gateway.receive','params':{'connector':platform,'envelope':event,'media':ids}})
        assert (await controller.gateway_dispatch({'method':'gateway.receive','params':{'connector':platform,'envelope':event,'media':ids}}))==admitted
        items=controller.gateway.media.for_mission(controller.gateway_policy(),admitted['mission_id'])
        assert len(store.list())==1 and len(items)==2+len(videos)
        async with connect(base.replace('http:','ws:')+'/api/ws?token='+token,proxy=None,max_size=4*1024*1024) as socket:
            async def ignore(*_args):pass
            class Observed(HermesConnection):
                async def request(self,method,params,**kwargs):
                    if method in {'image.attach_bytes','file.attach'}:
                        assert 'path' not in params
                        methods.append(method)
                    return await super().request(method,params,**kwargs)
            connection=Observed(socket,ignore,ignore)
            try:
                native=await connection.request('session.create',{'source':'herald_os','cwd':str(workspace),'title':'Actual media byte fixture','close_on_disconnect':True})
                refs=await attach(connection,native['session_id'],items)
                assert methods==['image.attach_bytes','file.attach']+['file.attach']*len(videos) and len(refs)==1+len(videos)
                ref=refs[0][len('@file:'):].strip('`"\'')
                path=Path(ref) if Path(ref).is_absolute() else workspace/ref
                assert path.is_relative_to(workspace.parent/'.hermes') and path.read_bytes()==document
                for ref,(video,fmt) in zip(refs[1:],videos):
                    video_ref=ref[len('@file:'):].strip('`"\'')
                    video_path=Path(video_ref) if Path(video_ref).is_absolute() else workspace/video_ref
                    assert video_path.suffix=='.'+fmt and video_path.read_bytes()==video
                images=list((workspace.parent/'.hermes/images').glob('upload_*'))
                assert any(path.read_bytes()==png for path in images)
                with Image.open(next(path for path in images if path.read_bytes()==png)) as actual:
                    actual.load();assert actual.size==(2,2) and actual.getpixel((0,0))==(10,20,30)
                assert hashlib.sha256(path.read_bytes()).hexdigest()==describe(document,'document')['sha256']
            finally:await connection.close()
        return {'runtime_session_created':True,'durable_session_persistence_tested':False,
            'actual_controller_upload_mission_and_pinned_attachment_rpcs':True,'image_and_document_bytes_match':True,'video_bytes_match_with_native_attachment':True,'video_formats':[fmt for data,fmt in videos],'gateway_platform':platform,
            'document_bytes':len(document),'maximum_document_size_exercised':platform=='line','maximum_incoming_sms_nonimage_size_exercised':platform=='sms',
            'host_paths_sent':False,'model_inference_or_installed_acceptance':False,'attachment_rpc_methods':methods}
    finally:store.close()


if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from probe_backend import probe
    from functools import partial
    assert len(sys.argv) in {4,5} and (len(sys.argv)==4 or sys.argv[4]=='--sms')
    result=probe(Path(sys.argv[2]).resolve(strict=True),session_probe=partial(session,platform='sms' if len(sys.argv)==5 else 'line'))
    Path(sys.argv[3]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
