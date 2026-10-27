#!/usr/bin/env python3
"""Actual signed LINE SDK/HTTPS content, durable relay and controller media path."""
import asyncio
import base64
import copy
from datetime import datetime,timezone,timedelta
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import GatewayPolicy
    from haos.gateway_runtime import build_adapter,adapter_envelope
    from haos.gateway_media_relay import event_media,forward
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_raw_recovery import retry_line_auth
    from haos.controller import Controller
    from haos.store import MissionStore
    from haos.redaction import Redactor
    cases=[]
    async def exercise(root):
        from aiohttp import web,ClientSession,TCPConnector,ClientConnectorCertificateError
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        from PIL import Image
        os.environ['HERMES_HOME']=str(root/'unused-home');os.environ['HERMES_SAFE_MODE']='1'
        user='U'+'a'*32;destination='U'+'d'*32
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,'thread':'',
            'identity':'personal','capabilities':['create','read'],'allow_media':True,'generation':'b'*64,'since':int((time.time()-30)*1000)}]}
        policy=lambda:GatewayPolicy(config)
        with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        value={'channel_secret':'c'*32,'channel_access_token':'private-line-media-access','destination':destination,'port':port}
        inbox=NativeInbox(root/'native.db',Redactor());relay=RelayInbox(root/'relay.db',Redactor())
        store=MissionStore(root/'controller.db');controller=Controller(store,'unused',set());controller.gateway_policy=policy
        profiles=root/'profiles';profiles.mkdir(mode=0o700)
        buffer=BytesIO();Image.new('RGB',(3,2),(10,20,30)).save(buffer,format='PNG');png=buffer.getvalue()
        document=b'actual LINE document\n'+b'd'*60000
        owner=root/'owner-secret';owner.write_bytes(b'preserve-owner-canary')
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]);now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False)
            .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256()))
        certificate=root/'api.pem';certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        private=root/'api.key';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_tls.load_cert_chain(certificate,private)
        trusted=ssl.create_default_context(cafile=str(certificate));assert trusted.check_hostname and trusted.verify_mode==ssl.CERT_REQUIRED
        mode=['ok'];downloads=[];lookups=[];accepted=[];events=[]
        async def info(request):lookups.append(True);return web.json_response({'userId':destination})
        async def content(request):
            assert request.headers['Authorization']=='Bearer '+value['channel_access_token']
            downloads.append(request.match_info['id'])
            if isinstance(mode[0],int):return web.Response(status=mode[0],headers={'Retry-After':'21'})
            if mode[0]=='redirect':return web.Response(status=307,headers={'Location':'/foreign'})
            if mode[0]=='secret':return web.Response(body=value['channel_access_token'].encode())
            if mode[0]=='oversize':return web.Response(body=b'x'*(2*1024*1024+1))
            if mode[0]=='encoded':return web.Response(body=b'not-gzip',headers={'Content-Encoding':'gzip'})
            data=png if request.match_info['id'].startswith('1') else document
            if mode[0]=='abort':
                response=web.StreamResponse(headers={'Content-Length':str(len(data))});await response.prepare(request)
                await response.write(data[:5]);request.transport.close();return response
            return web.Response(body=data)
        app=web.Application();app.router.add_get('/info',info);app.router.add_get('/content/{id}',content)
        async def foreign(_request):raise AssertionError('credentialed redirect followed')
        app.router.add_get('/foreign',foreign)
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=server_tls);await site.start()
        base='https://localhost:'+str(site._server.sockets[0].getsockname()[1])
        def receive(event):
            env=adapter_envelope(event,'line');ids=event_media(event,'line')
            with_unchanged_copy=copy.copy(event)
            try:event_media(with_unchanged_copy,'line')
            except PermissionError:pass
            else:raise AssertionError('copied native event inherited admission authority')
            relay.admit(policy(),'line',env,media=ids);accepted.append((env,ids));events.append(event);return True
        def create():
            result=build_adapter('line',value,line_context={'parent':profiles,'connector':'line','policy':policy,'inbox':inbox})
            result._haos_line_identity._target=base+'/info'
            result._haos_line_identity.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False)
            result._haos_line_identity.client._retry_connection=False
            result._haos_line_content._target=base+'/content/{message_id}'
            result._haos_line_content.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False)
            result._haos_line_content.client._retry_connection=False
            result.set_durable_message_handler(receive);return result
        async def until(predicate):
            async with asyncio.timeout(8):
                while not predicate():await asyncio.sleep(.02)
        counter=[0]
        async def post(kind='image',sender=user,**changes):
            counter[0]+=1
            event={'type':'message','mode':'active','timestamp':int(time.time()*1000),
                'webhookEventId':'01K8'+'A'*18+f'{counter[0]:04d}',
                'source':{'type':'user','userId':sender},'message':{'type':kind,'id':('1' if kind=='image' else '2')+str(counter[0])},
                'replyToken':'private-unused-reply-capability'}
            if kind=='image':event['message']['contentProvider']={'type':'line'}
            else:event['message'].update(fileName='../../owner-secret',fileSize=len(document))
            event['message'].update(changes)
            body=json.dumps({'destination':destination,'events':[event]}).encode()
            signature=base64.b64encode(hmac.new(value['channel_secret'].encode(),body,hashlib.sha256).digest()).decode()
            async with ClientSession() as client:
                async with client.post(f'http://127.0.0.1:{port}/line/webhook',data=body,headers={'X-Line-Signature':signature}) as response:assert response.status==200
            return event
        adapter=create()
        try:
            assert await adapter.connect()
            from haos.gateway_line_content import Refused
            content_client=adapter._haos_line_content
            for rejected,status in [('redirect',307),('oversize',413),('encoded',415),('secret',None)]:
                mode[0]=rejected
                try:await content_client.fetch('123456','image',lambda:None)
                except (Refused,PermissionError) as error:
                    if status is None:assert isinstance(error,PermissionError)
                    else:assert isinstance(error,Refused) and error.status==status
                else:raise AssertionError('unsafe native content response admitted: '+rejected)
                assert content_client.active is None
                cases.append('actual_content_'+rejected+'_refused_without_native_attachment_or_mission')
            mode[0]='ok'
            before=len(downloads)
            for label,context,target in [('untrusted_ca',ssl.create_default_context(),base),
                    ('wrong_hostname',trusted,base.replace('localhost','127.0.0.1'))]:
                await content_client.close()
                content_client.client=ClientSession(connector=TCPConnector(ssl=context),trust_env=False)
                content_client.client._retry_connection=False
                content_client._target=target+'/content/{message_id}'
                try:await content_client.fetch('123456','image',lambda:None)
                except __import__('aiohttp').ClientConnectorCertificateError:pass
                else:raise AssertionError('unverified content TLS admitted: '+label)
                assert len(downloads)==before and content_client.active is None
                cases.append('actual_content_tls_'+label+'_rejected_before_credentialed_http')
            await content_client.close()
            content_client.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False)
            content_client.client._retry_connection=False;content_client._target=base+'/content/{message_id}'
            await adapter.close_profile();config['bindings'][0]['allow_media']=False
            adapter=create();assert await adapter.connect()
            await post();await asyncio.sleep(.25)
            assert len(downloads)==before and accepted==[]
            await adapter.close_profile();config['bindings'][0]['allow_media']=True
            adapter=create();assert await adapter.connect()
            cases.append('actual_signed_media_without_explicit_owner_opt_in_never_downloads')
            before=len(downloads);await post(sender='U'+'e'*32);await asyncio.sleep(.25)
            assert len(downloads)==before and accepted==[]
            cases.append('actual_signed_unknown_sender_never_downloads_or_creates_a_media_record')
            first=await post();await until(lambda:len(accepted)==1)
            assert adapter._haos_media_cache.get(policy(),accepted[0][1][0])['data']==png
            try:event_media(events[0],'line')
            except PermissionError:pass
            else:raise AssertionError('native media authority escaped the retained callback')
            cases.append('actual_pinned_image_codec_https_content_and_context_bound_private_relay_preserve_bytes')
            cases.append('copied_or_later_replayed_event_objects_cannot_inherit_media_admission_context')
            queued=relay.next(policy());cache=adapter._haos_media_cache;calls=[];lose=[True]
            async def bridge(method,params):
                result=await controller.gateway_dispatch({'method':method,'params':params});calls.append(method)
                if method=='gateway.media.chunk' and lose[0]:lose[0]=False;raise ConnectionError('fixture lost committed chunk response')
                return result
            try:await forward(policy,'line',queued['envelope'],queued['media'],cache,bridge)
            except ConnectionError:pass
            else:raise AssertionError('lost chunk receipt not observed')
            assert len(store.list())==0 and cache.get(policy(),queued['media'][0])['data']==png
            response=await forward(policy,'line',queued['envelope'],queued['media'],cache,bridge)
            assert calls.count('gateway.media.chunk')==1 and len(store.list())==1
            assert controller.gateway.media.for_mission(policy(),response['mission_id'])[0]['data']==png
            relay.admitted(queued['id'],response['mission_id']);cache.transferred(queued['media'])
            assert inbox.db.execute('SELECT data,state FROM native_media_cache').fetchone()[:]==(None,'transferred')
            cases.append('lost_durable_chunk_receipt_resumes_without_resending_bytes_or_creating_a_duplicate_mission')
            cases.append('only_controller_admission_ack_compacts_the_transient_copy_and_preserves_authoritative_bytes')
            await post('file');await until(lambda:len(accepted)==2)
            queued=relay.next(policy());response=await forward(policy,'line',queued['envelope'],queued['media'],cache,bridge)
            assert controller.gateway.media.for_mission(policy(),response['mission_id'])[0]['data']==document
            assert owner.read_bytes()==b'preserve-owner-canary' and 'owner-secret' not in store.get(response['mission_id'])['goal']
            relay.admitted(queued['id'],response['mission_id']);cache.transferred(queued['media'])
            cases.append('actual_native_file_codec_ignores_pathlike_remote_filename_and_transfers_only_authorized_api_bytes')
            before=len(downloads);await post(contentProvider={'type':'external','originalContentUrl':'http://127.0.0.1/private'})
            await asyncio.sleep(.25);assert len(downloads)==before
            cases.append('external_content_provider_urls_are_refused_before_credentialed_download')
            await adapter.close_profile()
            for error in [401,403,429]:
                value['channel_access_token']='private-line-media-'+str(error);config['bindings'][0]['generation']=str(error%10)*64
                adapter=create();mode[0]='ok';assert await adapter.connect();mode[0]=error
                await post('file');await until(lambda:adapter.native_health()['status']==('rate-limited' if error==429 else 'authentication-refused'))
                assert not adapter.is_connected
                deadline=adapter.native_health()['next_attempt'];await adapter.close_profile();before=len(lookups)
                adapter=create();mode[0]='ok';assert not await adapter.connect() and len(lookups)==before
                decision=retry_line_auth(inbox,policy(),{'connector':'line','owner_uid':1000,'note_sha256':'f'*64})
                if error==429:
                    assert decision['authentication_blocks_cleared']==0 and adapter.native_health()['next_attempt']==deadline
                    assert not await adapter.connect() and len(lookups)==before
                else:assert decision['authentication_blocks_cleared']>0 and await adapter.connect()
                cases.append('actual_content_'+str(error)+'_pauses_profile_and_preserves_reopen_owner_recheck_and_throttle_rules')
                await adapter.close_profile()
            value['channel_access_token']='private-line-media-abort';config['bindings'][0]['generation']='f'*64
            mode[0]='abort';adapter=create();assert await adapter.connect();before=len(accepted);await post('file')
            await until(lambda:inbox.db.execute("SELECT COUNT(*) FROM native_inbox WHERE state='pending' AND attempt>0 AND binding_digest=?",(__import__('haos.gateway',fromlist=['digest']).digest(config['bindings'][0]),)).fetchone()[0]>0)
            assert len(accepted)==before
            mode[0]='ok';await until(lambda:len(accepted)>before)
            assert cache.get(policy(),accepted[-1][1][0])['data']==document
            cases.append('actual_short_http_content_never_admits_partial_file_and_recovers_from_retained_input')
            assert 'private-unused-reply-capability' not in str(inbox.db.execute('SELECT payload FROM native_inbox').fetchall())
        finally:await adapter.close_profile();await runner.cleanup();inbox.close();relay.close();store.close()
    with tempfile.TemporaryDirectory(prefix='haos-line-media-') as td:asyncio.run(exercise(Path(td)))
    result={'passed':len(cases),'cases':cases,'actual_native_codec_https_content_relay_and_controller':True,
        'fixture_only_loopback_and_disposable_ca':True,'tls_verification_disabled':False,
        'external_account_inference_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
