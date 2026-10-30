#!/usr/bin/env python3
"""Actual pinned official Buzz CLI, NIP-98 and signed writes over fixture TLS."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from plugins.platforms.buzz import nostr_auth
    from webhook_tls_fixture import create
    cli=Path(sys.argv[2]).resolve(strict=True);verifier=Path(sys.argv[3]).resolve(strict=True);cases=[]
    scalar=format(1,'064x');public=nostr_auth.public_key_hex(scalar)
    def signed(kind,content,tags):
        event={'pubkey':public,'created_at':int(time.time()),'kind':kind,'tags':tags,'content':content}
        event['id']=hashlib.sha256(json.dumps([0,public,event['created_at'],kind,tags,content],separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        event['sig']=nostr_auth.schnorr_sign(bytes.fromhex(event['id']),scalar).hex();return event
    def verified(event):
        result=subprocess.run([str(verifier)],input=json.dumps(event,separators=(',',':')).encode(),capture_output=True,timeout=5)
        assert result.returncode==0 and json.loads(result.stdout)=={'valid':True,'id':event['id'],'pubkey':event['pubkey']}
    with tempfile.TemporaryDirectory(prefix='haos-buzz-cli-') as temp:
        root=Path(temp);create(root,'buzz.fixture.invalid')
        with socket.socket() as chosen:chosen.bind(('127.0.0.1',0));port=chosen.getsockname()[1]
        origin='https://localhost:'+str(port);mode={'name':'ok'};calls=[];writes=[];auth_ids=[];escapes=[]
        profile=signed(0,json.dumps({'name':'haos-fixture','display_name':'HAOS Fixture'}),[])
        read_event=signed(9,'Composite local history event',[['h','01234567-89ab-4cde-8012-3456789abcde']]);queries=[]
        async def exercise():
            from aiohttp import web
            async def handle(request):
                if request.path=='/escape':escapes.append(True);return web.json_response([])
                assert request.secure and request.method=='POST' and request.path in {'/query','/events'}
                raw=await request.read();header=request.headers['Authorization'];assert header.startswith('Nostr ')
                auth=json.loads(base64.b64decode(header[6:],validate=True));verified(auth)
                tags={row[0]:row[1] for row in auth['tags'] if len(row)==2}
                assert auth['kind']==27235 and auth['pubkey']==public and abs(auth['created_at']-time.time())<60
                assert tags['u']==origin+request.path and tags['method']=='POST' and tags['payload']==hashlib.sha256(raw).hexdigest()
                assert scalar not in raw.decode() and scalar not in header
                auth_ids.append(auth['id']);calls.append(request.path)
                if mode['name']=='auth':return web.json_response({'error':'unauthorized fixture'},status=401)
                if mode['name']=='redirect':return web.Response(status=302,headers={'Location':origin+'/escape'})
                if request.path=='/query':
                    if mode['name']=='malformed-history':return web.Response(text='not a JSON array',content_type='application/json')
                    if mode['name']=='invalid-encoding':return web.Response(body=b'\xff',content_type='application/json')
                    if mode['name']=='oversized-error':return web.Response(status=400,body=b'x'*65537)
                    if mode['name']=='invalid-auth-body':return web.Response(status=401,body=b'\xff')
                    if mode['name']=='oversized-header':
                        response=web.StreamResponse(headers={'Content-Length':str(8*1024*1024+1)})
                        await response.prepare(request);return response
                    if mode['name']=='oversized-chunks':
                        response=web.StreamResponse();await response.prepare(request)
                        try:
                            for _ in range(129):await response.write(b'x'*65536)
                            await response.write_eof()
                        except ConnectionResetError:pass
                        return response
                    queries.append(json.loads(raw));return web.json_response([read_event] if mode['name']=='cursor' else [profile])
                event=json.loads(raw);verified(event);writes.append(raw)
                assert event['kind']==9 and event['pubkey']==public and ['h','01234567-89ab-4cde-8012-3456789abcde'] in event['tags']
                if mode['name']=='rate' and len(writes)==1:
                    return web.json_response({'error':'rate-limited: retry in 1s'},status=429)
                if mode['name']=='drop':
                    request.transport.close();return web.Response()
                return web.json_response({'event_id':event['id'],'accepted':True,'message':'stored fixture event'})
            app=web.Application(client_max_size=1048576);app.router.add_route('*','/{path:.*}',handle)
            runner=web.AppRunner(app,access_log=None);await runner.setup()
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
            await web.TCPSite(runner,'127.0.0.1',port,ssl_context=tls).start()
            async def run(args,text=None,before_id=None,approval=None):
                env={'PATH':'/usr/bin:/bin','HOME':str(root),'LANG':'C.UTF-8','BUZZ_RELAY_URL':origin,'BUZZ_PRIVATE_KEY':scalar,
                    'BUZZ_OUTPUT_FORMAT':'json','BUZZ_TIMEOUT_SECS':'2','BUZZ_CONNECT_TIMEOUT_SECS':'2','SSL_CERT_FILE':str(root/'ca.pem')}
                if before_id is not None:env['HAOS_BUZZ_BEFORE_ID']=before_id
                if approval is not None:env['HAOS_BUZZ_APPROVAL_SOCKET']=approval
                process=await asyncio.create_subprocess_exec(str(cli),*args,stdin=asyncio.subprocess.PIPE if text is not None else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
                try:out,err=await asyncio.wait_for(process.communicate(None if text is None else text.encode()),20)
                except BaseException:
                    if process.returncode is None:process.kill();await process.wait()
                    raise
                assert scalar.encode() not in out+err
                return process.returncode,out,err
            args=['messages','send','--channel','01234567-89ab-4cde-8012-3456789abcde','--content','-']
            try:
                code,out,err=await run(['users','get']);assert code==0,(code,out,err)
                value=json.loads(out);assert value==[{'pubkey':public,'name':'haos-fixture','display_name':'HAOS Fixture'}]
                cases.append('actual_pinned_official_Rust_CLI_queries_verified_TLS_relay_with_SDK_verified_NIP98_identity_method_URL_payload_and_nonce_without_private_key_on_wire')
                code,out,err=await run(args,'First local signed message');assert code==0,(code,out,err)
                receipt=json.loads(out);assert receipt['accepted'] is True and receipt['event_id']==json.loads(writes[-1])['id']
                assert json.loads(writes[-1])['content']=='First local signed message'
                cases.append('actual_native_CLI_message_builder_signing_and_HTTP_acceptance_receipt_preserve_exact_content_channel_and_event_id')
                mode['name']='rate';writes.clear();before=time.monotonic()
                code,out,err=await run(args,'Rate limited local message');assert code==0,(code,out,err)
                assert len(writes)==2 and writes[0]==writes[1] and time.monotonic()-before>=.8
                assert len(set(auth_ids[-2:]))==2
                cases.append('definite_429_retries_exact_same_signed_event_body_and_identity_with_bounded_native_delay_and_fresh_NIP98_nonce')
                mode['name']='auth';count=len(calls)
                code,out,err=await run(['users','get']);assert code==3 and len(calls)==count+1,(code,out,err)
                cases.append('actual_401_refuses_authentication_without_automatic_retry_or_false_account_readiness')
                mode['name']='redirect'
                code,out,err=await run(['users','get']);assert code!=0 and not escapes,(code,out,err)
                cases.append('reviewed_exact_source_default_HTTP_transport_overlay_refuses_302_without_following_or_forwarding_authentication')
                mode['name']='cursor'
                cursor='a'*64;timestamp=int(time.time())
                read_args=['messages','get','--channel','01234567-89ab-4cde-8012-3456789abcde','--limit','50','--before',str(timestamp),'--since','1']
                code,out,err=await run(read_args,before_id=cursor);assert code==0,(code,out,err)
                assert json.loads(out)==[read_event]
                assert isinstance(queries[-1],list) and len(queries[-1])==1
                selection=queries[-1][0]
                assert selection['until']==timestamp and selection['since']==1 and selection['before_id']==cursor
                assert selection['#h']==['01234567-89ab-4cde-8012-3456789abcde'] and selection['limit']==50
                cases.append('scoped_typed_composite_history_cursor_retains_exact_channel_time_bounds_and_complete_signed_native_message_fields')
                count=len(calls)
                code,out,err=await run(read_args,before_id='../untrusted');assert code==1 and len(calls)==count,(code,out,err)
                no_timestamp=['messages','get','--channel','01234567-89ab-4cde-8012-3456789abcde']
                code,out,err=await run(no_timestamp,before_id=cursor);assert code==1 and len(calls)==count,(code,out,err)
                cases.append('invalid_or_unpaired_history_cursor_is_refused_before_HTTP_or_NIP98_request')
                mode['name']='malformed-history'
                code,out,err=await run(read_args);assert code==4 and not out,(code,out,err)
                assert json.loads(err)['message']=='invalid history response'
                cases.append('malformed_successful_HTTP_history_is_an_explicit_native_CLI_error_not_an_empty_complete_history')
                for name in ['oversized-header','oversized-chunks']:
                    mode['name']=name;before=len(calls)
                    code,out,err=await run(read_args)
                    assert code==4 and not out and json.loads(err)['message']=='response_limit',(code,out,err)
                    assert len(calls)==before+1
                cases.append('actual_native_HTTP_reader_refuses_over_8MiB_declared_or_chunked_bodies_before_JSON_allocation_and_without_retry_or_empty_history')
                mode['name']='oversized-error';before=len(calls)
                code,out,err=await run(read_args)
                assert code==2 and not out and json.loads(err)['message']=='relay error 400: response_limit',(code,out,err)
                assert len(calls)==before+1
                cases.append('actual_native_HTTP_error_body_limit_preserves_status_without_unbounded_body_or_read_retry')
                mode['name']='invalid-auth-body';before=len(calls)
                code,out,err=await run(read_args)
                assert code==3 and not out and json.loads(err)['message']=='relay error 401: authentication refused',(code,out,err)
                assert len(calls)==before+1
                cases.append('actual_definite_401_refuses_before_opaque_body_parsing_even_when_body_is_invalid_UTF8_without_retry_or_false_network_failure')
                mode['name']='invalid-encoding'
                code,out,err=await run(read_args)
                assert code==4 and not out and json.loads(err)['message']=='invalid response encoding',(code,out,err)
                cases.append('actual_native_JSON_query_refuses_invalid_UTF8_without_lossy_replacement_or_fake_empty_history')
                mode['name']='ok';approval_name='haos-buzz-'+os.urandom(32).hex()
                observed=asyncio.Event();allowed=asyncio.Event();guard_mode={'name':'allow'};guarded=[];guard_errors=[]
                async def approve(reader,writer):
                    try:
                        async with asyncio.timeout(10):
                            pid,uid,gid=struct.unpack('3i',writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                            assert pid>0 and uid==os.geteuid() and gid==os.getegid()
                            size=int.from_bytes(await reader.readexactly(4),'big');assert 0<size<=1048576
                            raw=await reader.readexactly(size);event=json.loads(raw);verified(event)
                            assert event['pubkey']==public and event['kind']==9 and ['h','01234567-89ab-4cde-8012-3456789abcde'] in event['tags']
                            guarded.append(raw)
                            if guard_mode['name']=='allow':
                                with (root/'retained-signed-event.json').open('xb') as stream:
                                    stream.write(raw);stream.flush();os.fsync(stream.fileno())
                                observed.set();await allowed.wait();writer.write(b'\x01');await writer.drain()
                            elif guard_mode['name']=='deny':writer.write(b'\x00');await writer.drain()
                            else:assert guard_mode['name']=='drop'
                    except BaseException as error:guard_errors.append(type(error).__name__)
                    finally:writer.close();await writer.wait_closed()
                guard=await asyncio.start_unix_server(approve,path='\0'+approval_name)
                try:
                    count=len(writes);operation=asyncio.create_task(run(args,'Locally approved signed original',approval=approval_name))
                    await asyncio.wait_for(observed.wait(),10)
                    assert len(writes)==count and not operation.done()
                    retained=(root/'retained-signed-event.json').read_bytes();assert retained==guarded[-1]
                    allowed.set();code,out,err=await operation;assert code==0 and len(writes)==count+1,(code,out,err)
                    assert writes[-1]==retained and json.loads(out)['event_id']==json.loads(retained)['id']
                    cases.append('actual_native_signed_message_blocks_before_HTTP_until_private_peer_checked_bounded_event_is_fsynced_and_explicitly_approved_then_submits_exact_original_bytes_and_id')
                    for choice in ['deny','drop']:
                        guard_mode['name']=choice;count=len(writes)
                        code,out,err=await run(args,'Locally refused '+choice,approval=approval_name)
                        assert code==4 and not out and json.loads(err)['message']=='private event approval refused',(code,out,err)
                        assert len(writes)==count
                    assert len(guarded)==3 and not guard_errors
                    cases.append('actual_native_prepublication_refusal_and_approval_channel_disconnect_never_submit_signed_message_or_fallback_to_unguarded_send')
                finally:guard.close();await guard.wait_closed()
                mode['name']='drop';writes.clear()
                code,out,err=await run(args,'Ambiguous local message');assert code!=0 and len(writes)==3,(code,out,err)
                assert writes[0]==writes[1]==writes[2] and len(set(auth_ids[-3:]))==3
                failure=json.loads(err);assert failure['error']=='delivery_unknown' and failure['retryable'] is False,failure
                cases.append('post_body_disconnect_retries_only_same_idempotent_native_event_then_reports_delivery_unknown_not_retryable_for_new_CLI_invocation')
            finally:await runner.cleanup()
        asyncio.run(exercise())
    Path(sys.argv[4]).write_text(json.dumps({'passed':len(cases),'cases':cases,
        'official_buzz_commit':'1eb67bb525d66448b56d79f98c4ba0e2188b44c5','cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),
        'scope':'actual compiled pinned official CLI plus exact no-redirect constructor overlay and official Rust signature verifier, trusted fixture CA and local TLS relay',
        'private_UID_HAOS_ingress_mission_live_relay_GUI_or_public_activation':False},indent=2)+'\n')
    print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
