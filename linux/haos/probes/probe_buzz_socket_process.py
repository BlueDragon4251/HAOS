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
    model=Path('/var/lib/haos-speech-models/buzz-fixture');model.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    shutil.copytree('/public-model',model)
    model.chmod(0o755)
    for path in model.rglob('*'):path.chmod(0o755 if path.is_dir() else 0o644)
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    with Path('/etc/group').open('a') as stream:stream.write('haos-gateway:x:65534:\n')
    target=code/'buzz';target.mkdir(mode=0o755);provenance=json.loads(Path('/public-build/source.json').read_text())
    for name in ['buzz','haos-buzz-verify']:
        shutil.copyfile('/public-bin/'+name,target/name);(target/name).chmod(0o755)
        provenance['programs'][name]['sha256']=hashlib.sha256((target/name).read_bytes()).hexdigest()
    (target/'source.json').write_text(json.dumps(provenance));(target/'source.json').chmod(0o644)
    sys.path[:0]=[str(code),str(code/'hermes-source'),'/sdk','/repo/linux/haos/runtime']
    guard='''import asyncio
from haos.gateway_buzz_profile import build
from haos.gateway_buzz_send_process import send
for action in [lambda:build(None,parent=None,connector=None,policy=None,inbox=None),
    lambda:asyncio.run(send(None,None,home=None,current=None,retain=None,redactor=None))]:
    try:action()
    except PermissionError:print('refused-before-optional-SDK')
    else:raise AssertionError('foreign UID entered private Buzz profile or sender')
'''
    for uid,gid,groups in [(0,0,[]),(65533,65533,[]),(65534,65534,[0])]:
        result=subprocess.run([sys.executable,'-c',guard],user=uid,group=gid,extra_groups=groups,
            env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(code)},capture_output=True,text=True,timeout=5)
        assert result.returncode==0 and result.stdout=='refused-before-optional-SDK\n'*2 and not result.stderr
    from webhook_tls_fixture import create
    from plugins.platforms.buzz import nostr_auth
    from haos.gateway_buzz import scope
    scalar=format(1,'064x');peer_scalar=format(2,'064x');public=nostr_auth.public_key_hex(scalar);peer=nostr_auth.public_key_hex(peer_scalar)
    root=Path(tempfile.mkdtemp(prefix='haos-buzz-wss-'));root.chmod(0o755);create(root,'buzz.fixture.invalid')
    # Only this disposable namespace trusts the local TLS CA. The production
    # runner always uses the root-owned installed system bundle, never env CA.
    with Path('/etc/ssl/certs/ca-certificates.crt').open('ab') as stream:stream.write((root/'ca.pem').read_bytes())
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
from types import MethodType,SimpleNamespace
from haos.gateway_runtime import require_runtime_identity,prepare_runtime_home
require_runtime_identity();prepare_runtime_home()
from haos.gateway import digest,Conflict
from haos.gateway_buzz import PreparedBuzzPolicy,scope
from haos.gateway_buzz_crypto import verify
from haos.gateway_buzz_cli import Reader,QueryFailed
from haos.gateway_buzz_history import History
from haos.gateway_buzz_ingress import install as install_ingress,capture as capture_ingress,dispatch_stored
from haos.gateway_buzz_profile import build as build_profile
from haos.gateway_buzz_send_process import send as private_send
from haos.gateway_buzz_recovery import outgoing as inspect_outgoing,approve_retry
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
reader=Reader('buzz',value,current,redactor)
native_cli=reader.run
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
        if sys.argv[1].startswith('media'):
            fixture=json.loads(Path(sys.argv[2]).read_text())
            profiles=base/'media-profiles';profiles.mkdir(mode=0o700,exist_ok=True)
            local=NativeInbox(base/'media-native.db',redactor);parent=RelayInbox(base/'media-parent.db',redactor)
            profile=build_profile(value,parent=profiles,connector='buzz',policy=current,inbox=local)
            from haos.gateway_media_relay import MediaCache,event_media
            from haos.gateway_runtime import adapter_envelope
            cache=MediaCache(local);accepted=[]
            def admit(event):
                envelope=adapter_envelope(event,'buzz');ids=event_media(event,'buzz')
                assert event.raw_message is None and ids and len(ids)==len(set(ids))
                rows=[cache.get(current(),identity) for identity in ids]
                assert all(row['envelope_digest']==digest(envelope) for row in rows)
                parent.admit(current(),'buzz',envelope,media=ids)
                accepted.append({'goal':event.text,'type':event.message_type.value,'kinds':[row['descriptor']['kind'] for row in rows]});return True
            profile.set_durable_message_handler(admit);profile.set_message_handler(admit)
            try:
                # This media component fixture drives the real installed native
                # decoder directly. The full connection/replay lifecycle is
                # separately exercised below, without substituting UID or I/O.
                profile._display_name='Own Fixture'
                name='media-cache-fail' if sys.argv[1]=='media-cache-recover' else 'media-cache-damage' if sys.argv[1]=='media-cache-damage-replay' else sys.argv[1]
                selected=fixture[name]
                if name=='media-unapproved':
                    assert await capture_ingress(profile,value['channels'][0],selected) is False
                    print(json.dumps({'capture_refused':True}),flush=True);return
                assert await capture_ingress(profile,value['channels'][0],selected)
                proof=await profile._haos_buzz_raw.capture(current(),'buzz',value,json.dumps(selected).encode());key=proof['source_key']
                if name=='media-cache-fail' and sys.argv[1]!='media-cache-recover':
                    local.db.execute("CREATE TRIGGER fail_media_blob BEFORE INSERT ON native_media_cache BEGIN SELECT RAISE(ABORT,'fixture first blob failure'); END")
                if sys.argv[1]=='media-cache-damage':
                    parent.db.execute("CREATE TRIGGER fail_media_parent BEFORE INSERT ON inbox BEGIN SELECT RAISE(ABORT,'fixture parent admission failure'); END")
                if sys.argv[1]=='media-cache-damage-replay':
                    identity=local.db.execute('SELECT upload_id FROM buzz_input_media WHERE input_id=?',(key,)).fetchone()[0]
                    blob=bytearray(local.db.execute('SELECT data FROM native_media_cache WHERE id=?',(identity,)).fetchone()[0]);blob[-1]^=1
                    local.db.execute('UPDATE native_media_cache SET data=? WHERE id=?',(bytes(blob),identity))
                try:result=await dispatch_stored(profile,key)
                except Refused as error:
                    assert name in {'media-badsha','media-command','media-voice-masked-denied'}
                    expected='resource-integrity-refused' if name=='media-badsha' else 'media-command-refused' if name=='media-command' else 'independent-decoded-media-consent-required'
                    assert error.reason==expected
                    print(json.dumps({'refused':expected}),flush=True);return
                except Conflict:
                    assert sys.argv[1]=='media-cache-damage-replay'
                    print(json.dumps({'damaged_cache_refused':True}),flush=True);return
                except Exception as error:
                    import sqlite3
                    assert isinstance(error,sqlite3.IntegrityError)
                    if sys.argv[1]=='media-cache-damage':
                        parent.db.execute('DROP TRIGGER fail_media_parent')
                        print(json.dumps({'cache_precedes_parent':True}),flush=True);return
                    assert name=='media-cache-fail' and sys.argv[1]!='media-cache-recover'
                    assert local.db.execute('SELECT COUNT(*) FROM buzz_input_media WHERE input_id=?',(key,)).fetchone()[0]==1
                    local.db.execute('DROP TRIGGER fail_media_blob')
                    print(json.dumps({'receipt_precedes_blob':True}),flush=True);return
                assert result and accepted and len(accepted)==1
                before=local.db.execute('SELECT COUNT(*) FROM native_media_cache').fetchone()[0]
                assert await dispatch_stored(profile,key) and len(accepted)==1
                assert local.db.execute('SELECT COUNT(*) FROM native_media_cache').fetchone()[0]==before
                if sys.argv[1]=='media-voice':
                    from haos.store import MissionStore
                    from haos.controller import Controller
                    from haos import speech,speech_client
                    from haos.gateway_media_relay import forward
                    from websockets.asyncio.server import serve
                    store=MissionStore(base/'buzz-voice-controller.db');controller=Controller(store,'unused',set());controller.gateway_policy=current
                    saved=speech_client.transcribe;asr=[];methods=[];prompts=[]
                    async def local_engine(data,current):
                        current();asr.append(len(data))
                        result=await asyncio.to_thread(speech.transcribe,data,model_root=Path('/var/lib/haos-speech-models/buzz-fixture'),model_owner_uid=0)
                        current();return result
                    speech_client.transcribe=local_engine
                    async def terminal(connection):
                        async for raw in connection:
                            request=json.loads(raw);method=request['method'];methods.append(method)
                            if method=='session.create':result={'session_id':'buzz-voice','stored_session_id':'buzz-voice-durable'}
                            elif method=='prompt.submit':
                                text=request['params']['text'];assert 'ask not what your country can do for you' in text.lower()
                                assert '@file:' not in text and 'data:' not in text and value['relay_url'] not in text
                                prompts.append(text);result={'status':'streaming'}
                            else:raise AssertionError('raw Buzz voice reached agent RPC')
                            await connection.send(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}))
                            if method=='prompt.submit':await connection.send(json.dumps({'method':'event','params':{'type':'message.complete','session_id':'buzz-voice',
                                'payload':{'status':'complete','text':'Protocol terminal fixture, no inference'}}}))
                    try:
                        pending=parent.db.execute("SELECT * FROM inbox WHERE json_extract(envelope,'$.message_id')=?",(selected['id'],)).fetchone()
                        envelope=json.loads(pending['envelope']);ids=json.loads(pending['media'])
                        async def call(method,params):return await controller.gateway_dispatch({'method':method,'params':params})
                        admitted=await forward(current,'buzz',envelope,ids,cache,call);mid=admitted['mission_id']
                        parent.admitted(pending['id'],mid);cache.transferred(ids)
                        async with serve(terminal,'127.0.0.1',0) as endpoint:
                            controller.url='ws://127.0.0.1:'+str(endpoint.sockets[0].getsockname()[1]);mission=store.claim();assert mission['id']==mid
                            await asyncio.wait_for(controller.execute(mission),30)
                        assert store.get(mid)['state']=='completed' and len(asr)==1 and len(prompts)==1 and methods==['session.create','prompt.submit']
                        transcript=controller.gateway.media.transcript(current(),mid,ids[0])
                        assert 'ask what you can do for your country' in transcript['transcript'].lower()
                        assert await dispatch_stored(profile,key) and len(asr)==1 and len(store.list())==1
                    finally:speech_client.transcribe=saved;store.close()
                print(json.dumps({'media_admitted':accepted[0],'resource_count':len(proof['resources']),'same_source_replay':True,
                    'actual_local_ASR':sys.argv[1]=='media-voice'}),flush=True)
            finally:await profile.close_profile();local.close();parent.close()
            return
        if sys.argv[1].startswith('outbox'):
            profiles=base/'outbox-profiles';profiles.mkdir(mode=0o700,exist_ok=True)
            local=NativeInbox(base/'outbox-native.db',redactor);parent=RelayInbox(base/'outbox-parent.db',redactor)
            profile=None
            def build():
                result=build_profile(value,parent=profiles,connector='buzz',policy=current,inbox=local)
                from haos.gateway_runtime import adapter_envelope
                def admit(event):parent.admit(current(),'buzz',adapter_envelope(event,'buzz'));return True
                result.set_durable_message_handler(admit);result.set_message_handler(admit);return result
            source=json.loads(Path(sys.argv[2]).read_text())['original']['id']
            case='outbox-receipt-fail' if sys.argv[1] in {'outbox-receipt-fail','outbox-receipt-reopen','outbox-owner-retry'} else sys.argv[1]
            delivery=digest(['local Buzz outbox fixture',case]);content='Private local fixture '+case
            binding=current().bindings['owner']
            metadata={'haos_binding':{'binding_id':binding['id'],'binding_digest':digest(binding)},'haos_scope':scope(value),
                'thread_id':'','haos_delivery_id':delivery,'haos_delivery_attempt':1}
            try:
                profile=build();assert await profile.connect() and profile.is_connected
                async with asyncio.timeout(20):
                    while not local.db.execute("SELECT 1 FROM native_inbox WHERE message_id=? AND state='committed'",(source,)).fetchone():await asyncio.sleep(.05)
                if sys.argv[1]=='outbox-receipt-fail':
                    local.db.execute("CREATE TRIGGER fail_outbox_receipt BEFORE UPDATE ON buzz_delivery_intents WHEN NEW.state='confirmed' BEGIN SELECT RAISE(ABORT,'fixture confirmed receipt failure'); END")
                if sys.argv[1]=='outbox-owner-retry':
                    await profile.close_profile();profile=None
                    row=next(row for row in inspect_outgoing(local) if row['delivery_id']==delivery)
                    request={'connector':'buzz','delivery_id':delivery,'attempt':1,'snapshot_sha256':row['snapshot_sha256'],
                        'owner_uid':1000,'note_sha256':digest('explicit fixture owner non-delivery inspection'),'confirmed':True,'confirmed_not_delivered':True}
                    try:approve_retry(local,current(),{**request,'snapshot_sha256':'0'*64})
                    except Conflict:pass
                    else:raise AssertionError('stale owner inspection authorized retry')
                    first=approve_retry(local,current(),request);assert first['signed_event_reuse_required'] is True
                    assert approve_retry(local,current(),request)==first
                    profile=build();assert await profile.connect() and profile.is_connected
                    metadata['haos_delivery_attempt']=2
                receipt=await profile.send(value['channels'][0],content,reply_to=source,metadata=metadata)
                if sys.argv[1]=='outbox-receipt-fail':local.db.execute('DROP TRIGGER fail_outbox_receipt')
                repeated=await profile.send(value['channels'][0],content,reply_to=source,metadata=metadata)
                assert repeated.success==receipt.success and repeated.message_id==receipt.message_id
                row=local.db.execute('SELECT * FROM buzz_delivery_intents WHERE delivery_id=? ORDER BY attempt DESC',(delivery,)).fetchone()
                print(json.dumps({'success':receipt.success,'state':row['state'],'event_id':row['event_id'],
                    'receipt':receipt.message_id,'attempt':row['attempt'],'actual_native_send':True}),flush=True)
            finally:
                if profile is not None:await profile.close_profile()
                local.close();parent.close()
            return
        if sys.argv[1].startswith('outgoing'):
            fixture=json.loads(Path(sys.argv[2]).read_text());source=fixture['original']
            target={'channel':value['channels'][0],'anchor':source['id'],'thread':source['id'],
                'content':'Private local fixture '+sys.argv[1],'kind':9,'allowed_mentions':[source['pubkey'],value['public_key']],'explicit_mentions':[]}
            inbox.db.execute('CREATE TABLE IF NOT EXISTS buzz_outgoing_probe(id TEXT PRIMARY KEY,data BLOB NOT NULL)')
            replay=None
            if sys.argv[1]=='outgoing-replay':
                target['content']='Private local fixture outgoing-drop'
                replay=bytes(inbox.db.execute("SELECT data FROM buzz_outgoing_probe WHERE json_extract(CAST(data AS TEXT),'$.content')=?",(target['content'],)).fetchone()[0])
            async def retained(raw,event):
                current()
                if sys.argv[1]=='outgoing-refuse':return False
                inbox.db.execute('INSERT OR IGNORE INTO buzz_outgoing_probe VALUES(?,?)',(event['id'],raw))
                assert inbox.db.execute('SELECT data FROM buzz_outgoing_probe WHERE id=?',(event['id'],)).fetchone()[0]==raw
                return True
            result=await private_send(value,target,home=base,current=current,retain=retained,redactor=redactor,replay=replay)
            print(json.dumps(result),flush=True);return
        if sys.argv[1] in {'profile','profile-auth','profile-auth-saved'}:
            profiles=base/'profiles';profiles.mkdir(mode=0o700,exist_ok=True)
            private_inbox=NativeInbox(base/'profile-native.db',redactor);private_parent=RelayInbox(base/'profile-parent.db',redactor)
            profile=build_profile(value,parent=profiles,connector='buzz',policy=current,inbox=private_inbox)
            try:
                try:build_profile(value,parent=profiles,connector='buzz',policy=current,inbox=private_inbox)
                except PermissionError:pass
                else:raise AssertionError('duplicate native identity acquired private lease')
                from haos.gateway_runtime import adapter_envelope
                def admit(event):
                    envelope=adapter_envelope(event,'buzz');assert event.raw_message is None
                    assert envelope['sender'] in reader.peers() and envelope['scope']==scope(value)
                    private_parent.admit(current(),'buzz',envelope);return True
                profile.set_durable_message_handler(admit);profile.set_message_handler(admit)
                if sys.argv[1]!='profile':
                    assert await profile.connect() is False
                    assert profile._haos_health()['status']=='authentication-refused'
                    print(json.dumps({'profile_authentication_refused':True}),flush=True);return
                assert await profile.connect(),profile._haos_health()
                assert profile.is_connected
                assert profile._haos_health()['status']=='connected-ws'
                async with asyncio.timeout(20):
                    while private_parent.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]<2:await asyncio.sleep(.05)
                original_id=json.loads(Path(sys.argv[2]).read_text())['original']['id']
                assert private_parent.db.execute("SELECT COUNT(*) FROM inbox WHERE json_extract(envelope,'$.message_id')=?",(original_id,)).fetchone()[0]==1
                print(json.dumps({'profile_ready':True,'lease_refused':True,'actual_private_UID':os.geteuid()}),flush=True)
                await asyncio.to_thread(sys.stdin.readline)
                async with asyncio.timeout(5):
                    while profile._haos_health()['status']!='revoked':await asyncio.sleep(.05)
                async with asyncio.timeout(5):
                    while profile._haos_buzz_transport.connections or profile._ws_task is not None:await asyncio.sleep(.05)
                assert profile._ws_task is None
                assert not profile.is_connected
                print(json.dumps({'profile_revoked':True,'native_socket_stopped':True}),flush=True)
            finally:await profile._haos_close();private_inbox.close();private_parent.close()
            return
        if sys.argv[1].startswith('decode'):
            import sqlite3
            from plugins.platforms.buzz.adapter import hex_to_npub
            from haos.gateway_runtime import adapter_envelope
            fixture=json.loads(Path(sys.argv[2]).read_text())
            adapter._self_npub=hex_to_npub(value['public_key'])
            adapter._display_name='Old Fixture' if sys.argv[1]=='decode-commit-fail' else 'New Fixture'
            adapter._haos_native=SimpleNamespace(connector='buzz',policy=current,inbox=inbox)
            adapter._haos_buzz_check=current;adapter._haos_buzz_value=value;adapter._haos_buzz_raw=originals
            adapter._haos_buzz_home=base;adapter._haos_buzz_environment={'HERMES_SAFE_MODE':'1'}
            install_ingress(adapter);admissions=[]
            def admit(event):
                envelope=adapter_envelope(event,'buzz');assert envelope['text']=='/status'
                assert event.raw_message is None and not event.media_urls
                admissions.append(relay.admit(current(),'buzz',envelope));return True
            adapter.set_durable_message_handler(admit)
            selected=fixture['decode_named' if sys.argv[1] in {'decode-commit-fail','decode-commit-recover'} else 'decode_public']
            assert await capture_ingress(adapter,value['channels'][0],selected)
            proof=await originals.capture(current(),'buzz',value,json.dumps(selected).encode());key=proof['source_key']
            if sys.argv[1]=='decode-receipt-fail':
                originals.db.execute("CREATE TRIGGER failed_decode_receipt BEFORE UPDATE ON buzz_raw_events BEGIN SELECT RAISE(ABORT,'fixture receipt failure'); END")
            if sys.argv[1]=='decode-commit-fail':
                inbox.db.execute("CREATE TRIGGER failed_decode_commit BEFORE UPDATE ON native_inbox WHEN NEW.state='committed' BEGIN SELECT RAISE(ABORT,'fixture native commit failure'); END")
            try:assert await dispatch_stored(adapter,key)
            except sqlite3.IntegrityError:
                assert sys.argv[1] in {'decode-receipt-fail','decode-commit-fail'}
                if sys.argv[1]=='decode-receipt-fail':originals.db.execute('DROP TRIGGER failed_decode_receipt')
                else:inbox.db.execute('DROP TRIGGER failed_decode_commit')
            state=inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]
            projection=inbox.db.execute('SELECT normalizer,text FROM buzz_native_projection WHERE source_key=?',(key,)).fetchone()
            assert projection['text']=='/status'
            if sys.argv[1]=='decode-commit-recover':assert json.loads(projection['normalizer'])['_display_name']=='Old Fixture'
            print(json.dumps({'native_state':state,'parent_count':relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0],
                'handler_calls':len(admissions),'raw_receipt':bool(originals.db.execute('SELECT admitted_receipt FROM buzz_raw_events WHERE id=?',(proof['id'],)).fetchone()[0])}),flush=True);return
        if sys.argv[1].startswith('history'):
            import sqlite3
            history=History(base/'history.db',reader,redactor,capture)
            try:
                if sys.argv[1]=='history-fail':
                    history.db.execute("CREATE TRIGGER failed_history_cursor BEFORE UPDATE ON buzz_history BEGIN SELECT RAISE(ABORT,'fixture cursor commit failure'); END")
                try:result=await history.step(value['channels'][0])
                except sqlite3.IntegrityError:
                    assert sys.argv[1]=='history-fail'
                    assert history.db.execute('SELECT revision FROM buzz_history').fetchone()[0]==0
                    history.db.execute('DROP TRIGGER failed_history_cursor')
                    result={'cursor_failed':True}
                except QueryFailed as error:
                    assert sys.argv[1]=='history-malformed' and error.category=='query_unavailable'
                    assert history.db.execute('SELECT revision FROM buzz_history').fetchone()[0]==3
                    result={'malformed_failed':True}
                result['raw_count']=originals.db.execute('SELECT COUNT(*) FROM buzz_raw_events').fetchone()[0]
                print(json.dumps(result),flush=True);return
            finally:history.close()
        if sys.argv[1].startswith('reader'):
            if sys.argv[1]=='reader':
                for args in [['messages','delete','--event','a'*64],['reactions','add','--event','a'*64],
                    ['users','get','--pubkey','f'*64],['channels','get','--channel','11234567-89ab-4cde-8012-3456789abcde'],
                    ['messages','get','--channel',value['channels'][0],'--limit','50','--limit','100']]:
                    try:await reader.run(args)
                    except PermissionError:pass
                    else:raise AssertionError('unapproved native query escaped')
                for action in ['channels','dms']:
                    result=await reader.run([action,'list']);assert len(json.loads(result[1]))==1
                result=await reader.run(['users','get']);assert json.loads(result[1])[0]['pubkey']==value['public_key']
                print(json.dumps({'reader_verified':True}),flush=True);return
            try:await reader.run(['users','get'])
            except QueryFailed as error:
                if sys.argv[1]=='reader-auth':
                    assert error.category=='authentication_refused'
                    try:await reader.run(['users','get'])
                    except QueryFailed as repeated:assert repeated.category=='authentication_refused'
                    else:raise AssertionError('refused native identity retried')
                print(json.dumps({'query_failed':error.category}),flush=True);return
            else:raise AssertionError('invalid query result accepted')
        if sys.argv[1]=='storage':
            import sqlite3
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
        'decode_public':signed(peer_scalar,'@'+public+' /status'),'decode_named':signed(peer_scalar,'@Old Fixture /status'),
        'receipt_failure':signed(peer_scalar,'Local receipt recovery source')}));fixture.chmod(0o644)
    profile=signed(peer_scalar,json.dumps({'display_name':'Peer Fixture'}),0)
    same_second=int(time.time())
    history_events=[signed(peer_scalar,'Same-second fixture history '+str(index),created_at=same_second) for index in range(121)]
    cases=['actual_root_agent_UID_and_gateway_with_supplementary_root_group_are_refused_before_optional_native_SDK_import_or_credential_parsing_in_private_profile_factory']
    async def exercise():
        from aiohttp import web
        mode={'name':'receive'};auths=[];subscriptions=[];escapes=[];active=[];queries=[];query_auth=[];outgoing=[];write_auth=[];assets={};media_gets=[];public_gets=[]
        def verified(event):
            result=subprocess.run([str(target/'haos-buzz-verify')],input=json.dumps(event),text=True,capture_output=True,timeout=5)
            assert result.returncode==0 and json.loads(result.stdout)['valid'] is True
        async def handle(request):
            if request.path.startswith('/media/'):
                assert request.method=='GET' and request.path in assets
                header=request.headers['Authorization'];assert header.startswith('Nostr ')
                encoded=header[6:];auth=json.loads(base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4)));verified(auth)
                tags={tag[0]:tag[1] for tag in auth['tags'] if len(tag)==2}
                assert auth['kind']==24242 and auth['pubkey']==public and auth['content']=='Get media'
                assert tags['t']=='get' and tags['server']=='localhost:'+str(port) and 0<int(tags['expiration'])-auth['created_at']<=60
                assert scalar not in header and not request.headers.get('Cookie')
                media_gets.append(request.path);return web.Response(body=assets[request.path])
            if request.path in {'/query','/events'}:
                body=await request.read();header=request.headers['Authorization'];assert header.startswith('Nostr ')
                auth=json.loads(base64.b64decode(header[6:],validate=True));verified(auth)
                tags={tag[0]:tag[1] for tag in auth['tags'] if len(tag)==2}
                assert auth['kind']==27235 and auth['pubkey']==public and tags['u']==value['relay_url']+request.path
                assert tags['method']=='POST' and tags['payload']==hashlib.sha256(body).hexdigest()
                if request.path=='/events':
                    import sqlite3
                    original=json.loads(body);verified(original);assert original['pubkey']==public
                    expected='outgoing-drop' if mode['name']=='outgoing-replay' else 'outbox-receipt-fail' if mode['name']=='outbox-owner-retry' else mode['name']
                    assert ['h',channel] in original['tags'] and original['content']=='Private local fixture '+expected
                    if mode['name'].startswith('outbox'):
                        with sqlite3.connect('file:'+str(private/'outbox-native.db')+'?mode=ro',uri=True) as check:
                            assert check.execute("SELECT signed_raw FROM buzz_delivery_intents WHERE event_id=? AND state='writing'",(original['id'],)).fetchone()[0]==body
                    else:
                        with sqlite3.connect('file:'+str(private/'native.db')+'?mode=ro',uri=True) as check:
                            assert check.execute('SELECT data FROM buzz_outgoing_probe WHERE id=?',(original['id'],)).fetchone()[0]==body
                    outgoing.append(body);write_auth.append(auth['id'])
                    if mode['name']=='outgoing-drop':request.transport.close();return web.Response()
                    return web.json_response({'event_id':original['id'],'accepted':True})
                selection=json.loads(body);queries.append(selection);query_auth.append(auth['id'])
                assert isinstance(selection,list) and len(selection)==1
                if selection[0].get('ids')==[event['id']]:return web.json_response([event])
                if mode['name'] in {'reader-auth','profile-auth'}:return web.json_response({'error':'not channel members '+scalar},status=401)
                if mode['name']=='reader-rate':return web.json_response({'error':'rate limited fixture'},status=429)
                if mode['name']=='reader-reflect':return web.json_response([signed(scalar,json.dumps({'display_name':scalar}),0)])
                if mode['name']=='reader-identity':return web.json_response([profile])
                if selection[0]['kinds']==[0]:
                    assert selection[0]['authors'] in [[peer],[public]]
                    own=signed(scalar,json.dumps({'display_name':'Own Fixture'}),0)
                    return web.json_response([profile] if selection[0]['authors']==[peer] else [own])
                if selection[0]['kinds']==[9,45001,45003]:
                    filter=selection[0];assert filter['#h']==[channel] and filter['limit']==50
                    if mode['name']=='history-malformed':return web.Response(text='not a JSON history',content_type='application/json')
                    chosen=[event for event in history_events if filter['since']<=event['created_at']<=filter['until']
                        and (not filter.get('before_id') or event['created_at']<filter['until'] or event['id']<filter['before_id'])]
                    chosen.sort(key=lambda event:(event['created_at'],event['id']),reverse=True)
                    return web.json_response(chosen[:filter['limit']])
                kind=selection[0]['kinds'][0];assert kind in {39000,41001}
                return web.json_response([signed(peer_scalar,'',kind,tags=[['d',identity],['name','Fixture channel'],['p',public]])
                    for identity in [channel,'11234567-89ab-4cde-8012-3456789abcde']])
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
            if mode['name'] in {'receive','profile'} or mode['name'].startswith('outbox'):
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
                    'PYTHONPATH':str(code)+':'+str(code/'hermes-source')+':/sdk','SSL_CERT_FILE':str(root/'ca.pem'),'HERMES_SAFE_MODE':'1',
                    'OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
        async def done(process):
            await asyncio.wait_for(asyncio.to_thread(process.wait),15);error=process.stderr.read()
            assert process.returncode==0,error
            assert scalar not in error and peer_scalar not in error
        try:
            mode['name']='reader';before=len(queries);process=spawn('reader')
            assert await line(process)=={'reader_verified':True};await done(process);assert len(queries)==before+3
            cases.append('actual_private_UID_fixed_official_CLI_rejects_writes_unknown_peers_channels_and_duplicate_flags_before_HTTP_and_filters_native_discovery_to_owner_channels')
            for name,category in [('reader-auth','authentication_refused'),('reader-rate','rate_limited'),('reader-reflect','private_reflection'),('reader-identity','identity_mismatch')]:
                mode['name']=name;before=len(queries);process=spawn(name)
                assert await line(process)=={'query_failed':category};await done(process)
                attempts=3 if name=='reader-rate' else 1
                assert len(queries)==before+attempts
                if name=='reader-rate':
                    assert queries[-3:]==[queries[-1]]*3 and len(set(query_auth[-3:]))==3
            cases.append('actual_official_CLI_auth_refusal_is_sticky_without_retry_or_empty_history_and_reflected_private_material_or_wrong_public_identity_never_reaches_native_adapter')
            for name,expected,count in [('outgoing-ok','confirmed',1),('outgoing-refuse','not-dispatched',0),('outgoing-drop','uncertain',3)]:
                mode['name']=name;before=len(outgoing);process=spawn(name)
                result=await line(process);assert result['state']==expected,result
                assert result['error']==(None if expected=='confirmed' else 'prepublication-refused' if expected=='not-dispatched' else 'delivery-unknown')
                await done(process);assert len(outgoing)==before+count
                if count==1:assert result['receipt']==json.loads(outgoing[-1])['id']
                if count==3:assert outgoing[-3:]==[outgoing[-1]]*3 and len(set(write_auth[-3:]))==3 and result['receipt'] is None
            cases.append('actual_gateway_UID_fixed_CLI_peer_PID_SDK_verification_and_FULL_signed_original_commit_precede_HTTP_publication_and_exact_native_reply_receipt')
            cases.append('actual_private_signed_original_custody_refusal_never_publishes_and_post_ack_body_disconnect_retries_only_same_event_then_reports_uncertain_without_new_process_or_resigning')
            before=len(outgoing);previous=outgoing[-1];await asyncio.sleep(2)
            mode['name']='outgoing-replay';process=spawn('outgoing-replay');result=await line(process)
            assert result=={'state':'confirmed','receipt':json.loads(previous)['id'],'error':None};await done(process)
            assert len(outgoing)==before+1 and outgoing[-1]==previous
            cases.append('fresh_gateway_UID_process_replays_exact_retained_signed_original_through_sealed_memfd_and_actual_native_SDK_verification_without_new_timestamp_signature_or_event_identity')
            mode['name']='receive'
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
            mode['name']='history'
            process=spawn('history-fail');assert await line(process)=={'cursor_failed':True,'raw_count':52};await done(process)
            for page,expected in enumerate([{'complete':False,'events':50,'retained':50,'revision':1,'raw_count':52},
                    {'complete':False,'events':50,'retained':50,'revision':2,'raw_count':102},
                    {'complete':True,'events':21,'retained':21,'revision':3,'raw_count':123}]):
                process=spawn('history');assert await line(process)==expected;await done(process)
            cases.append('actual_UID_official_CLI_signed_query_and_FULL_history_reopen_page_121_same_second_events_without_native_50_event_truncation_or_new_source_on_replayed_page')
            cases.append('actual_SQL_history_cursor_commit_failure_after_50_verified_original_commits_keeps_revision_zero_then_reconciles_exact_page_after_process_reopen')
            mode['name']='history-malformed';process=spawn('history-malformed')
            assert await line(process)=={'malformed_failed':True,'raw_count':123};await done(process)
            cases.append('actual_native_CLI_rejects_malformed_HTTP_history_without_false_empty_list_or_completed_sweep_and_saved_cursor_remains_unchanged')
            for name,state,count in [('outbox-ok','confirmed',1),('outbox-receipt-fail','uncertain',1),('outbox-receipt-reopen','uncertain',0),('outbox-owner-retry','confirmed',1)]:
                mode['name']=name;before=len(outgoing);process=spawn(name);result=await line(process);await done(process)
                assert result['state']==state and result['success'] is (state=='confirmed'),result
                assert result['actual_native_send'] is True and len(outgoing)==before+count
                if name=='outbox-ok':assert result['receipt']==result['event_id'] and result['attempt']==1
                if name=='outbox-receipt-fail':retained_original=outgoing[-1];assert result['receipt'] is None
                if name=='outbox-receipt-reopen':assert result['event_id']==json.loads(retained_original)['id']
                if name=='outbox-owner-retry':assert result['attempt']==2 and outgoing[-1]==retained_original and result['receipt']==json.loads(retained_original)['id']
            cases.append('actual_native_BuzzAdapter_send_runs_only_behind_current_independent_source_and_outbox_authority_and_repeated_confirmed_attempt_returns_same_receipt_without_HTTP')
            cases.append('actual_SQL_acceptance_commit_failure_reopens_uncertain_and_never_automatically_republishes_or_signs_new_id_for_same_outbox_attempt')
            cases.append('stopped_private_profile_owner_inspection_rejects_stale_snapshot_then_idempotent_approved_next_attempt_replays_identical_signed_event_through_actual_native_send_and_new_UID_process')
            mode['name']='receive'
            for action,expected in [('decode-receipt-fail',{'native_state':'committed','parent_count':3,'handler_calls':1,'raw_receipt':False}),
                    ('decode-receipt-recover',{'native_state':'committed','parent_count':3,'handler_calls':0,'raw_receipt':True}),
                    ('decode-commit-fail',{'native_state':'pending','parent_count':4,'handler_calls':1,'raw_receipt':False})]:
                process=spawn(action);assert await line(process)==expected;await done(process)
            await asyncio.sleep(2.1)
            process=spawn('decode-commit-recover')
            assert await line(process)=={'native_state':'committed','parent_count':4,'handler_calls':1,'raw_receipt':True};await done(process)
            cases.append('actual_native_text_MessageEvent_and_independent_parent_relay_admit_strip_public_and_named_mentions_without_exposing_raw_original_or_creating_another_parent_receipt_on_reopen')
            cases.append('actual_SQL_native_commit_and_original_receipt_failures_reconcile_after_fresh_processes_without_duplicate_parent_admission_and_retain_first_command_projection_across_display_name_change')
            mode['name']='unapproved';before=len(subscriptions);process=spawn('unapproved');assert (await line(process))['ready'] is True
            assert await line(process)=={'unapproved_subscription_refused':True};await done(process)
            assert len(subscriptions)==before+2
            cases.append('actual_private_socket_refuses_unapproved_channel_before_any_subscription_frame_reaches_relay')
            mode['name']='redirect';before=len(auths);process=spawn('redirect');assert await line(process)=={'transport_refused':True};await done(process)
            assert not escapes and len(auths)==before
            cases.append('actual_verified_TLS_WebSocket_302_is_not_followed_and_never_receives_native_authentication')
            mode['name']='auth-refuse';process=spawn('auth-refuse');assert await line(process)=={'transport_refused':True};await done(process)
            cases.append('actual_relay_AUTH_refusal_produces_no_subscription_or_native_message_readiness')
            mode['name']='profile';process=spawn('profile')
            assert await line(process)=={'profile_ready':True,'lease_refused':True,'actual_private_UID':65534}
            publish({**config,'publication':'b'*64});process.stdin.write('withdrawn\n');process.stdin.flush()
            assert await line(process)=={'profile_revoked':True,'native_socket_stopped':True};await done(process)
            cases.append('actual_private_profile_fixed_CLI_native_NIP42_WSS_durable_parent_admission_identity_lease_and_root_publication_replacement_stop_live_native_socket_without_waiting_for_new_network_input')
            mode['name']='profile-auth';before=len(queries);process=spawn('profile-auth')
            assert await line(process)=={'profile_authentication_refused':True};await done(process);assert len(queries)==before+1
            process=spawn('profile-auth-saved');assert await line(process)=={'profile_authentication_refused':True};await done(process)
            assert len(queries)==before+1
            cases.append('actual_401_private_profile_refusal_persists_across_new_UID_processes_and_same_credential_identity_never_retries_or_reports_readiness_after_restart')
            mode['name']='withdraw';process=spawn('withdraw');assert (await line(process))['ready'] is True
            before=len(subscriptions);publish({**config,'bindings':[]});process.stdin.write('withdrawn\n');process.stdin.flush()
            assert await line(process)=={'withdrawal_refused':True};await done(process)
            assert len(subscriptions)==before
            cases.append('actual_root_owned_policy_replacement_prevents_further_use_of_existing_authenticated_socket')
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII=')
            document=b'Bounded local native Buzz document'
            voice=Path('/public-media/reference.flac').read_bytes()
            assert hashlib.sha256(voice).hexdigest()=='63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715'
            for data,ext in [(png,'png'),(document,'bin'),(voice,'flac')]:assets['/media/'+hashlib.sha256(data).hexdigest()+'.'+ext]=data
            with socket.socket() as chosen:chosen.bind(('127.0.0.1',0));public_port=chosen.getsockname()[1]
            async def public_asset(request):
                assert request.secure and request.path=='/public.png' and not any(request.headers.get(key) for key in ['Authorization','Cookie','x-auth-tag'])
                public_gets.append(request.path);return web.Response(body=png)
            public_app=web.Application();public_app.router.add_get('/public.png',public_asset)
            public_runner=web.AppRunner(public_app,access_log=None);await public_runner.setup()
            await web.TCPSite(public_runner,'127.0.0.1',public_port,ssl_context=tls).start()
            try:
                public_origin='https://localhost:'+str(public_port)
                account.write_text(json.dumps({**value,'attachment_origins':[public_origin]}));account.chmod(0o600)
                media_grant={**grant,'allow_media':True,'allow_voice':True,'allow_video':True,'generation':'c'*64,'since':(int(time.time())-5)*1000}
                publish({**config,'bindings':[media_grant],'publication':'c'*64})
                png_url=value['relay_url']+'/media/'+hashlib.sha256(png).hexdigest()+'.png'
                def imeta(data,url,mime):return ['imeta','url '+url,'x '+hashlib.sha256(data).hexdigest(),'size '+str(len(data)),'m '+mime,'filename attachment.bin']
                voice_url=value['relay_url']+'/media/'+hashlib.sha256(voice).hexdigest()+'.flac'
                inputs=json.loads(fixture.read_text());inputs.update({
                    'media-image':signed(peer_scalar,'![fixture]('+png_url+')',tags=[['h',channel],['p',public],imeta(png,png_url,'image/png')]),
                    'media-document':signed(peer_scalar,'Inspect document '+value['relay_url']+'/media/'+hashlib.sha256(document).hexdigest()+'.bin'),
                    'media-voice':signed(peer_scalar,'Listen to this fixture',tags=[['h',channel],['p',public],imeta(voice,voice_url,'audio/flac')]),
                    'media-public':signed(peer_scalar,'Inspect external fixture',tags=[['h',channel],['p',public],imeta(png,public_origin+'/public.png','image/png')]),
                    'media-cache-fail':signed(peer_scalar,'Retain image before blob insertion',tags=[['h',channel],['p',public],imeta(png,png_url,'image/png')]),
                    'media-cache-damage':signed(peer_scalar,'Reject damaged retained bytes',tags=[['h',channel],['p',public],imeta(png,png_url,'image/png')]),
                    'media-badsha':signed(peer_scalar,'Reject changed resource',tags=[['h',channel],['p',public],['imeta','url '+png_url,'x '+('a'*64),'size '+str(len(png)),'m image/png']]),
                    'media-command':signed(peer_scalar,'/status '+png_url)})
                fixture.write_text(json.dumps(inputs));fixture.chmod(0o644)
                for name,goal,kind in [('media-image','fixture','image'),('media-document','Inspect document','document'),
                        ('media-voice','Listen to this fixture','voice'),('media-public','Inspect external fixture','image')]:
                    mode['name']=name;before=len(media_gets);before_public=len(public_gets);process=spawn(name)
                    result=await line(process);await done(process)
                    assert result=={'media_admitted':{'goal':goal,'type':'photo' if kind=='image' else kind,'kinds':[kind]},'resource_count':1,'same_source_replay':True,'actual_local_ASR':name=='media-voice'},result
                    assert len(media_gets)==before+(name!='media-public') and len(public_gets)==before_public+(name=='media-public')
                cases.append('actual_gateway_UID_original_signature_media_grant_native_imeta_and_bare_URL_decoding_preserve_image_document_and_voice_kinds_with_private_FULL_cache_and_parent_media_ids')
                cases.append('same_relay_private_media_uses_actual_Blossom_signer_while_explicit_foreign_TLS_origin_receives_no_authentication_and_duplicate_imeta_body_URL_is_one_resource')
                cases.append('actual_gateway_UID_native_voice_media_controller_composition_and_pinned_offline_ASR_reach_only_text_agent_terminal_without_raw_audio_and_replay_creates_no_new_ASR_or_mission_with_private_IPC_and_terminal_fixture_seams')
                mode['name']='media-cache-fail';before=len(media_gets);process=spawn('media-cache-fail')
                assert await line(process)=={'receipt_precedes_blob':True};await done(process);assert len(media_gets)==before+1
                await asyncio.sleep(2.1);process=spawn('media-cache-recover');result=await line(process);await done(process)
                assert result['media_admitted']['kinds']==['image'] and result['same_source_replay'] is True and len(media_gets)==before+2
                cases.append('actual_SQL_blob_insertion_failure_keeps_first_byte_receipt_then_new_private_process_refetches_only_exact_original_hash_MIME_and_descriptor_before_native_admission')
                for name,reason,count in [('media-badsha','resource-integrity-refused',1),('media-command','media-command-refused',0)]:
                    mode['name']=name;before=len(media_gets);process=spawn(name)
                    assert await line(process)=={'refused':reason};await done(process);assert len(media_gets)==before+count
                cases.append('actual_private_resource_hash_mismatch_never_reaches_parent_and_media_control_command_is_refused_before_spending_network_credentials')
                mode['name']='media-cache-damage';before=len(media_gets);process=spawn('media-cache-damage')
                assert await line(process)=={'cache_precedes_parent':True};await done(process);assert len(media_gets)==before+1
                await asyncio.sleep(2.1);process=spawn('media-cache-damage-replay')
                assert await line(process)=={'damaged_cache_refused':True};await done(process);assert len(media_gets)==before+1
                cases.append('actual_damaged_retained_media_after_parent_commit_failure_is_refused_on_private_process_reopen_without_refetch_or_automatic_restoration')
                denied={**media_grant,'allow_voice':False,'generation':'d'*64,'since':(int(time.time())-5)*1000}
                publish({**config,'bindings':[denied],'publication':'d'*64})
                inputs=json.loads(fixture.read_text());inputs.update({
                    'media-voice-masked-denied':signed(peer_scalar,'Not a document downgrade',tags=[['h',channel],['p',public],imeta(voice,voice_url,'application/octet-stream')]),
                    'media-unapproved':signed(peer_scalar,'No implicit foreign origin',tags=[['h',channel],['p',public],imeta(png,'https://never.fixture.invalid/private.png','image/png')])})
                fixture.write_text(json.dumps(inputs));fixture.chmod(0o644)
                before=len(media_gets);process=spawn('media-voice-masked-denied')
                assert await line(process)=={'refused':'independent-decoded-media-consent-required'};await done(process);assert len(media_gets)==before+1
                cases.append('actual_voice_bytes_labeled_octet_stream_never_become_document_media_or_reach_ASR_or_parent_when_only_general_media_is_approved')
                before=len(media_gets)+len(public_gets);process=spawn('media-unapproved')
                assert await line(process)=={'capture_refused':True};await done(process);assert len(media_gets)+len(public_gets)==before
                cases.append('signed_foreign_media_origin_without_explicit_owner_approval_is_refused_before_original_admission_or_any_HTTP_credentials')
            finally:await public_runner.cleanup()
        finally:
            for connection in active:await connection.close()
            await runner.cleanup()
    asyncio.run(exercise())
    print(json.dumps({'passed':len(cases),'cases':cases,'actual_UID_TLS_native_auth_subscription_and_MessageEvent':True,
        'actual_FULL_original_native_inbox_and_parent_relay_custody':True,
        'actual_private_profile_lease_lifecycle_native_text_and_revocation':True,
        'production_runtime_factory_root_controller_mission_media_delivery_GUI_or_public_activation':False},indent=2))


if __name__=='__main__':main()
