"""Actual native NIP-42 and guarded WSS receive under the installed gateway UID."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_BUZZ_SOCKET_PROCESS')!='1' or Path('/usr/lib/haos').exists()
            or not os.statvfs('/repo').f_flag&os.ST_RDONLY):raise PermissionError('fresh explicit offline Buzz WSS namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755);installer='/repo/linux/haos/runtime/install_package.py'
    subprocess.run([sys.executable,installer,'/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,installer,'/deps','/sdk'],check=True)
    prepared=Path('/repo/upstream/hermes-agent')
    assert (prepared/'.herald-os-upstream-sha').read_text().strip()=='f97608f178d1ffeca59860195ab7da295f7c8e5f'
    staged=Path(tempfile.mkdtemp(prefix='haos-buzz-public-source-'))
    shutil.copytree(prepared,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,installer,str(staged),str(code/'hermes-source')],check=True)
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    with Path('/etc/group').open('a') as stream:stream.write('haos-gateway:x:65534:\n')
    target=code/'buzz';target.mkdir(mode=0o755);provenance=json.loads(Path('/public-build/source.json').read_text())
    for name in ['buzz','haos-buzz-verify']:
        shutil.copyfile('/public-bin/'+name,target/name);(target/name).chmod(0o755)
        provenance['programs'][name]['sha256']=hashlib.sha256((target/name).read_bytes()).hexdigest()
    (target/'source.json').write_text(json.dumps(provenance));(target/'source.json').chmod(0o644)
    sys.path[:0]=[str(code),str(code/'hermes-source'),'/sdk','/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    from plugins.platforms.buzz import nostr_auth
    from haos.gateway_buzz import scope
    scalar=format(1,'064x');peer_scalar=format(2,'064x');public=nostr_auth.public_key_hex(scalar);peer=nostr_auth.public_key_hex(peer_scalar)
    root=Path(tempfile.mkdtemp(prefix='haos-buzz-wss-'));root.chmod(0o755);create(root,'buzz.fixture.invalid')
    with socket.socket() as chosen:chosen.bind(('127.0.0.1',0));port=chosen.getsockname()[1]
    channel='01234567-89ab-4cde-8012-3456789abcde'
    value={'private_key':scalar,'public_key':public,'relay_url':'https://localhost:'+str(port),'channels':[channel]}
    grant={'id':'owner','connector':'buzz','sender':peer,'chat':channel,'scope':scope(value),'thread':'','identity':'personal',
        'capabilities':['create','read'],'generation':'a'*64,'since':(int(time.time())-10)*1000,'require_mention':True}
    config={'version':1,'connectors':[{'id':'buzz','platform':'buzz'}],'bindings':[grant]}
    etc=Path('/etc/haos');etc.mkdir(mode=0o755)
    def publish(config):
        path=etc/'next-policy';path.write_text(json.dumps(config));path.chmod(0o640);os.chown(path,0,65534);path.replace(etc/'gateways.json')
    publish(config)
    private=Path('/var/lib/haos-gateway');private.mkdir(mode=0o700);os.chown(private,65534,65534)
    account=private/'account.json';account.write_text(json.dumps(value));account.chmod(0o600);os.chown(account,65534,65534)
    script=root/'worker.py';script.write_text('''import asyncio,json,os,sys
from pathlib import Path
from types import MethodType
from haos.gateway_runtime import require_runtime_identity,prepare_runtime_home
require_runtime_identity();prepare_runtime_home()
from haos.gateway import digest
from haos.gateway_buzz import PreparedBuzzPolicy,scope
from haos.gateway_buzz_crypto import verify
from haos.gateway_buzz_socket import Transport
from haos.gateway_buzz_cache import RawEvents
from haos.gateway_buzz_admission import Refused
from haos.gateway_raw import NativeInbox
from haos.gateway_relay import RelayInbox
from haos.redaction import Redactor
from haos.sandbox import trusted_json
from haos.gateway_ingress import durable_adapter
from gateway.config import PlatformConfig
from plugins.platforms.buzz.adapter import BuzzAdapter
value=json.loads(Path('/var/lib/haos-gateway/account.json').read_text());snapshot=trusted_json(Path('/etc/haos/gateways.json'));initial=digest(snapshot)
def current():
    raw=trusted_json(Path('/etc/haos/gateways.json'))
    if digest(raw)!=initial:raise PermissionError('fixture actual root publication withdrawn')
    return PreparedBuzzPolicy(raw)
captured=[];received=[];cli_outcomes=[];proofs={}
redactor=Redactor([value['private_key']]);base=Path('/var/lib/haos-gateway')
originals=RawEvents(base/'originals.db',redactor,current)
inbox=NativeInbox(base/'native.db',redactor);relay=RelayInbox(base/'relay.db',redactor)
async def capture(channel,event):
    try:proof=await originals.capture(current(),'buzz',value,json.dumps(event,separators=(',',':')).encode())
    except Refused:return False
    assert proof['envelope']['chat']==channel
    current();captured.append(event['id']);proofs[event['id']]=proof;return True
adapter=durable_adapter(BuzzAdapter(PlatformConfig(enabled=True,extra={'relay_url':value['relay_url'],'channels':value['channels'],'require_mention':False,'cli_path':'/usr/lib/haos/buzz/buzz'})))
assert callable(getattr(BuzzAdapter,'_open_websocket',None))
native_cli=adapter._run_cli
async def observed_cli(args,**kwargs):
    result=await native_cli(args,**kwargs)
    try:error=json.loads(result[2]).get('error')
    except (ValueError,AttributeError):error='non-json'
    cli_outcomes.append({'code':result[0],'error_kind':error})
    return result
adapter._run_cli=observed_cli
adapter._private_key=value['private_key'];adapter._self_pubkey=value['public_key'];adapter._auth_tag=''
adapter._channel_state={value['channels'][0]:adapter._new_channel_state('group')}
adapter._allowed_pubkeys={row['sender'] for row in current().bindings.values()}
def receive(event):
    assert event.message_id in captured and event.raw_message['id']==event.message_id
    assert event.source.chat_id==value['channels'][0] and event.source.user_id in adapter._allowed_pubkeys
    assert event.source.user_name=='Peer Fixture',{'observed_name':event.source.user_name,'CLI_outcomes':cli_outcomes}
    proof=proofs[event.message_id];current().current_binding(proof)
    key=inbox.admit(current(),'buzz',proof['envelope'],{'raw_id':proof['id']},received_at=proof['received_at'])
    assert key==proof['source_key']
    state=inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]
    if state!='committed':
        assert inbox.claim(key,current()) is not None
        actual_parent_receipt=relay.admit(current(),'buzz',proof['envelope'])
        assert isinstance(actual_parent_receipt,str) and len(actual_parent_receipt)==64
        inbox.complete(key,True)
    originals.admitted(proof['id'],key)
    received.append(event.message_id);return True
adapter.set_durable_message_handler(receive);adapter.set_message_handler(receive)
async def no_reaction(*args,**kwargs):return False
adapter.send_reaction=no_reaction
transport=Transport(value,current,capture);adapter._open_websocket=transport.open
async def exercise():
    try:
        if sys.argv[1]=='storage':
            import sqlite3
            from haos.gateway import Conflict
            fixture=json.loads(Path(sys.argv[2]).read_text());count=originals.db.execute('SELECT COUNT(*) FROM buzz_raw_events').fetchone()[0]
            proof=await originals.capture(current(),'buzz',value,json.dumps(fixture['original']).encode())
            same=await originals.capture(current(),'buzz',value,json.dumps(fixture['alternate']).encode())
            assert same==proof and json.loads(same['raw'])['sig']==fixture['original']['sig']
            for item in fixture['negatives']:
                try:await originals.capture(current(),'buzz',value,json.dumps(item['event']).encode())
                except Refused as error:assert error.reason==item['reason']
                except PermissionError:assert item['reason']=='signature'
                else:raise AssertionError('invalid or unapproved signed source entered custody')
                assert originals.db.execute('SELECT COUNT(*) FROM buzz_raw_events').fetchone()[0]==count
            next_raw=json.dumps(fixture['receipt_failure']).encode();next_proof=await originals.capture(current(),'buzz',value,next_raw)
            key=inbox.admit(current(),'buzz',next_proof['envelope'],{'raw_id':next_proof['id']},received_at=next_proof['received_at'])
            assert inbox.claim(key,current()) is not None
            relay.admit(current(),'buzz',next_proof['envelope']);inbox.complete(key,True)
            originals.db.execute("CREATE TRIGGER failed_buzz_receipt BEFORE UPDATE ON buzz_raw_events BEGIN SELECT RAISE(ABORT,'fixture receipt failure'); END")
            try:originals.admitted(next_proof['id'],key)
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('fixture receipt failure did not execute')
            assert originals.db.execute('SELECT admitted_receipt FROM buzz_raw_events WHERE id=?',(next_proof['id'],)).fetchone()[0]==''
            originals.db.execute('DROP TRIGGER failed_buzz_receipt')
            originals.close();inbox.close();relay.close()
            reopened=RawEvents(base/'originals.db',redactor,current);new_inbox=NativeInbox(base/'native.db',redactor);new_relay=RelayInbox(base/'relay.db',redactor)
            try:
                recovered=await reopened.capture(current(),'buzz',value,next_raw);assert recovered==next_proof
                same_key=new_inbox.admit(current(),'buzz',recovered['envelope'],{'raw_id':recovered['id']},received_at=recovered['received_at'])
                assert same_key==key and new_inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='committed'
                reopened.admitted(recovered['id'],key)
                assert reopened.db.execute('SELECT COUNT(*) FROM buzz_raw_events').fetchone()[0]==2
                assert new_inbox.db.execute("SELECT COUNT(*) FROM native_inbox WHERE state='committed'").fetchone()[0]==2
                assert new_relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
                data=reopened.db.execute('SELECT data FROM buzz_raw_events WHERE id=?',(recovered['id'],)).fetchone()[0]
                reopened.db.execute('UPDATE buzz_raw_events SET data=? WHERE id=?',(bytes(data)+b'tampered',recovered['id']))
                try:await reopened.get(current(),'buzz',value,recovered['id'])
                except Conflict:pass
                else:raise AssertionError('changed retained original was restored or silently trusted')
                reopened.db.execute('UPDATE buzz_raw_events SET data=? WHERE id=?',(data,recovered['id']))
            finally:reopened.close();new_inbox.close();new_relay.close()
            print(json.dumps({'storage_verified':True,'negative_cases':len(fixture['negatives'])}),flush=True);return
        async with adapter._open_websocket(open_timeout=20,close_timeout=5,ping_interval=20,ping_timeout=20,max_size=2000000,happy_eyeballs_delay=.25) as connection:
            await adapter._authenticate_websocket(connection)
            subscriptions=await adapter._subscribe_websocket(connection)
            print(json.dumps({'ready':True,'uid':os.geteuid()}),flush=True)
            if sys.argv[1]=='receive':
                while len(received)<1:
                    raw=await connection.recv();await adapter._handle_ws_message(connection,subscriptions,json.loads(raw))
                # The duplicate is filtered by the actual native event path.
                raw=await connection.recv();await adapter._handle_ws_message(connection,subscriptions,json.loads(raw))
                assert len(received)==1
                print(json.dumps({'received':received,'captured':captured,'raw_count':originals.db.execute('SELECT COUNT(*) FROM buzz_raw_events').fetchone()[0],
                    'native_count':inbox.db.execute("SELECT COUNT(*) FROM native_inbox WHERE state='committed'").fetchone()[0],
                    'relay_count':relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]}),flush=True)
            elif sys.argv[1]=='unapproved':
                try:await connection.send(json.dumps(['REQ','escape',{'kinds':[9],'#h':['11234567-89ab-4cde-8012-3456789abcde']}]))
                except PermissionError:print(json.dumps({'unapproved_subscription_refused':True}),flush=True)
                else:raise AssertionError('unapproved channel subscription escaped')
            elif sys.argv[1]=='withdraw':
                await asyncio.to_thread(sys.stdin.readline)
                try:await connection.send(json.dumps(['REQ','after-withdraw',{'kinds':[9],'#h':value['channels']}]))
                except PermissionError:print(json.dumps({'withdrawal_refused':True}),flush=True)
                else:raise AssertionError('withdrawn owner publication reused socket')
    finally:
        await transport.close();originals.close();inbox.close();relay.close()
try:asyncio.run(exercise())
except PermissionError as error:
    if sys.argv[1]=='receive':
        import traceback
        print(json.dumps({'transport_refused':True,'sites':[[frame.name,frame.lineno] for frame in traceback.extract_tb(error.__traceback__)]}),flush=True)
    else:print(json.dumps({'transport_refused':True}),flush=True)
''');script.chmod(0o644)
    def signed(author,content,kind=9,*,tags=None,created_at=None):
        pub=nostr_auth.public_key_hex(author);event={'pubkey':pub,'created_at':int(time.time()) if created_at is None else created_at,'kind':kind,
            'tags':([['h',channel],['p',public]] if kind==9 else []) if tags is None else tags,'content':content}
        event['id']=hashlib.sha256(json.dumps([0,pub,event['created_at'],kind,event['tags'],content],separators=(',',':')).encode()).hexdigest()
        event['sig']=nostr_auth.schnorr_sign(bytes.fromhex(event['id']),author).hex();return event
    event=signed(peer_scalar,'Native local socket message');unknown=signed(format(3,'064x'),'Unapproved local sender')
    alternate={**event,'sig':nostr_auth.schnorr_sign(bytes.fromhex(event['id']),peer_scalar,auxiliary_randomness=bytes(32)).hex()}
    negatives=[{'event':{**event,'sig':'f'*128},'reason':'signature'},
        {'event':signed(peer_scalar,'stale signed source',created_at=int(time.time())-30),'reason':'invalid-time'},
        {'event':signed(peer_scalar,'future signed source',created_at=int(time.time())+3600),'reason':'invalid-time'},
        {'event':signed(peer_scalar,'unmentioned source',tags=[['h',channel]]),'reason':'mention-required'},
        {'event':signed(peer_scalar,'unapproved thread',tags=[['h',channel],['p',public],['e','f'*64,'','root']]),'reason':'unapproved-route'},
        {'event':signed(peer_scalar,scalar),'reason':'private-reflection'},
        {'event':signed(peer_scalar,'ambiguous roots',tags=[['h',channel],['p',public],['e','f'*64,'','root'],['e','e'*64,'','root']]),'reason':'unsupported-content'},
        {'event':signed(peer_scalar,'unapproved voice',tags=[['h',channel],['p',public],['imeta','url '+value['relay_url']+'/media/'+('a'*64)+'.flac','x '+('a'*64),'size 4','m audio/flac','filename voice.flac']]),'reason':'independent-media-consent-required'}]
    fixture=root/'signed-inputs.json';fixture.write_text(json.dumps({'original':event,'alternate':alternate,'negatives':negatives,
        'receipt_failure':signed(peer_scalar,'Local receipt recovery source')}));fixture.chmod(0o644)
    profile=signed(peer_scalar,json.dumps({'display_name':'Peer Fixture'}),0)
    cases=[]
    async def exercise():
        from aiohttp import web
        mode={'name':'receive'};auths=[];subscriptions=[];escapes=[];active=[]
        def verified(event):
            result=subprocess.run([str(target/'haos-buzz-verify')],input=json.dumps(event),text=True,capture_output=True,timeout=5)
            assert result.returncode==0 and json.loads(result.stdout)['valid'] is True
        async def handle(request):
            if request.path=='/query':
                body=await request.read();header=request.headers['Authorization'];assert header.startswith('Nostr ')
                auth=json.loads(base64.b64decode(header[6:],validate=True));verified(auth)
                tags={tag[0]:tag[1] for tag in auth['tags'] if len(tag)==2}
                assert auth['kind']==27235 and auth['pubkey']==public and tags['u']==value['relay_url']+'/query'
                assert tags['method']=='POST' and tags['payload']==hashlib.sha256(body).hexdigest()
                assert json.loads(body)==[{'kinds':[0],'authors':[peer],'limit':1}]
                return web.json_response([profile])
            if request.path=='/escape':escapes.append(True);return web.Response()
            if mode['name']=='redirect':return web.Response(status=302,headers={'Location':value['relay_url']+'/escape'})
            socket=web.WebSocketResponse();await socket.prepare(request);active.append(socket)
            await socket.send_json(['AUTH','fixed-local-challenge'])
            auth=(await socket.receive_json());assert auth[0]=='AUTH';verified(auth[1]);auths.append(auth[1]['id'])
            assert auth[1]['pubkey']==public and auth[1]['kind']==22242
            assert auth[1]['tags']==[['relay','wss'+value['relay_url'][5:]],['challenge','fixed-local-challenge']]
            await socket.send_json(['OK',auth[1]['id'],mode['name']!='auth-refuse','local fixture'])
            if mode['name']=='auth-refuse':await socket.close();return socket
            first=await socket.receive_json();second=await socket.receive_json();subscriptions.extend([first,second])
            assert first[0]=='REQ' and first[2]['#h']==[channel] and second[2]['#p']==[public]
            if mode['name']=='receive':
                await socket.send_json(['EVENT',first[1],unknown]);await socket.send_json(['EVENT',first[1],event]);await socket.send_json(['EVENT',first[1],event])
            async for message in socket:
                if message.type==web.WSMsgType.TEXT:subscriptions.append(json.loads(message.data))
            return socket
        app=web.Application();app.router.add_route('*','/{path:.*}',handle);runner=web.AppRunner(app,access_log=None);await runner.setup()
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        await web.TCPSite(runner,'127.0.0.1',port,ssl_context=tls).start()
        async def line(process):
            value=await asyncio.wait_for(asyncio.to_thread(process.stdout.readline),15)
            if not value:raise AssertionError(process.stderr.read())
            return json.loads(value)
        def spawn(name):
            return subprocess.Popen([sys.executable,str(script),name,str(root/'signed-inputs.json')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                text=True,user=65534,group=65534,extra_groups=[],cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
                    'PYTHONPATH':str(code)+':'+str(code/'hermes-source')+':/sdk','SSL_CERT_FILE':str(root/'ca.pem'),'HERMES_SAFE_MODE':'1'})
        async def done(process):
            await asyncio.wait_for(asyncio.to_thread(process.wait),15);error=process.stderr.read()
            assert process.returncode==0,error
            assert scalar not in error and peer_scalar not in error
        try:
            process=spawn('receive');assert await line(process)=={'ready':True,'uid':65534}
            result=await line(process);assert result=={'received':[event['id']],'captured':[event['id'],event['id']],'raw_count':1,'native_count':1,'relay_count':1},result
            await done(process)
            cases.append('actual_installed_private_UID_native_NIP42_signing_and_guarded_verified_WSS_authenticate_exact_identity_relay_and_challenge_without_private_key_on_wire')
            cases.append('actual_native_subscription_and_MessageEvent_path_deliver_only_explicit_signed_peer_and_channel_after_signature_capture_and_native_duplicate_filter')
            process=spawn('receive');assert await line(process)=={'ready':True,'uid':65534}
            reopened=await line(process);assert reopened==result,reopened;await done(process)
            cases.append('actual_private_FULL_original_native_inbox_and_parent_relay_reopen_preserve_first_signed_source_and_never_duplicate_local_admission_on_native_replay')
            process=spawn('storage');assert await line(process)=={'storage_verified':True,'negative_cases':8};await done(process)
            cases.append('actual_private_original_custody_refuses_invalid_signature_time_mention_thread_private_key_reflection_and_unapproved_voice_before_new_inbox_or_media_use')
            cases.append('Nostr_signature_randomness_replay_keeps_first_valid_original_without_new_semantic_message_or_local_admission')
            cases.append('actual_SQL_receipt_failure_after_native_and_parent_commit_reopens_and_reconciles_without_new_local_delivery_or_fake_mission')
            cases.append('changed_retained_original_bytes_are_refused_without_automatic_restoration_or_discarding_source_tombstone')
            mode['name']='unapproved';before=len(subscriptions);process=spawn('unapproved');assert (await line(process))['ready'] is True
            assert await line(process)=={'unapproved_subscription_refused':True};await done(process)
            assert len(subscriptions)==before+2
            cases.append('actual_private_socket_refuses_unapproved_channel_before_any_subscription_frame_reaches_relay')
            mode['name']='redirect';before=len(auths);process=spawn('redirect');assert await line(process)=={'transport_refused':True};await done(process)
            assert not escapes and len(auths)==before
            cases.append('actual_verified_TLS_WebSocket_302_is_not_followed_and_never_receives_native_authentication')
            mode['name']='auth-refuse';process=spawn('auth-refuse');assert await line(process)=={'transport_refused':True};await done(process)
            cases.append('actual_relay_AUTH_refusal_produces_no_subscription_or_native_message_readiness')
            mode['name']='withdraw';process=spawn('withdraw');assert (await line(process))['ready'] is True
            before=len(subscriptions);publish({**config,'bindings':[]});process.stdin.write('withdrawn\n');process.stdin.flush()
            assert await line(process)=={'withdrawal_refused':True};await done(process)
            assert len(subscriptions)==before
            cases.append('actual_root_owned_policy_replacement_prevents_further_use_of_existing_authenticated_socket')
        finally:
            for connection in active:await connection.close()
            await runner.cleanup()
    asyncio.run(exercise())
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_UID_TLS_native_auth_subscription_and_MessageEvent':True,
        'actual_FULL_original_native_inbox_and_parent_relay_custody':True,
        'persistent_profile_history_controller_mission_media_delivery_GUI_or_public_activation':False},indent=2))


if __name__=='__main__':main()
