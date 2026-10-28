#!/usr/bin/env python3
"""Real pinned server plus HAOS upload/mission/native-byte-attachment contracts."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys


async def session(base,token,workspace):
    from websockets.asyncio.client import connect
    from haos.controller import Controller
    from haos.gateway import GatewayPolicy
    from haos.gateway_media import describe,CHUNK_BYTES,MAX_BYTES
    from haos.hermes import HermesConnection
    from haos.hermes_media import attach
    from haos.store import MissionStore
    store=MissionStore(workspace/'controller.db')
    controller=Controller(store,'unused-private-fixture-origin',set())
    config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,
        'thread':'','identity':'personal','capabilities':['create','read'],'allow_media':True,'allow_video':True,'generation':'b'*64,'since':1}]}
    controller.gateway_policy=lambda:GatewayPolicy(config)
    event={'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'message_id':'c'*64,'is_bot':False,'text':'Inspect the attached image and document.'}
    from io import BytesIO
    from PIL import Image
    buffer=BytesIO();Image.new('RGB',(2,2),(10,20,30)).save(buffer,format='PNG');png=buffer.getvalue()
    prefix=b'actual private mission attachment\n'
    document=prefix+b'd'*(MAX_BYTES-len(prefix))
    import av
    video_buffer=BytesIO()
    with av.open(video_buffer,'w',format='mp4') as target:
        stream=target.add_stream('mpeg4',rate=5);stream.width=16;stream.height=16;stream.pix_fmt='yuv420p'
        frame=av.VideoFrame(16,16,'yuv420p')
        for plane in frame.planes:plane.update(bytes([80])*plane.buffer_size)
        for packet in stream.encode(frame):target.mux(packet)
        for packet in stream.encode(None):target.mux(packet)
    video=video_buffer.getvalue()
    ids=[];methods=[]
    try:
        for data,kind in [(png,'image'),(document,'document'),(video,'video')]:
            meta=describe(data,kind)
            started=await controller.gateway_dispatch({'method':'gateway.media.begin','params':{'connector':'line','envelope':event,'descriptor':meta}})
            for offset in range(0,len(data),CHUNK_BYTES):
                result=await controller.gateway_dispatch({'method':'gateway.media.chunk','params':{
                    'id':started['id'],'offset':offset,'data':base64.b64encode(data[offset:offset+CHUNK_BYTES]).decode()}})
            assert result['ready'];ids.append(started['id'])
        admitted=await controller.gateway_dispatch({'method':'gateway.receive','params':{'connector':'line','envelope':event,'media':ids}})
        assert (await controller.gateway_dispatch({'method':'gateway.receive','params':{'connector':'line','envelope':event,'media':ids}}))==admitted
        items=controller.gateway.media.for_mission(controller.gateway_policy(),admitted['mission_id'])
        assert len(store.list())==1 and len(items)==3
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
                assert methods==['image.attach_bytes','file.attach','file.attach'] and len(refs)==2
                ref=refs[0][len('@file:'):].strip('`"\'')
                path=Path(ref) if Path(ref).is_absolute() else workspace/ref
                assert path.is_relative_to(workspace.parent/'.hermes') and path.read_bytes()==document
                video_ref=refs[1][len('@file:'):].strip('`"\'')
                video_path=Path(video_ref) if Path(video_ref).is_absolute() else workspace/video_ref
                assert video_path.suffix=='.mp4' and video_path.read_bytes()==video
                images=list((workspace.parent/'.hermes/images').glob('upload_*'))
                assert any(path.read_bytes()==png for path in images)
                with Image.open(next(path for path in images if path.read_bytes()==png)) as actual:
                    actual.load();assert actual.size==(2,2) and actual.getpixel((0,0))==(10,20,30)
                assert hashlib.sha256(path.read_bytes()).hexdigest()==describe(document,'document')['sha256']
            finally:await connection.close()
        return {'runtime_session_created':True,'durable_session_created':True,
            'actual_controller_upload_mission_and_pinned_attachment_rpcs':True,'image_and_document_bytes_match':True,'video_bytes_match_with_native_mp4_attachment':True,
            'document_bytes':len(document),'maximum_document_size_exercised':True,
            'host_paths_sent':False,'model_inference_or_installed_acceptance':False,'attachment_rpc_methods':methods}
    finally:store.close()


if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from probe_backend import probe
    result=probe(Path(sys.argv[2]).resolve(strict=True),session_probe=session)
    Path(sys.argv[3]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
