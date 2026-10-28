#!/usr/bin/env python3
"""Real pinned backend bytes + native LINE builders + verified loopback HTTPS.

Completed mission/session rows are explicit fixtures; no inference or recipient.
"""
import asyncio
import base64
import copy
from datetime import datetime,timezone,timedelta
from io import BytesIO
import json
from pathlib import Path
import ssl
import sys
import time
from types import SimpleNamespace


async def session(base,token,workspace):
    import av
    from PIL import Image
    from aiohttp import web,ClientSession,TCPConnector
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from gateway.config import PlatformConfig
    from plugins.platforms.line.adapter import LineAdapter
    from hermes_state import SessionDB
    from websockets.asyncio.client import connect
    from haos.hermes import HermesConnection,websocket_url
    from haos.controller import Controller
    from haos.gateway import GatewayPolicy
    from haos.gateway_raw import NativeInbox
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_line_ingress import install
    from haos.gateway_line_delivery import Publisher
    from haos.gateway_line_output import Output
    from haos.gateway_delivery import delivery_result
    from haos.redaction import Redactor
    from haos.store import MissionStore
    from gateway.platforms.base import MEDIA_DELIVERY_EXTS
    from haos.gateway_outbound import EXTENSIONS
    assert set(MEDIA_DELIVERY_EXTS)<=EXTENSIONS
    cases=['pinned_native_output_extension_catalog_is_covered'];user='U'+'a'*32;destination='U'+'d'*32
    config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,'thread':'','identity':'personal',
        'capabilities':['create','read'],'allow_outbound_media':True,'generation':'b'*64,'since':1}]}
    policy=lambda:GatewayPolicy(config)
    image=BytesIO();Image.new('RGB',(16,16),(20,40,80)).save(image,format='PNG')
    audio=BytesIO();video=BytesIO()
    with av.open(audio,'w',format='mp4') as out:
        stream=out.add_stream('aac',rate=16000);stream.layout='mono'
        frame=av.AudioFrame(format='s16',layout='mono',samples=16000);frame.sample_rate=16000
        for plane in frame.planes:plane.update(bytes(plane.buffer_size))
        for packet in stream.encode(frame):out.mux(packet)
        for packet in stream.encode(None):out.mux(packet)
    with av.open(video,'w',format='mp4') as out:
        stream=out.add_stream('mpeg4',rate=5);stream.width=16;stream.height=16;stream.pix_fmt='yuv420p'
        for _ in range(5):
            frame=av.VideoFrame(16,16,'yuv420p')
            for plane in frame.planes:plane.update(bytes([80])*plane.buffer_size)
            for packet in stream.encode(frame):out.mux(packet)
        for packet in stream.encode(None):out.mux(packet)
    files={'result.png':image.getvalue(),'result.m4a':audio.getvalue(),'result.mp4':video.getvalue(),'result.txt':b'actual approved document bytes'}
    for name,data in files.items():(workspace/name).write_bytes(data)
    text='Actual fixture outputs\n'+'\n'.join('MEDIA:'+str(workspace/name) for name in files)
    async def ignore(*_args):pass
    async with connect(websocket_url(base,token),proxy=None) as socket:
        rpc=HermesConnection(socket,ignore,ignore)
        try:native=await rpc.request('session.create',{'source':'herald_os','cwd':str(workspace),'close_on_disconnect':True})
        finally:await rpc.close()
    db=SessionDB(workspace.parent/'.hermes/state.db')
    try:db.create_session(native['stored_session_id'],source='herald_os',cwd=str(workspace))
    finally:db.close()
    store=MissionStore(workspace/'missions.db');controller=Controller(store,websocket_url(base,token),set());controller.gateway_policy=policy
    event={'platform':'line','sender':user,'chat':user,'scope':destination,'thread':'','message_id':'a'*64,'is_bot':False,'text':'Produce the fixture output files'}
    admitted=await controller.gateway.receive(policy(),'line',event,None);mid=admitted['mission_id']
    store.claim();store.session(mid,native['session_id'],native['stored_session_id']);store.settle(mid,'completed',result=text)
    deliveries=[]
    while True:
        delivery=controller.gateway.next_delivery(policy())
        if delivery is None:break
        deliveries.append(delivery)
    delivery=next(d for d in deliveries if 'MEDIA:' in d['content'])
    gateway_home=workspace/'private-gateway';gateway_home.mkdir(mode=0o700)
    inbox=NativeInbox(gateway_home/'native.db',Redactor())
    adapter=install(durable_adapter(LineAdapter(PlatformConfig(enabled=True,extra={
        'channel_secret':'private-output-fixture-secret','channel_access_token':'private-output-fixture-token'}))))
    adapter._haos_native=SimpleNamespace(connector='line',policy=policy,inbox=inbox)
    publisher=Publisher(adapter);output=Output(adapter);adapter._haos_line_output=output;adapter._haos_line_public_url=''
    requests=[];mode=['success']
    async def push(request):
        assert request.headers['Authorization']=='Bearer '+adapter.channel_access_token
        assert inbox.db.execute('SELECT state FROM line_delivery_intents WHERE delivery_id=?',(delivery['id'],)).fetchone()[0]=='writing'
        body=await request.json();requests.append(body)
        if type(mode[0]) is int:return web.Response(status=mode[0],headers={'Retry-After':'7'})
        if mode[0]=='abort':request.transport.close();return web.Response()
        return web.json_response({'sentMessages':[{'id':str(100+i)} for i in range(len(body['messages']))]},headers={
            'X-Line-Request-Id':'d6f3be33-8d24-40a5-a6ab-8116de7744ad'})
    app=web.Application();app.router.add_post('/fixture-push',push);app.router.add_get('/line/output/{token}',output.receive)
    key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False)
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256()))
    pem=workspace/'public.pem';pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    secret=workspace/'private.key';secret.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));secret.chmod(0o600)
    server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_tls.load_cert_chain(pem,secret)
    trusted=ssl.create_default_context(cafile=str(pem));assert trusted.check_hostname and trusted.verify_mode==ssl.CERT_REQUIRED
    runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=server_tls);await site.start()
    origin='https://localhost:'+str(site._server.sockets[0].getsockname()[1]);adapter._haos_line_public_url=origin+'/line/webhook'
    publisher._target=origin+'/fixture-push';publisher.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False);publisher.client._retry_connection=False
    async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
    binding=copy.deepcopy(config['bindings'][0])
    try:
        prepared=await output.prepare(delivery,call)
        assert [i['kind'] for i in prepared['items']]==['image','audio','video','document']
        assert 900<=prepared['items'][1]['duration']<=1200
        cases.append('actual_authenticated_backend_exports_four_explicit_completed_session_artifacts')
        async with ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False) as client:
            for item,expected in zip(prepared['items'],files.values()):
                async with client.get(item['url']) as response:
                    assert response.status==200 and await response.read()==expected and response.headers['Cache-Control']=='no-store, private'
            cases.append('verified_https_capability_downloads_match_all_original_bytes')
            result=await publisher.send(binding,delivery['id'],delivery['attempt'],delivery['content'],prepared=prepared)
            assert delivery_result(result)['status']=='delivered' and len(requests)==1
            messages=requests[0]['messages'];assert [m['type'] for m in messages]==['image','audio','video','text','text']
            assert messages[0]['originalContentUrl']==prepared['items'][0]['url'] and messages[1]['duration']==prepared['items'][1]['duration']
            assert messages[2]['previewImageUrl']==prepared['items'][2]['preview']
            cases.append('actual_native_image_voice_video_and_document_link_builders_one_journaled_push')
            duplicate=await publisher.send(binding,delivery['id'],delivery['attempt'],delivery['content'],prepared=prepared)
            assert duplicate.message_id==result.message_id and len(requests)==1
            cases.append('confirmed_media_attempt_replay_never_repeats_native_http_push')
            async with client.get(prepared['items'][2]['url'],headers={'Range':'bytes=0-15'}) as response:
                assert response.status==206 and await response.read()==video.getvalue()[:16]
            async with client.get(prepared['items'][2]['url'],headers={'Range':'bytes=999999999-'}) as response:
                assert response.status==416
            cases.append('native_media_capability_supports_bounded_byte_ranges_and_refuses_invalid_ranges')
            from haos.gateway_media_relay import MediaCache
            inventory=MediaCache(inbox).owner_inventory(policy())
            assert sum(row['stored_bytes'] for row in inventory['uploads'])==sum(map(len,files.values()))+len(__import__('plugins.platforms.line.adapter',fromlist=['_FALLBACK_PNG_PREVIEW'])._FALLBACK_PNG_PREVIEW)
            assert all(row['state']=='output-cached' and not row['purge_allowed'] for row in inventory['uploads'])
            cases.append('owner_cache_inventory_includes_output_bytes_without_download_tokens_or_paths')
            await controller.gateway_dispatch({'method':'gateway.ack','params':{'id':delivery['id'],'result':{**delivery_result(result),'attempt':delivery['attempt']}}})
            snapshots=controller.gateway.media.inventory()['uploads']
            assert len([r for r in snapshots if r['state']=='output-ready'])==4
            assert all('token' not in r and 'path' not in r for r in snapshots)
            first_export=next(r for r in snapshots if r['state']=='output-ready')
            purged=controller.gateway.media.purge([first_export['id']],'owner:1000','inspected fixture output',confirmed=True)
            assert purged['removed_payload_bytes']>0
            cases.append('explicit_owner_controller_inventory_and_purge_preserve_output_tombstone_and_mission')

            original_delivery=delivery
            from haos.gateway import digest
            for scenario,expected in [(401,'failed'),(429,'retry'),('abort','uncertain')]:
                delivery=dict(original_delivery);delivery['id']=digest([original_delivery['id'],str(scenario)]);delivery['attempt']=1
                store.db.execute("INSERT INTO gateway_outbox(id,route_id,content,state,attempt,lease_until) VALUES(?,?,?,'sending',1,?)",
                    (delivery['id'],delivery['route_id'],delivery['content'],time.time()+120))
                payload=await output.prepare(delivery,call);mode[0]=scenario;before=len(requests)
                refused=await publisher.send(binding,delivery['id'],1,delivery['content'],prepared=payload)
                assert delivery_result(refused)['status']==expected and len(requests)==before+1
                repeated=await publisher.send(binding,delivery['id'],1,delivery['content'],prepared=payload)
                assert delivery_result(repeated)['status']=='uncertain' and len(requests)==before+1
                cases.append('native_media_'+str(scenario)+'_does_not_repeat_the_same_attempt')
                if scenario=='abort':
                    await publisher.close()
                    publisher=Publisher(adapter);publisher._target=origin+'/fixture-push'
                    publisher.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False);publisher.client._retry_connection=False
                    repeated=await publisher.send(binding,delivery['id'],1,delivery['content'],prepared=payload)
                    assert delivery_result(repeated)['status']=='uncertain' and len(requests)==before+1
                    cases.append('new_publisher_preserves_uncertain_media_write_and_does_not_resend')
            delivery=original_delivery;mode[0]='success'
            before_forgery=len(requests)
            corrupt=copy.deepcopy(prepared);corrupt['items'][0]['url']='https://foreign.invalid/not-approved'
            try:await publisher.send(binding,'e'*64,1,delivery['content'],prepared=corrupt)
            except PermissionError:pass
            else:raise AssertionError('arbitrary media URL accepted')
            assert len(requests)==before_forgery;cases.append('forged_or_foreign_media_url_refused_before_request')
            config['bindings'][0]['allow_outbound_media']=False
            for item in prepared['items']:
                async with client.get(item['url']) as response:assert response.status==404
            cases.append('owner_revocation_immediately_blocks_all_existing_download_capabilities')
            try:await output.prepare(delivery,call)
            except PermissionError:pass
            else:raise AssertionError('withdrawn output authority reused')
            cases.append('revoked_output_cannot_be_exported_or_republished')
            inventory=MediaCache(inbox).owner_inventory(policy())
            selected=inventory['uploads'][0]
            assert selected['purge_allowed']
            cache_purge=MediaCache(inbox).owner_purge(policy(),{'id':selected['id'],'owner_uid':1000,'note_sha256':'f'*64,'confirmed':True})
            assert cache_purge['removed_payload_bytes']==selected['stored_bytes']
            cases.append('owner_gateway_cache_purge_requires_withdrawal_and_keeps_private_audit')
            config['bindings'][0]['allow_outbound_media']=True
            inbox.db.execute('UPDATE line_output_media SET expires=0')
            async with client.get(prepared['items'][0]['url']) as response:assert response.status==404
            cases.append('expired_download_capability_refused')
            config['bindings'][0]['allow_outbound_media']=False
            # A newly published read-only route can still receive safe text;
            # it cannot inherit output permissions or disclose agent paths.
            read_only=dict(delivery);read_only['binding_digest']=__import__('haos.gateway',fromlist=['digest']).digest(config['bindings'][0])
            safe=await output.prepare(read_only,lambda *_:(_ for _ in ()).throw(AssertionError('unapproved export requested')))
            assert safe['items']==[] and 'MEDIA:' not in safe['text'] and str(workspace) not in safe['text']
            cases.append('read_without_output_opt_in_delivers_safe_text_without_file_paths_or_exports')
        assert store.get(mid)['result']==text
    finally:await publisher.close();await runner.cleanup();inbox.close();store.close()
    return {'passed':len(cases),'cases':cases,'actual_native_backend_line_builders_and_verified_https':True,
        'completed_mission_and_session_are_explicit_fixtures':True,'external_delivery_inference_or_installed_acceptance':False}


if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from probe_backend import probe
    result=probe(Path(sys.argv[2]).resolve(strict=True),session_probe=session)
    Path(sys.argv[3]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
