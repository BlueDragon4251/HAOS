#!/usr/bin/env python3
"""Actual native file codecs, verified loopback HTTPS and first-byte/cache custody.

Private SQLite/HTTP component contract; the installed UID/controller process
contract is separate. No model inference, ASR or live external peer is claimed.
"""
import asyncio
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import Conflict
    from haos.gateway_a2a import credentials,scope,PreparedA2APolicy
    from haos.gateway_a2a_cache import RawEvents
    from haos.gateway_a2a_admission import approve,Refused as AdmissionRefused
    from haos.gateway_a2a_resources import Resources,Refused
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-a2a-file-codecs-') as temp:
        root=Path(temp);create(root,'a2a.fixture.invalid')
        with socket.socket() as chosen:chosen.bind(('127.0.0.1',0));port=chosen.getsockname()[1]
        origin='https://localhost:'+str(port)
        value=credentials({'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32},'port':8448,'agent_name':'HAOS',
            'download_origins':{'alice':[origin]},'tls':{'public_url':'https://a2a.fixture.invalid/a2a',
                'certificate':(root/'certificate.pem').read_text(),'private_key':(root/'key.pem').read_text(),
                'bind_host':'127.0.0.1','public_listener':False}},verify_tls=False)
        grant={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-files','scope':scope(value,'alice'),'thread':'',
            'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1,
            'allow_media':True,'allow_voice':True,'allow_video':True}
        config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[grant]};active=[True]
        policy=lambda:PreparedA2APolicy(config)
        def current():
            if not active[0]:raise PermissionError('fixture exact owner withdrawal')
        raw=RawEvents(root/'originals.db',Redactor(),current);inbox=NativeInbox(root/'native.db',raw.redactor)
        resources=Resources(value,'a2a',policy,current,raw,inbox)
        def message(name,parts):return {'jsonrpc':'2.0','id':name,'method':'SendMessage','params':{'message':{
            'messageId':name,'contextId':grant['chat'],'role':'ROLE_USER','parts':parts}}}
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5tUAAAAASUVORK5CYII=')
        def inline(data,name='document.txt',mime='text/plain'):return {'raw':base64.b64encode(data).decode(),'filename':name,'mediaType':mime}
        async def exercise():
            nonlocal raw,inbox,resources
            from aiohttp import web
            calls=[];body=[png]
            async def response(request):
                assert request.secure and 'Authorization' not in request.headers and 'Cookie' not in request.headers
                assert not any(token in str(request.headers) for token in value['peer_tokens'].values())
                calls.append(request.path)
                if request.path.startswith('/status/'):
                    return web.Response(status=int(request.path.rsplit('/',1)[1]),headers={'Location':'https://unapproved.invalid/private'})
                if request.path=='/broken':
                    reply=web.StreamResponse(headers={'Content-Type':'image/png','Content-Length':'10000'})
                    await reply.prepare(request);await reply.write(b'partial');request.transport.close();return reply
                return web.Response(body=body[0],content_type='image/png')
            app=web.Application();app.router.add_get('/{path:.*}',response);runner=web.AppRunner(app,access_log=None);await runner.setup()
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
            await web.TCPSite(runner,'127.0.0.1',port,ssl_context=tls).start()
            prior=os.environ.get('SSL_CERT_FILE');os.environ['SSL_CERT_FILE']=str(root/'ca.pem')
            try:
                document=message('inline-document',[inline(b'Original private document bytes.')])
                proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(document).encode())
                items=await resources.retained(proof)
                assert len(items)==1 and items[0]['kind']=='document'
                assert resources.cache.get(policy(),items[0]['id'])['data']==b'Original private document bytes.' and not calls
                cases.append('actual_native_inline_file_text_codec_and_FULL_snapshot_then_media_cache_retain_exact_original_bytes_without_HTTP')
                url=origin+'/image.png?signed=private-fixture-resource-capability'
                requested=message('uri-image',[{'url':url,'filename':'image.png','mediaType':'image/png'}])
                proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(requested).encode())
                assert url not in proof['envelope']['text'] and 'private-fixture-resource-capability' not in proof['envelope']['text']
                inbox.db.execute("CREATE TRIGGER failed_first_copy BEFORE INSERT ON native_media_cache BEGIN SELECT RAISE(ABORT,'fixture cache-copy failure'); END")
                try:await resources.retained(proof)
                except __import__('sqlite3').IntegrityError:pass
                else:raise AssertionError('failed private cache copy was hidden')
                snapshot=raw.db.execute('SELECT state,data,media_id FROM a2a_input_resources WHERE raw_id=?',(proof['id'],)).fetchone()
                assert tuple(snapshot)==('retained',png,'') and calls==['/image.png']
                inbox.db.execute('DROP TRIGGER failed_first_copy');body[0]=b'remote URI changed after first accepted bytes'
                raw.close();inbox.close()
                raw=RawEvents(root/'originals.db',Redactor(),current);inbox=NativeInbox(root/'native.db',raw.redactor)
                resources=Resources(value,'a2a',policy,current,raw,inbox)
                proof=raw.get(policy(),'a2a',value,'alice',proof['id']);items=await resources.retained(proof)
                assert resources.cache.get(policy(),items[0]['id'])['data']==png and calls==['/image.png']
                cases.append('actual_verified_TLS_file_read_omits_peer_credentials_and_agent_URL_capability')
                cases.append('real_SQLite_cache_copy_failure_and_reopen_preserve_first_response_without_refetching_changed_URI')
                resources.cache.transferred([items[0]['id']]);again=await resources.retained(proof)
                assert again==items and resources.cache.replay(policy(),items[0]['id'])['data'] is None and calls==['/image.png']
                cases.append('transferred_private_media_replay_preserves_receipt_without_restoring_consumed_cache_bytes_or_refetching')
                legacy=message('legacy-native-uri',[{'kind':'file','file':{'fileWithUri':url,'name':'legacy.png','mimeType':'image/png'}}])
                legacy_proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(legacy).encode())
                assert legacy_proof['resources'][0]['kind']=='image' and url not in legacy_proof['envelope']['text']
                cases.append('actual_native_legacy_fileWithUri_codec_preserves_opaque_carrier_and_exact_origin_permission')
                negatives=[inline(b'x',name='../owner-secret'),inline(b'x',mime='application/octet-stream; charset=utf8'),
                    inline(value['tls']['private_key'].encode(),mime='application/octet-stream'),
                    inline(b'fLaCprivate audio',mime='application/octet-stream'),inline(png,mime='application/octet-stream'),
                    {'raw':'YQ==\n','filename':'x.bin','mediaType':'application/octet-stream'},
                    {'raw':'YQ==','url':url,'mediaType':'application/octet-stream'},
                    {'url':origin+'/x#fragment','filename':'x.bin','mediaType':'application/octet-stream'},
                    {'url':'http://localhost:'+str(port)+'/x','filename':'x.bin','mediaType':'application/octet-stream'},
                    {'url':'https://unapproved.invalid/x','filename':'x.bin','mediaType':'application/octet-stream'},
                    {'url':origin.replace('https://','https://user:password@')+'/x','filename':'x.bin','mediaType':'application/octet-stream'},
                    {'raw':'YQ==','filename':'x.bin','mediaType':'application/octet-stream','plugin':'arbitrary'}]
                count=raw.db.execute('SELECT COUNT(*) FROM a2a_raw_events').fetchone()[0]
                for index,bad in enumerate(negatives):
                    try:raw.capture(policy(),'a2a',value,'alice',json.dumps(message('bad-file-'+str(index),[bad])).encode())
                    except (ValueError,PermissionError):pass
                    else:raise AssertionError('invalid or unapproved native file Part accepted')
                    assert raw.db.execute('SELECT COUNT(*) FROM a2a_raw_events').fetchone()[0]==count
                    cases.append('native_file_no_custody_or_HTTP_on_invalid_part_'+str(index))
                no_voice=deepcopy(config);no_voice['bindings'][0]['allow_voice']=False
                try:approve(PreparedA2APolicy(no_voice),'a2a',value,'alice',json.dumps(message('denied-voice',[inline(b'fLaCprivate audio',name='voice.flac',mime='audio/flac')])).encode(),Redactor())
                except AdmissionRefused as error:assert error.reason=='independent-media-consent-required'
                else:raise AssertionError('voice renamed as generic approved file or text')
                cases.append('explicit_voice_consent_is_independent_of_generic_media_and_no_audio_to_document_downgrade')
                for status,reason in [(401,'authentication-refused'),(429,'rate-limited'),(302,'source-unavailable')]:
                    request=message('status-'+str(status),[{'url':origin+'/status/'+str(status),'filename':'x.png','mediaType':'image/png'}])
                    item=raw.capture(policy(),'a2a',value,'alice',json.dumps(request).encode());before=len(calls)
                    for attempt in range(2):
                        if attempt:
                            raw.close();inbox.close()
                            raw=RawEvents(root/'originals.db',Redactor(),current);inbox=NativeInbox(root/'native.db',raw.redactor)
                            resources=Resources(value,'a2a',policy,current,raw,inbox)
                            item=raw.get(policy(),'a2a',value,'alice',item['id'])
                        try:await resources.retained(item)
                        except Refused as error:
                            assert error.reason in {reason,'transport-unavailable'}
                        else:raise AssertionError('non-200 native A2A file response admitted')
                    assert len(calls)==before+1
                    row=raw.db.execute('SELECT state,data,media_id FROM a2a_input_resources WHERE raw_id=?',(item['id'],)).fetchone()
                    assert tuple(row)==(reason,None,'')
                    cases.append('actual_HTTPS_'+str(status)+'_persists_refusal_backoff_and_does_not_follow_redirect_or_repeat_read')
                broken=raw.capture(policy(),'a2a',value,'alice',json.dumps(message('broken-file',[{'url':origin+'/broken','filename':'x.png','mediaType':'image/png'}])).encode())
                try:await resources.retained(broken)
                except Refused as error:assert error.reason=='transport-unavailable'
                else:raise AssertionError('partial HTTPS file became a complete attachment')
                assert raw.db.execute('SELECT data FROM a2a_input_resources WHERE raw_id=?',(broken['id'],)).fetchone()[0] is None
                cases.append('actual_truncated_HTTPS_body_never_commits_partial_snapshot_or_media_receipt')
                active[0]=False
                try:await resources.retained(proof)
                except PermissionError:pass
                else:raise AssertionError('withdrawn grant reused retained file bytes')
                active[0]=True;cases.append('current_owner_withdrawal_precedes_retained_and_cached_attachment_use')
            finally:
                if prior is None:os.environ.pop('SSL_CERT_FILE',None)
                else:os.environ['SSL_CERT_FILE']=prior
                await runner.cleanup()
        try:asyncio.run(exercise())
        finally:raw.close();inbox.close()
    Path(sys.argv[2]).write_text(json.dumps({'cases':cases,'passed':len(cases),'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'scope':'actual frozen native A2A file/text codecs, verified loopback HTTPS and real private FULL SQLite first-byte/cache recovery; explicit fixture CA trust in this process only',
        'installed_UID_controller_ASR_model_inference_live_peer_or_public_activation':False},indent=2)+'\n')
    print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
