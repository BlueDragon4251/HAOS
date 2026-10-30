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
                if request.path=='/query':return web.json_response([profile])
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
            async def run(args,text=None):
                env={'PATH':'/usr/bin:/bin','HOME':str(root),'LANG':'C.UTF-8','BUZZ_RELAY_URL':origin,'BUZZ_PRIVATE_KEY':scalar,
                    'BUZZ_OUTPUT_FORMAT':'json','BUZZ_TIMEOUT_SECS':'2','BUZZ_CONNECT_TIMEOUT_SECS':'2','SSL_CERT_FILE':str(root/'ca.pem')}
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
