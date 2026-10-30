#!/usr/bin/env python3
"""Actual backend artifact exports, verified SMS profile, MMS form and TLS fetches."""
import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import time
from urllib.parse import urlsplit


async def session(base,token,workspace):
    import av
    from PIL import Image
    from aiohttp import web,ClientSession,TCPConnector,DummyCookieJar
    from websockets.asyncio.client import connect
    from hermes_state import SessionDB
    from haos.hermes import HermesConnection,websocket_url
    from haos.controller import Controller
    from haos.store import MissionStore
    from haos.gateway_sms import PreparedSMSPolicy,scope
    from haos.gateway_sms_profile import build
    from haos.gateway_raw import NativeInbox
    from haos.gateway import digest
    from haos.gateway_delivery import delivery_result
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    root=workspace/'sms-private';root.mkdir(mode=0o700)
    tls=create(root,'sms.fixture.invalid');os.environ['SSL_CERT_FILE']=str(root/'ca.pem')
    trusted=ssl.create_default_context();assert trusted.check_hostname and trusted.verify_mode==ssl.CERT_REQUIRED
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(root/'certificate.pem',root/'key.pem')
    with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    value={'account_sid':'AC'+'a'*32,'auth_token':'b'*32,'from_number':'+12025550100','port':port,'tls':tls}
    sender='+12025550101';config={'version':1,'connectors':[{'id':'sms','platform':'sms'}],'bindings':[{
        'id':'owner','connector':'sms','sender':sender,'chat':sender,'scope':scope(value),'thread':'','identity':'personal',
        'capabilities':['create','read'],'allow_outbound_media':True,'generation':'c'*64,'since':1}]}
    policy=lambda:PreparedSMSPolicy(config);cases=[];requests=[];fetches=[]
    image=BytesIO();Image.new('RGB',(16,16),(10,20,30)).save(image,format='PNG')
    audio=BytesIO();video=BytesIO()
    with av.open(audio,'w',format='mp4') as output:
        stream=output.add_stream('aac',rate=16000);stream.layout='mono'
        frame=av.AudioFrame(format='s16',layout='mono',samples=16000);frame.sample_rate=16000
        for plane in frame.planes:plane.update(bytes(plane.buffer_size))
        for packet in stream.encode(frame):output.mux(packet)
        for packet in stream.encode(None):output.mux(packet)
    with av.open(video,'w',format='mp4') as output:
        stream=output.add_stream('mpeg4',rate=5);stream.width=16;stream.height=16;stream.pix_fmt='yuv420p'
        frame=av.VideoFrame(16,16,'yuv420p')
        for plane in frame.planes:plane.update(bytes([60])*plane.buffer_size)
        for packet in stream.encode(frame):output.mux(packet)
        for packet in stream.encode(None):output.mux(packet)
    files={'result.png':image.getvalue(),'result.m4a':audio.getvalue(),'result.mp4':video.getvalue(),'result.txt':b'private output document fixture'}
    for name,data in files.items():(workspace/name).write_bytes(data)
    text='Actual output fixture\n'+'\n'.join('MEDIA:'+str(workspace/name) for name in files)
    async def ignore(*_args):pass
    async with connect(websocket_url(base,token),proxy=None) as channel:
        rpc=HermesConnection(channel,ignore,ignore)
        try:native=await rpc.request('session.create',{'source':'herald_os','cwd':str(workspace),'close_on_disconnect':True})
        finally:await rpc.close()
    db=SessionDB(workspace.parent/'.hermes/state.db')
    try:db.create_session(native['stored_session_id'],source='herald_os',cwd=str(workspace))
    finally:db.close()
    store=MissionStore(root/'missions.db');controller=Controller(store,websocket_url(base,token),set());controller.gateway_policy=policy
    event={'platform':'sms','sender':sender,'chat':sender,'scope':scope(value),'thread':'','message_id':'SM'+'d'*32,'is_bot':False,'text':'Create output fixtures'}
    admitted=await controller.gateway.receive(policy(),'sms',event,None);mid=admitted['mission_id']
    store.claim();store.session(mid,native['session_id'],native['stored_session_id']);store.settle(mid,'completed',result=text)
    deliveries=[]
    while True:
        row=controller.gateway.next_delivery(policy())
        if row is None:break
        deliveries.append(row)
    delivery=next(row for row in deliveries if 'MEDIA:' in row['content'])
    assert len([row for row in deliveries if 'MEDIA:' in row['content']])==1
    assert 'Actual output fixture' not in delivery['content']
    inbox=NativeInbox(root/'native.db',Redactor());profiles=root/'profiles';profiles.mkdir(mode=0o700)
    from plugins.platforms.sms.adapter import _basic_auth
    auth=_basic_auth(value['account_sid'],value['auth_token'])
    async def account(request):
        assert request.headers['Authorization']==auth;return web.json_response({'sid':value['account_sid'],'status':'active'})
    async def phones(request):
        assert request.headers['Authorization']==auth
        return web.json_response({'incoming_phone_numbers':[{'account_sid':value['account_sid'],'phone_number':value['from_number'],'capabilities':{'sms':True,'mms':True}}]})
    async def push(request):
        assert request.headers['Authorization']==auth
        data=await request.post();requests.append([(key,data.getall(key)) for key in dict.fromkeys(data.keys())])
        assert data['From']==value['from_number'] and data['To']==sender
        assert inbox.db.execute('SELECT state FROM sms_delivery_intents WHERE delivery_id=?',(delivery['id'],)).fetchone()[0]=='writing'
        urls=data.getall('MediaUrl',[]);assert len(urls)==3
        async with ClientSession(connector=TCPConnector(ssl=trusted),cookie_jar=DummyCookieJar(),trust_env=False) as client:
            for url,expected in zip(urls,[image.getvalue(),audio.getvalue(),video.getvalue()]):
                parsed=urlsplit(url);assert parsed.scheme=='https' and parsed.hostname=='sms.fixture.invalid' and parsed.path.startswith('/sms/output/')
                async with client.get('https://localhost:'+str(port)+parsed.path) as response:
                    assert response.status==200 and await response.read()==expected
                    fetches.append(response.headers['Content-Type'])
        return web.json_response({'sid':'SM'+'f'*32,'account_sid':value['account_sid'],'from':value['from_number'],
            'to':sender,'body':data['Body'],'status':'queued','num_media':str(len(urls))},status=201)
    app=web.Application();app.router.add_get('/accounts/{account}.json',account)
    app.router.add_get('/accounts/{account}/IncomingPhoneNumbers.json',phones);app.router.add_post('/accounts/{account}/Messages.json',push)
    runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=context);await site.start()
    origin='https://localhost:'+str(site._server.sockets[0].getsockname()[1])
    adapter=build(value,parent=profiles,connector='sms',policy=policy,inbox=inbox)
    adapter.set_durable_message_handler(lambda event:(_ for _ in ()).throw(AssertionError('outgoing fixture received input')))
    adapter._haos_sms_rest._fixture_origin=origin+'/accounts/'
    adapter._haos_sms_rest.client=ClientSession(connector=TCPConnector(ssl=trusted),cookie_jar=DummyCookieJar(),trust_env=False);adapter._haos_sms_rest.client._retry_connection=False
    publisher=adapter._haos_sms_publisher;publisher._target=origin+'/accounts/'+value['account_sid']+'/Messages.json'
    publisher.client=ClientSession(connector=TCPConnector(ssl=trusted),cookie_jar=DummyCookieJar(),trust_env=False);publisher.client._retry_connection=False
    async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
    try:
        assert await adapter.connect();cases.append('real_private_account_and_mms_number_verification_before_sender_and_https_output_listener')
        prepared=await adapter._haos_sms_output.prepare(delivery,call)
        assert [item['kind'] for item in prepared['items']]==['image','audio','video','document']
        assert prepared['text']==''
        cases.append('actual_authenticated_backend_exports_four_exact_completed_source_session_artifacts')
        binding=config['bindings'][0];metadata={'haos_scope':binding['scope'],'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},
            'haos_delivery_id':delivery['id'],'haos_delivery_attempt':delivery['attempt'],'haos_output':prepared}
        result=await adapter.send(sender,delivery['content'],metadata=metadata)
        assert delivery_result(result)['status']=='delivered' and len(requests)==1
        assert fetches==['image/png','audio/mp4','video/mp4']
        cases.append('actual_native_sms_form_extended_only_with_three_approved_mms_urls_after_durable_intent')
        cases.append('fixture_provider_fetches_all_native_mms_bytes_from_actual_grant_bound_https_listener')
        duplicate=await adapter.send(sender,delivery['content'],metadata=metadata)
        assert duplicate.message_id==result.message_id and len(requests)==1
        cases.append('confirmed_mms_write_is_not_repeated')
        body,urls=publisher.compile(binding,delivery['id'],prepared)
        assert len(urls)==3 and 'Result file: https://sms.fixture.invalid/sms/output/' in body and 'MEDIA:' not in body
        cases.append('document_uses_real_bounded_download_link_while_supported_audio_video_and_image_use_mms')
        adapter._haos_sms_capabilities['mms']=False
        body,urls=publisher.compile(binding,delivery['id'],prepared)
        assert not urls and body.count('Result file:')==4 and len(body)<=1600
        cases.append('sms_only_number_uses_download_links_without_claiming_mms_support')
        bad={**prepared,'items':[dict(prepared['items'][0],url='https://foreign.invalid/not-approved')]}
        try:publisher.compile(binding,delivery['id'],bad)
        except PermissionError:pass
        else:raise AssertionError('forged MMS URL accepted')
        cases.append('foreign_or_other_delivery_urls_are_refused_before_native_send')
        config['bindings'][0]['allow_outbound_media']=False
        async with ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False) as client:
            for item in prepared['items']:
                async with client.get('https://localhost:'+str(port)+urlsplit(item['url']).path) as response:assert response.status==404
        cases.append('owner_revocation_immediately_blocks_every_media_download')
    finally:await adapter.close_profile();await runner.cleanup();inbox.close();store.close()
    return {'passed':len(cases),'cases':cases,'actual_backend_native_sms_mms_and_verified_tls':True,
        'fixture_completed_mission_and_provider_resources':True,'external_accounts_mms_charges_inference_or_installed_acceptance':False}


if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from probe_backend import probe
    result=probe(Path(sys.argv[2]).resolve(strict=True),session_probe=session)
    Path(sys.argv[3]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
