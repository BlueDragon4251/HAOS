#!/usr/bin/env python3
"""Actual pinned SMS signatures/codec/sender, private REST and loopback TLS."""
import asyncio
import base64
import copy
from email.utils import formatdate
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time
from urllib.parse import urlencode


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_sms import PreparedSMSPolicy,scope
    from haos.gateway_runtime import build_adapter
    def build(value,**context):return build_adapter('sms',value,sms_context=context)
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.gateway_delivery import delivery_result
    from haos.gateway import digest
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    cases=[]
    async def exercise(root):
        from aiohttp import web,ClientSession,TCPConnector,DummyCookieJar
        os.environ.update(HERMES_HOME=str(root/'hermes'),HERMES_SAFE_MODE='1')
        tls=create(root,'sms.fixture.invalid');os.environ['SSL_CERT_FILE']=str(root/'ca.pem')
        trusted=ssl.create_default_context();assert trusted.check_hostname and trusted.verify_mode==ssl.CERT_REQUIRED
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(root/'certificate.pem',root/'key.pem')
        with socket.socket() as reserved:reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        value={'account_sid':'AC'+'a'*32,'auth_token':'b'*32,'from_number':'+12025550100','port':port,'tls':tls}
        sender='+12025550101';config={'version':1,'connectors':[{'id':'sms','platform':'sms'}],'bindings':[{
            'id':'owner','connector':'sms','sender':sender,'chat':sender,'scope':scope(value),'thread':'','identity':'personal',
            'capabilities':['create','read'],'generation':'c'*64,'since':1}]}
        line_sender='U'+'1'*32;line_destination='U'+'9'*32
        config['connectors'].append({'id':'line-shared','platform':'line'})
        config['bindings'].append({'id':'line-owner','connector':'line-shared','sender':line_sender,'chat':line_sender,
            'scope':line_destination,'thread':'','identity':'personal','capabilities':['create','read'],'generation':'8'*64,'since':1})
        policy=lambda:PreparedSMSPolicy(config)
        profiles=root/'profiles';profiles.mkdir(mode=0o700)
        inbox=NativeInbox(root/'native.db',Redactor());relay=RelayInbox(root/'relay.db',Redactor());accepted=[];lookups=[];pushes=[]
        messages={};resources={};downloads=[];recovery_rows=[];recovery_next=[None];mode=['success'];delivery=['e'*64]
        auth='Basic '+base64.b64encode((value['account_sid']+':'+value['auth_token']).encode()).decode()
        async def account(request):
            assert request.headers['Authorization']==auth;lookups.append('account')
            return web.json_response({'sid':value['account_sid'],'status':'active'})
        async def phones(request):
            assert request.headers['Authorization']==auth and request.query['PhoneNumber']==value['from_number'];lookups.append('phone')
            return web.json_response({'incoming_phone_numbers':[{'account_sid':value['account_sid'],'phone_number':value['from_number'],'capabilities':{'sms':True,'mms':True}}]})
        async def message(request):
            assert request.headers['Authorization']==auth;sid=request.match_info['message'];lookups.append(sid)
            item=messages[sid];body=item['Body'] if mode[0]!='mismatch' else 'different body'
            stamp=time.time()-3600 if mode[0]=='old' else item.get('__created',time.time())
            return web.json_response({'sid':sid,'account_sid':value['account_sid'],'from':item['From'],'to':item['To'],
                'body':body,'direction':'inbound','status':'received','num_media':item.get('NumMedia','0'),'date_created':formatdate(stamp,usegmt=True)})
        async def message_list(request):
            assert request.headers['Authorization']==auth
            assert request.query['From']==sender and request.query['To']==value['from_number'] and request.query['PageSize']=='10'
            return web.json_response({'messages':recovery_rows,'next_page_uri':recovery_next[0]})
        async def media_list(request):
            assert request.headers['Authorization']==auth
            sid=request.match_info['message'];lookups.append('media:'+sid)
            return web.json_response({'media_list':[{'sid':item['id'],'parent_sid':sid,'account_sid':value['account_sid'],
                'content_type':item['mime']} for item in resources[sid]],'next_page_uri':None})
        async def media_bytes(request):
            assert request.headers['Authorization']==auth
            item=next(item for items in resources.values() for item in items if item['id']==request.match_info['media'])
            downloads.append(('api',item['id']))
            if mode[0]=='foreign-cdn':return web.Response(status=307,headers={'Location':'http://127.0.0.1/private-owner'})
            if mode[0]=='cdn':return web.Response(status=307,headers={'Location':'https://mms.twiliocdn.com/cdn/'+item['id'],'Set-Cookie':'private=never-forward'})
            if mode[0]=='encoded':return web.Response(body=b'not-gzip',headers={'Content-Encoding':'gzip'})
            if mode[0]=='oversized':return web.Response(body=b'x'*500001)
            if mode[0]=='partial':
                response=web.StreamResponse(headers={'Content-Length':str(len(item['data']))});await response.prepare(request)
                await response.write(item['data'][:5]);request.transport.close();return response
            return web.Response(body=item['data'],headers={'Content-Type':item['mime'],'Content-Disposition':'attachment; filename="../../owner-private"'})
        async def cdn_bytes(request):
            assert 'Authorization' not in request.headers and 'Cookie' not in request.headers
            item=next(item for items in resources.values() for item in items if item['id']==request.match_info['media'])
            downloads.append(('cdn',item['id']));return web.Response(body=item['data'],headers={'Content-Type':item['mime']})
        async def push(request):
            assert request.headers['Authorization']==auth
            body=dict(await request.post());pushes.append(body)
            assert inbox.db.execute('SELECT state FROM sms_delivery_intents WHERE delivery_id=?',(delivery[0],)).fetchone()[0]=='writing'
            if type(mode[0]) is int:return web.json_response({'message':'private-provider-error'},status=mode[0],headers={'Retry-After':'7'})
            if mode[0]=='abort':request.transport.close();return web.Response()
            if mode[0]=='encoded-receipt':return web.Response(body=b'not-gzip',status=201,headers={'Content-Encoding':'gzip'})
            return web.json_response({'sid':'SM'+'f'*32,'account_sid':value['account_sid'],'from':value['from_number'],
                'to':sender,'body':body['Body'],'status':'queued'},status=201)
        async def line_info(request):
            assert request.headers['Authorization']=='Bearer private-shared-line-token'
            return web.json_response({'userId':line_destination})
        app=web.Application();app.router.add_get('/line-info',line_info);app.router.add_get('/accounts/{account}.json',account)
        app.router.add_get('/accounts/{account}/IncomingPhoneNumbers.json',phones)
        app.router.add_get('/accounts/{account}/Messages.json',message_list)
        app.router.add_get('/accounts/{account}/Messages/{message}.json',message)
        app.router.add_get('/accounts/{account}/Messages/{message}/Media.json',media_list)
        app.router.add_get('/accounts/{account}/Messages/{message}/Media/{media}',media_bytes)
        app.router.add_get('/cdn/{media}',cdn_bytes)
        app.router.add_post('/accounts/{account}/Messages.json',push)
        runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=context);await site.start()
        origin='https://localhost:'+str(site._server.sockets[0].getsockname()[1])
        from haos.gateway_media_relay import event_media,forward
        def receive(event):
            env=adapter_envelope(event,'sms');relay.admit(policy(),'sms',env,media=event_media(event,'sms'));accepted.append(event);return True
        def create_sms():
            result=build(value,parent=profiles,connector='sms',policy=policy,inbox=inbox)
            result._haos_sms_rest._fixture_origin=origin+'/accounts/'
            result._haos_sms_rest._cdn_fixture_origin=origin
            result._haos_sms_rest.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False,cookie_jar=DummyCookieJar())
            result._haos_sms_rest.client._retry_connection=False
            result._haos_sms_publisher._target=origin+'/accounts/'+value['account_sid']+'/Messages.json'
            result._haos_sms_publisher.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False,cookie_jar=DummyCookieJar())
            result._haos_sms_publisher.client._retry_connection=False
            result.set_durable_message_handler(receive);return result
        adapter=create_sms();publisher=adapter._haos_sms_publisher
        from haos.gateway_line_profile import build as build_line
        line_value={'channel_secret':'c'*32,'channel_access_token':'private-shared-line-token','destination':line_destination,
            'port':port,'tls':{**tls,'public_url':tls['public_url'].replace('/webhooks/twilio','/line/webhook')}}
        line=build_line(line_value,parent=profiles,connector='line-shared',policy=policy,inbox=inbox)
        line._haos_line_identity._target=origin+'/line-info'
        line._haos_line_identity.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False)
        line._haos_line_identity.client._retry_connection=False
        line_events=[]
        def line_receive(event):
            env=adapter_envelope(event,'line');relay.admit(policy(),'line-shared',env);line_events.append(event);return True
        line.set_durable_message_handler(line_receive)

        async def until(predicate,timeout=5):
            async with asyncio.timeout(timeout):
                while not predicate():await asyncio.sleep(.01)
        counter=[0]
        async def post(client,*,who=sender,body='A real local SMS mission',valid=True,extra=None,assets=None):
            counter[0]+=1;sid='SM'+f'{counter[0]:032x}'
            fields={'AccountSid':value['account_sid'],'MessageSid':sid,'From':who,'To':value['from_number'],'Body':body,'NumMedia':'0'}
            if assets is not None:
                fields['NumMedia']=str(len(assets))
                resources[sid]=[{'id':'ME'+f'{counter[0]*10+index:032x}','mime':mime,'data':data} for index,(data,mime) in enumerate(assets)]
                for index in range(len(assets)):fields['MediaUrl'+str(index)]='http://127.0.0.1/never-trust-this-remote-url'
            if extra:fields.update(extra)
            messages[sid]={**fields,'__created':time.time()}
            raw=urlencode(fields).encode();signed=value['tls']['public_url']+''.join(key+fields[key] for key in sorted(fields))
            signature=base64.b64encode(hmac.new(value['auth_token'].encode(),signed.encode(),hashlib.sha1).digest()).decode() if valid else 'A'*27+'='
            async with client.post(f'https://localhost:{port}/webhooks/twilio',data=raw,
                    headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature}) as response:
                status=response.status;text=await response.text()
            return status,sid,raw,signature,text
        try:
            connected=await adapter.connect()
            assert connected and adapter.native_health()['status']=='listening-tls',adapter.native_health()
            assert lookups==['account','phone'];cases.append('actual_native_private_account_auth_codec_and_owned_sms_number_verified_before_listener')
            assert await line.connect()
            assert adapter._haos_sms_runner.server is line._haos_line_runner.server
            cases.append('line_and_sms_share_one_verified_tls_listener_with_independent_owner_profiles')
            async with ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False) as client:
                line_body=json.dumps({'destination':line_destination,'events':[{'type':'message','mode':'active',
                    'timestamp':int(time.time()*1000),'webhookEventId':'01K8'+'D'*22,
                    'source':{'type':'user','userId':line_sender},'message':{'type':'text','id':'12345','text':'An independently signed LINE goal'}}]}).encode()
                line_signature=base64.b64encode(hmac.new(line_value['channel_secret'].encode(),line_body,hashlib.sha256).digest()).decode()
                async with client.post(f'https://localhost:{port}/line/webhook',data=line_body,headers={'X-Line-Signature':line_signature}) as response:assert response.status==200
                await until(lambda:len(line_events)==1)
                for path in ['/health','/api/owner','/unknown/plugin']:
                    async with client.get(f'https://localhost:{port}'+path) as response:assert response.status==404
                cases.append('shared_listener_keeps_real_line_signature_codec_and_no_health_owner_or_plugin_routes')
                await line.close_profile()
                async with client.post(f'https://localhost:{port}/line/webhook',data=line_body,headers={'X-Line-Signature':line_signature}) as response:assert response.status==404
                assert adapter.is_connected
                cases.append('closing_line_removes_its_route_without_disconnecting_sms_on_the_shared_socket')
                before=len(lookups);assert (await post(client,valid=False))[0]==403 and len(lookups)==before
                cases.append('bad_signature_refused_before_private_message_lookup_or_mission')
                assert (await post(client,who='+12025550199'))[0]==200 and len(lookups)==before and not accepted
                cases.append('signed_unknown_sender_never_gets_lookup_reply_or_mission')
                status,sid,raw,signature,text=await post(client)
                assert status==200 and '<Response' in text;await until(lambda:len(accepted)==1)
                assert accepted[0].message_id==sid and accepted[0].source.scope_id==scope(value)
                assert relay.db.execute('SELECT COUNT(*) FROM inbox WHERE connector=\"sms\"').fetchone()[0]==1
                cases.append('actual_signed_https_provider_body_timestamp_native_decoder_and_durable_relay')
                before=len(lookups)
                async with client.post(f'https://localhost:{port}/webhooks/twilio',data=raw,
                        headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature}) as response:assert response.status==200
                await asyncio.sleep(.1);assert len(accepted)==1 and len(lookups)==before
                cases.append('duplicate_signed_message_uses_durable_identity_without_new_lookup_or_admission')
                for scenario in ['mismatch','old']:
                    mode[0]=scenario
                    if scenario=='old':config['bindings'][0]['since']=int((time.time()-600)*1000)
                    # Changing a grant requires a fresh captured profile. Test
                    # timestamp refusal directly against the private REST reader
                    # without mutating the running profile's policy snapshot.
                    if scenario=='old':config['bindings'][0]['since']=1
                    if scenario=='mismatch':assert (await post(client))[0]==403
                    else:
                        fields={'MessageSid':'SM'+'d'*32,'AccountSid':value['account_sid'],'From':sender,'To':value['from_number'],'Body':'old real resource'}
                        messages[fields['MessageSid']]=fields
                        binding={**config['bindings'][0],'since':int((time.time()-600)*1000)}
                        try:await adapter._haos_sms_rest.message(fields,binding,lambda:None)
                        except PermissionError:pass
                        else:raise AssertionError('old SMS admitted under a new grant')
                    cases.append('authenticated_provider_'+scenario+'_cannot_create_mission')
                mode[0]='success'
                from io import BytesIO
                from PIL import Image
                import av,wave
                image=BytesIO();Image.new('RGB',(4,4),(20,40,60)).save(image,format='PNG');png=image.getvalue()
                wav=BytesIO()
                with wave.open(wav,'wb') as audio:
                    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\0\0'*16000)
                movie=BytesIO()
                with av.open(movie,'w',format='3gp') as output:
                    stream=output.add_stream('mpeg4',rate=5);stream.width=16;stream.height=16;stream.pix_fmt='yuv420p'
                    frame=av.VideoFrame(16,16,'yuv420p')
                    for plane in frame.planes:plane.update(bytes([70])*plane.buffer_size)
                    for packet in stream.encode(frame):output.mux(packet)
                    for packet in stream.encode(None):output.mux(packet)
                before=len(lookups);ignored=await post(client,body='',assets=[(png,'image/png')])
                assert ignored[0]==200 and len(lookups)==before and not downloads
                cases.append('signed_mms_without_separate_media_consent_performs_no_private_lookup_or_download')
                await adapter.close_profile()
                config['bindings'][0].update(allow_media=True,allow_voice=True,allow_video=True,generation='7'*64,since=int(time.time()*1000))
                adapter=create_sms();publisher=adapter._haos_sms_publisher;assert await adapter.connect()
                async with client.post(f'https://localhost:{port}/webhooks/twilio',data=ignored[2],headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':ignored[3]}) as response:assert response.status==403
                cases.append('previously_ignored_old_mms_cannot_gain_authority_from_a_fresh_owner_grant')
                await asyncio.sleep(1.05)  # Provider timestamps have one-second precision.
                before=len(accepted)
                files=[(png,'image/png'),(b'private document fixture','application/pdf'),(wav.getvalue(),'audio/wav'),(movie.getvalue(),'video/3gpp')]
                from haos import gateway_sms_media
                original_download=gateway_sms_media.download;decode_errors=[]
                async def observed_download(*args):
                    try:return await original_download(*args)
                    except Exception as error:decode_errors.append(type(error).__name__+': '+str(error));raise
                gateway_sms_media.download=observed_download
                mode[0]='cdn';status,media_sid,*_=await post(client,body='',assets=files)
                assert status==200
                try:await until(lambda:len(accepted)==before+1 or decode_errors)
                except TimeoutError:
                    print({'diagnostic':adapter.native_health(),'inbox':[(r['platform'],r['state'],r['attempt']) for r in inbox.db.execute('SELECT platform,state,attempt FROM native_inbox')],'downloads':downloads,'lookup_count':len(lookups)},flush=True)
                    raise
                finally:gateway_sms_media.download=original_download
                assert not decode_errors,decode_errors

                current=relay.next(policy())
                # Earlier text receipts are not the media obligation under test.
                while current and current['envelope']['message_id']!=media_sid:
                    relay.admitted(current['id'],'00000000-0000-4000-8000-000000000001');current=relay.next(policy())
                assert current and len(current['media'])==4
                from haos.gateway_media_relay import MediaCache
                cache=MediaCache(inbox)
                received=[cache.get(policy(),identity) for identity in current['media']]
                assert [item['data'] for item in received]==[data for data,mime in files]
                assert [item['descriptor']['kind'] for item in received]==['image','document','voice','video']
                assert received[-1]['descriptor']['format']=='3gp'
                assert all(url.startswith('haos-media:') for url in accepted[-1].media_urls)
                assert len([x for x in downloads if x[0]=='cdn'])==4
                cases.append('actual_mms_empty_body_native_decoder_and_four_private_media_kinds_with_no_remote_paths')
                cases.append('verified_official_cdn_redirect_never_forwards_account_auth_or_cookies')
                from haos.controller import Controller
                from haos.store import MissionStore
                store=MissionStore(root/'controller.db');controller=Controller(store,'unused-local-fixture',set());controller.gateway_policy=policy
                async def bridge(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
                try:
                    admitted=await forward(policy,'sms',current['envelope'],current['media'],cache,bridge)
                    assert [item['data'] for item in controller.gateway.media.for_mission(policy(),admitted['mission_id'])]==[data for data,mime in files]
                    relay.admitted(current['id'],admitted['mission_id']);cache.transferred(current['media'])
                    cases.append('actual_controller_chunked_mms_admission_preserves_image_document_voice_and_3gp_bytes')
                finally:store.close()
                first_resource=resources[media_sid][0]
                from haos.gateway_sms_media import metadata as media_metadata
                checked=media_metadata({'sid':first_resource['id'],'account_sid':value['account_sid'],'parent_sid':media_sid,'content_type':'image/png'},value['account_sid'],media_sid)
                mode[0]='foreign-cdn';before_cdn=len([x for x in downloads if x[0]=='cdn'])
                try:await adapter._haos_sms_rest.content(media_sid,checked,lambda:None)
                except __import__('haos.gateway_sms_rest',fromlist=['Refused']).Refused:pass
                else:raise AssertionError('foreign MMS redirect accepted')
                assert len([x for x in downloads if x[0]=='cdn'])==before_cdn
                cases.append('foreign_or_plaintext_mms_redirect_is_refused_without_a_second_request')
                bounded={**checked,'mime':'audio/wav','kind':'voice'}
                for failure in ['encoded','oversized','partial']:
                    mode[0]=failure
                    try:await adapter._haos_sms_rest.content(media_sid,bounded,lambda:None)
                    except (__import__('haos.gateway_sms_rest',fromlist=['Refused']).Refused,__import__('aiohttp').ClientError):pass
                    else:raise AssertionError('unbounded or incomplete MMS bytes accepted: '+failure)
                    cases.append('mms_'+failure+'_content_is_refused_without_partial_admission')
                mode[0]='success'
            from haos.gateway_sms_recovery import recover
            missed='SM'+'e'*32
            fields={'AccountSid':value['account_sid'],'MessageSid':missed,'From':sender,'To':value['from_number'],
                'Body':'Recovered without a webhook','NumMedia':'0','__created':time.time()}
            messages[missed]=fields
            recovery_rows.append({'sid':missed,'account_sid':value['account_sid'],'from':sender,'to':value['from_number'],
                'body':fields['Body'],'direction':'inbound','status':'received','num_media':'0','date_created':formatdate(fields['__created'],usegmt=True)})
            unsupported='MM'+'0'*31+'9'
            messages[unsupported]={**fields,'MessageSid':unsupported,'Body':'Too many MMS attachments','NumMedia':'5'}
            recovery_rows.insert(0,{'sid':unsupported,'account_sid':value['account_sid'],'from':sender,'to':value['from_number'],
                'body':messages[unsupported]['Body'],'direction':'inbound','status':'received','num_media':'5','date_created':formatdate(fields['__created'],usegmt=True)})
            before=len(accepted);await recover(adapter);await until(lambda:len(accepted)==before+1)
            refused=inbox.db.execute('SELECT message_sid,reason FROM sms_recovery_rejections').fetchone()
            assert tuple(refused)==(unsupported,'unsupported-content')
            from haos.gateway_raw_recovery import unresolved
            assert unresolved(inbox)['recovery_rejections'][0]['message_sid']==unsupported
            cases.append('authenticated_unsupported_mms_keeps_bounded_refusal_receipt_without_starving_later_supported_messages')

            retained=inbox.db.execute('SELECT origin FROM sms_input_origins WHERE identity=?',(inbox.key('sms',adapter_envelope(accepted[-1],'sms')),)).fetchone()
            assert retained['origin']=='authenticated-api-recovery'
            cases.append('missed_webhook_is_recovered_from_authenticated_filtered_api_and_actual_native_decoder_with_explicit_origin')
            await recover(adapter);await asyncio.sleep(.1);assert len(accepted)==before+1
            cases.append('repeated_recovery_sweep_deduplicates_the_same_provider_message')
            recovery_next[0]='https://foreign.invalid/private-owner'
            try:await recover(adapter)
            except PermissionError:pass
            else:raise AssertionError('foreign recovery page accepted')
            assert inbox.db.execute('SELECT continuation FROM sms_recovery_pages').fetchone()[0] is None
            assert inbox.db.execute('SELECT status FROM sms_recovery_status').fetchone()[0]=='backfill-unavailable'
            recovery_next[0]=None
            cases.append('foreign_provider_pagination_is_refused_without_advancing_durable_recovery_cursor')
            await recover(adapter)
            assert inbox.db.execute('SELECT status FROM sms_recovery_status').fetchone()[0]=='backfill-ready'
            cases.append('recovery_failure_and_success_are_persisted_without_claiming_complete_remote_history')
            started=time.time();recovery_next[0]='https://foreign.invalid/private-owner'
            await until(lambda:inbox.db.execute('SELECT updated_at FROM sms_recovery_status').fetchone()[0]>started,timeout=35)
            assert adapter.is_connected and adapter.native_health()['status']=='listening-tls'
            assert inbox.db.execute('SELECT status FROM sms_recovery_status').fetchone()[0]=='backfill-unavailable'
            recovery_next[0]=None
            cases.append('actual_periodic_recovery_refusal_retains_cursor_and_listener_without_falsely_claiming_owner_revocation')
            binding=copy.deepcopy(config['bindings'][0]);metadata={'haos_scope':binding['scope'],
                'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},'haos_delivery_id':delivery[0],'haos_delivery_attempt':1}
            result=await adapter.send(sender,'**Actual SMS** reply',metadata=metadata)
            assert delivery_result(result)['status']=='delivered' and pushes==[{'From':value['from_number'],'To':sender,'Body':'Actual SMS reply'}]
            cases.append('actual_native_sms_formatter_form_sender_and_exact_server_receipt_after_private_write_intent')
            duplicate=await adapter.send(sender,'**Actual SMS** reply',metadata=metadata)
            assert duplicate.message_id==result.message_id and len(pushes)==1
            cases.append('confirmed_same_attempt_never_repeats_native_sms_http_write')
            for scenario,expected in [('abort','uncertain'),('encoded-receipt','uncertain'),(429,'retry')]:
                mode[0]=scenario;delivery[0]=digest(str(scenario));metadata['haos_delivery_id']=delivery[0]
                result=await adapter.send(sender,'A bounded fixture SMS',metadata=metadata)
                assert delivery_result(result)['status']==expected
                if scenario in {'abort','encoded-receipt'}:
                    before=len(pushes)
                    repeated=await adapter.send(sender,'A bounded fixture SMS',metadata=metadata)
                    assert delivery_result(repeated)['status']=='uncertain' and len(pushes)==before
                    cases.append(str(scenario)+'_native_sms_write_is_uncertain_and_same_attempt_is_never_repeated')
                if scenario==429:
                    assert not adapter.is_connected and adapter.native_health()['status']=='rate-limited'
                    assert not await adapter.connect()
                    before=len(lookups)
                    assert not await adapter.connect() and len(lookups)==before
            cases.append('explicit_native_sms_rate_refusal_pauses_profile_and_retains_wait_deadline')
            deadline=adapter.native_health()['next_attempt'];before=len(lookups)
            await adapter.close_profile()
            blocked=build(value,parent=profiles,connector='sms',policy=policy,inbox=inbox)
            try:
                assert not await blocked.connect() and len(lookups)==before and blocked.native_health()['next_attempt']==deadline
                cases.append('new_profile_reacquires_private_lease_without_bypassing_persistent_rate_deadline')
            finally:await blocked.close_profile()
        finally:await line.close_profile();await adapter.close_profile();await runner.cleanup();relay.close();inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-sms-native-') as name:
        root=Path(name);root.chmod(0o700);asyncio.run(exercise(root))
    result={'passed':len(cases),'cases':cases,'actual_pinned_sms_and_verified_loopback_https':True,
        'public_sms_owner_policy_supported':True,'tls_verification_disabled':False,'external_sms_charges_accounts_or_delivery':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
