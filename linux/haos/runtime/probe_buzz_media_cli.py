#!/usr/bin/env python3
"""Actual pinned Blossom GET, verified TLS and binary response limits, no live relay."""
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
    from plugins.platforms.buzz.nostr_auth import public_key_hex
    from webhook_tls_fixture import create
    cli=Path(sys.argv[2]).resolve(strict=True);verifier=Path(sys.argv[3]).resolve(strict=True)
    scalar=format(1,'064x');public=public_key_hex(scalar);cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-buzz-blossom-') as directory:
        root=Path(directory);create(root,'buzz.fixture.invalid')
        with socket.socket() as chosen:chosen.bind(('127.0.0.1',0));port=chosen.getsockname()[1]
        origin='https://localhost:'+str(port);data=b'Local binary Blossom resource\x00\xff';sha=hashlib.sha256(data).hexdigest()
        mode={'name':'ok'};calls=[];escapes=[]
        async def exercise():
            from aiohttp import web
            async def handle(request):
                if request.path=='/escape':escapes.append(True);return web.Response()
                assert request.secure and request.method=='GET' and request.path=='/media/'+sha+'.bin'
                header=request.headers['Authorization'];assert header.startswith('Nostr ')
                encoded=header[6:];event=json.loads(base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4)))
                verified=subprocess.run([str(verifier)],input=json.dumps(event),text=True,capture_output=True,timeout=5)
                assert verified.returncode==0 and json.loads(verified.stdout)=={'valid':True,'id':event['id'],'pubkey':public}
                tags={part[0]:part[1] for part in event['tags'] if len(part)==2}
                assert event['pubkey']==public and event['kind']==24242 and event['content']=='Get media'
                assert set(tags)=={'t','expiration','server'} and tags['t']=='get' and tags['server']=='localhost:'+str(port)
                assert 0<int(tags['expiration'])-event['created_at']<=60 and abs(event['created_at']-time.time())<60
                assert scalar not in header and not request.headers.get('Cookie')
                calls.append({'mode':mode['name'],'id':event['id']})
                if mode['name']=='redirect':return web.Response(status=302,headers={'Location':origin+'/escape'})
                if mode['name']=='auth':return web.Response(status=401,body=b'\xff')
                if mode['name']=='rate':return web.json_response({'error':'rate-limited: retry in 0s'},status=429)
                if mode['name']=='header':
                    response=web.StreamResponse(headers={'Content-Length':str(8*1024*1024+1)})
                    await response.prepare(request);return response
                if mode['name']=='chunks':
                    response=web.StreamResponse();await response.prepare(request)
                    try:
                        for _ in range(129):await response.write(b'x'*65536)
                        await response.write_eof()
                    except ConnectionResetError:pass
                    return response
                if mode['name']=='drop':
                    response=web.StreamResponse(headers={'Content-Length':'100'});await response.prepare(request)
                    await response.write(b'partial');request.transport.close();return response
                return web.Response(body=data)
            app=web.Application();app.router.add_route('*','/{path:.*}',handle)
            runner=web.AppRunner(app,access_log=None);await runner.setup()
            tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
            await web.TCPSite(runner,'127.0.0.1',port,ssl_context=tls).start()
            async def run(url=None):
                env={'PATH':'/usr/bin:/bin','HOME':str(root),'LANG':'C.UTF-8','BUZZ_PRIVATE_KEY':scalar,'BUZZ_RELAY_URL':origin,
                    'BUZZ_TIMEOUT_SECS':'2','BUZZ_CONNECT_TIMEOUT_SECS':'2','SSL_CERT_FILE':str(root/'ca.pem'),'TOKIO_WORKER_THREADS':'2'}
                process=await asyncio.create_subprocess_exec(str(cli),'media','get','-o','-',url or origin+'/media/'+sha+'.bin',
                    stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
                try:out,err=await asyncio.wait_for(process.communicate(),20)
                finally:
                    if process.returncode is None:process.kill();await process.wait()
                assert scalar.encode() not in out+err
                return process.returncode,out,err
            try:
                code,out,err=await run();assert code==0 and out==data and not err,(code,len(out),err)
                cases.append('actual_native_Blossom_kind24242_SDK_signature_and_GET_expiry_server_identity_verified_over_real_TLS_preserve_binary_bytes_without_private_key_on_wire')
                mode['name']='redirect';code,out,err=await run();assert code!=0 and not out and not escapes
                cases.append('actual_private_media_GET_refuses_redirect_without_forwarding_Blossom_authentication')
                for name in ['header','chunks']:
                    mode['name']=name;before=len(calls);code,out,err=await run()
                    assert code==4 and not out and json.loads(err)['message']=='media_response_limit',(code,len(out),err)
                    assert len(calls)==before+1
                cases.append('actual_native_binary_media_reader_refuses_oversized_declared_and_chunked_bodies_before_stdout_or_unbounded_allocation')
                mode['name']='auth';before=len(calls);code,out,err=await run()
                assert code==3 and not out and len(calls)==before+1
                assert json.loads(err)['message']=='relay error 401: authentication refused'
                cases.append('definite_media_401_is_refused_before_opaque_body_parsing_without_retry_or_binary_fallback')
                mode['name']='rate';before=len(calls);code,out,err=await run()
                assert code==2 and not out and len(calls)==before+3 and json.loads(err)['message'].startswith('relay error 429:')
                cases.append('actual_native_read_only_429_retry_budget_is_exactly_three_Blossom_authenticated_GETs')
                mode['name']='drop';before=len(calls);code,out,err=await run()
                assert code==2 and not out and len(calls)==before+3
                cases.append('partial_media_body_disconnect_has_three_bounded_native_read_retries_and_never_returns_partial_binary_content')
                before=len(calls)
                for url in ['https://elsewhere.fixture.invalid/media/'+sha+'.bin',origin+'/admin/export']:
                    code,out,err=await run(url);assert code==1 and not out and len(calls)==before
                cases.append('actual_native_media_target_validator_refuses_foreign_origins_and_non_media_paths_before_HTTP_or_authentication')
            finally:await runner.cleanup()
        asyncio.run(exercise())
    Path(sys.argv[4]).write_text(json.dumps({'passed':len(cases),'cases':cases,'cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest(),
        'scope':'actual compiled pinned official CLI and signature verifier, local trusted fixture CA and TLS relay',
        'gateway_UID_original_admission_media_cache_ASR_controller_GUI_live_or_public_activation':False},indent=2)+'\n')
    print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
