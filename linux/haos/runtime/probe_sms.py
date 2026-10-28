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
    from haos.gateway_sms_profile import build
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.gateway_delivery import delivery_result
    from haos.gateway import digest
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    cases=[]
    async def exercise(root):
        from aiohttp import web,ClientSession,TCPConnector
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
        messages={};mode=['success'];delivery=['e'*64]
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
            stamp=time.time()-3600 if mode[0]=='old' else time.time()
            return web.json_response({'sid':sid,'account_sid':value['account_sid'],'from':item['From'],'to':item['To'],
                'body':body,'direction':'inbound','status':'received','num_media':'0','date_created':formatdate(stamp,usegmt=True)})
        async def push(request):
            assert request.headers['Authorization']==auth
            body=dict(await request.post());pushes.append(body)
            assert inbox.db.execute('SELECT state FROM sms_delivery_intents WHERE delivery_id=?',(delivery[0],)).fetchone()[0]=='writing'
            if type(mode[0]) is int:return web.json_response({'message':'private-provider-error'},status=mode[0],headers={'Retry-After':'7'})
            if mode[0]=='abort':request.transport.close();return web.Response()
            return web.json_response({'sid':'SM'+'f'*32,'account_sid':value['account_sid'],'from':value['from_number'],
                'to':sender,'body':body['Body'],'status':'queued'},status=201)
        async def line_info(request):
            assert request.headers['Authorization']=='Bearer private-shared-line-token'
            return web.json_response({'userId':line_destination})
        app=web.Application();app.router.add_get('/line-info',line_info);app.router.add_get('/accounts/{account}.json',account)
        app.router.add_get('/accounts/{account}/IncomingPhoneNumbers.json',phones)
        app.router.add_get('/accounts/{account}/Messages/{message}.json',message)
        app.router.add_post('/accounts/{account}/Messages.json',push)
        runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0,ssl_context=context);await site.start()
        origin='https://localhost:'+str(site._server.sockets[0].getsockname()[1])
        adapter=build(value,parent=profiles,connector='sms',policy=policy,inbox=inbox)
        adapter._haos_sms_rest._fixture_origin=origin+'/accounts/'
        adapter._haos_sms_rest.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False)
        adapter._haos_sms_rest.client._retry_connection=False
        publisher=adapter._haos_sms_publisher;publisher._target=origin+'/accounts/'+value['account_sid']+'/Messages.json'
        publisher.client=ClientSession(connector=TCPConnector(ssl=trusted),trust_env=False);publisher.client._retry_connection=False
        def receive(event):
            env=adapter_envelope(event,'sms');relay.admit(policy(),'sms',env);accepted.append(event);return True
        adapter.set_durable_message_handler(receive)
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

        async def until(predicate):
            async with asyncio.timeout(5):
                while not predicate():await asyncio.sleep(.01)
        counter=[0]
        async def post(client,*,who=sender,body='A real local SMS mission',valid=True,extra=None):
            counter[0]+=1;sid='SM'+f'{counter[0]:032x}'
            fields={'AccountSid':value['account_sid'],'MessageSid':sid,'From':who,'To':value['from_number'],'Body':body,'NumMedia':'0'}
            if extra:fields.update(extra)
            messages[sid]=dict(fields)
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
            binding=copy.deepcopy(config['bindings'][0]);metadata={'haos_scope':binding['scope'],
                'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},'haos_delivery_id':delivery[0],'haos_delivery_attempt':1}
            result=await adapter.send(sender,'**Actual SMS** reply',metadata=metadata)
            assert delivery_result(result)['status']=='delivered' and pushes==[{'From':value['from_number'],'To':sender,'Body':'Actual SMS reply'}]
            cases.append('actual_native_sms_formatter_form_sender_and_exact_server_receipt_after_private_write_intent')
            duplicate=await adapter.send(sender,'**Actual SMS** reply',metadata=metadata)
            assert duplicate.message_id==result.message_id and len(pushes)==1
            cases.append('confirmed_same_attempt_never_repeats_native_sms_http_write')
            for scenario,expected in [('abort','uncertain'),(429,'retry')]:
                mode[0]=scenario;delivery[0]=digest(str(scenario));metadata['haos_delivery_id']=delivery[0]
                result=await adapter.send(sender,'A bounded fixture SMS',metadata=metadata)
                assert delivery_result(result)['status']==expected
                if scenario=='abort':
                    before=len(pushes)
                    repeated=await adapter.send(sender,'A bounded fixture SMS',metadata=metadata)
                    assert delivery_result(repeated)['status']=='uncertain' and len(pushes)==before
                    cases.append('aborted_native_sms_write_is_uncertain_and_same_attempt_is_never_repeated')
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
        'prepared_only_not_public_setup_yet':True,'tls_verification_disabled':False,'external_sms_charges_accounts_or_delivery':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
