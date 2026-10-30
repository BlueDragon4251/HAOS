"""Real UID/TLS/native SDK no-send action in a guarded offline namespace."""
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def main():
    if (os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists()
            or os.environ.get('HAOS_DISPOSABLE_DINGTALK_RESOURCE_PROCESS')!='1' or Path('/usr/lib/haos').exists()
            or Path('/etc/haos').exists() or not os.statvfs('/repo').f_flag&os.ST_RDONLY):
        raise PermissionError('fresh explicit offline DingTalk process namespace required')
    code=Path('/usr/lib/haos');code.mkdir(mode=0o755);installer='/repo/linux/haos/runtime/install_package.py'
    subprocess.run([sys.executable,installer,'/repo/linux/haos/haos',str(code/'haos')],check=True)
    subprocess.run([sys.executable,installer,'/deps','/sdk'],check=True)
    source=Path(os.environ.get('HAOS_DINGTALK_PUBLIC_SOURCE','/repo/upstream/hermes-agent'))
    if (source/'.herald-os-upstream-sha').read_text().strip()!='f97608f178d1ffeca59860195ab7da295f7c8e5f':raise PermissionError('pinned public source required')
    staged=Path(tempfile.mkdtemp(prefix='haos-dingtalk-source-'))
    shutil.copytree(source,staged,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.venv','__pycache__','.env','auth.json','config.yaml'))
    subprocess.run([sys.executable,installer,str(staged),str(code/'hermes-source')],check=True)
    runtime=code/'hermes/.venv';subprocess.run([sys.executable,'-m','venv','--without-pip',str(runtime)],check=True)
    (runtime/'lib/python3.11/site-packages/dingtalk_fixture.pth').write_text('/sdk\n/usr/lib/haos\n/usr/lib/haos/hermes-source\n')
    with Path('/etc/passwd').open('a') as stream:stream.write('haos-gateway:x:65534:65534:Disposable gateway:/nonexistent:/usr/sbin/nologin\n')
    base=Path('/var/lib/haos-gateway');base.mkdir(mode=0o700);os.chown(base,65534,65534)
    work=Path(tempfile.mkdtemp(prefix='haos-dingtalk-process-'));work.chmod(0o755)
    sys.path[:0]=['/deps',str(code),'/repo/linux/haos/runtime']
    from webhook_tls_fixture import create
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    create(work,'api.dingtalk.com')
    for bundle in [Path('/etc/ssl/certs/ca-certificates.crt'),Path('/sdk/certifi/cacert.pem')]:
        with bundle.open('ab') as stream:stream.write(b'\n'+(work/'ca.pem').read_bytes())
    with Path('/etc/hosts').open('a') as stream:stream.write('\n127.0.0.1 api.dingtalk.com\n')
    value={'client_id':'ding_private_fixture_app','client_secret':'private-dingtalk-process-fixture',
        'corp_id':'ding_fixture_corporation','robot_code':'ding_fixture_robot'}
    config=Path('/etc/haos');config.mkdir(mode=0o755)
    policy={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[{
        'id':'owner','connector':'dingtalk','sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=',
        'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':1}]}
    def publish(data):
        PreparedDingTalkPolicy(data);path=config/'new-policy';path.write_text(json.dumps(data));path.chmod(0o640);os.chown(path,0,65534);path.replace(config/'gateways.json')
    publish(policy)
    account=base/'account.json';account.write_text(json.dumps(value));account.chmod(0o600);os.chown(account,65534,65534)
    canary=work/'owner-secret';canary.write_text('root-only-disposable-owner-evidence');canary.chmod(0o600)
    # A globally classified address belongs ONLY to loopback in this fresh
    # --network=none namespace. The actual production DNS guard remains intact.
    # There is no external interface, route, proxy or Internet destination.
    assert socket.if_nameindex()==[(1,'lo')]
    import struct,base64,hashlib
    link=socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,socket.NETLINK_ROUTE);link.bind((0,0))
    attribute=struct.pack('HH',8,2)+socket.inet_aton('8.8.8.8')
    payload=struct.pack('BBBBI',socket.AF_INET,32,0,254,1)+attribute
    link.send(struct.pack('IHHII',16+len(payload),20,1|4|0x400|0x200,1,0)+payload)
    reply=link.recv(4096);link.close()
    assert struct.unpack_from('H',reply,4)[0]==2 and struct.unpack_from('i',reply,16)[0]==0
    cdn=work/'cdn';cdn.mkdir();create(cdn,'content.fixture.invalid')
    for bundle in [Path('/etc/ssl/certs/ca-certificates.crt'),Path('/sdk/certifi/cacert.pem')]:
        with bundle.open('ab') as stream:stream.write(b'\n'+(cdn/'ca.pem').read_bytes())
    with Path('/etc/hosts').open('a') as stream:stream.write('\n8.8.8.8 content.fixture.invalid\n')
    policy['bindings'][0]['allow_media']=True;publish(policy)
    from haos.gateway import digest
    body={'msgId':'native-resource-source','createAt':int(time.time()*1000)-1000,
        'senderId':policy['bindings'][0]['sender'],'senderCorpId':value['corp_id'],'chatbotCorpId':value['corp_id'],
        'robotCode':value['robot_code'],'conversationId':policy['bindings'][0]['chat'],'conversationType':'1',
        'msgtype':'picture','content':{'downloadCode':'private-native-resource-code'}}
    raw=json.dumps(body).encode();proof={'binding_id':'owner','binding_digest':digest(policy['bindings'][0]),
        'source_sha256':hashlib.sha256(raw).hexdigest(),'source_base64':base64.b64encode(raw).decode(),'resource_index':0}
    source=base/'resource-source.json';source.write_text(json.dumps(proof));source.chmod(0o600);os.chown(source,65534,65534)
    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')
    import io,wave
    voice_buffer=io.BytesIO()
    with wave.open(voice_buffer,'wb') as recording:
        recording.setnchannels(1);recording.setsampwidth(2);recording.setframerate(16000);recording.writeframes(b'\0\0'*1600)
    voice=voice_buffer.getvalue()
    document=b'%PDF-1.4\nHAOS private transport fixture\n%%EOF\n'
    video=b'\0\0\0\x10ftypmp42\0\0\0\0'
    large_document=document*4096
    state={'mode':'ok','intent_reads':0};seen=[]
    class Server(ThreadingHTTPServer):
        def handle_error(self,*_args):pass
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_args):pass
        def respond(self,status,data,mime='application/json',headers=None):
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
            self.send_header('Connection','close')
            for key,value in (headers or {}).items():self.send_header(key,value)
            self.end_headers()
            try:self.wfile.write(data);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            self.close_connection=True
        def do_POST(self):
            assert self.server.server_address[0]=='127.0.0.1'
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers.get('Accept-Encoding')=='identity';seen.append(self.path)
            if self.path=='/v1.0/gateway/connections/open':
                assert data['clientId']==value['client_id'] and data['clientSecret']==value['client_secret']
                assert data['subscriptions']==[{'type':'CALLBACK','topic':'/v1.0/im/bot/messages/get'}]
                self.respond(200,json.dumps({'endpoint':'wss://wss-open-connection.dingtalk.com/connect','ticket':'private-resource-socket-ticket'}).encode());return
            if self.path=='/v1.0/oauth2/accessToken':
                assert data=={'appKey':value['client_id'],'appSecret':value['client_secret']}
                response={'accessToken':'private-resource-token-fixture','expireIn':7200}
            else:
                assert self.path=='/v1.0/robot/messageFiles/download'
                assert self.headers['x-acs-dingtalk-access-token']=='private-resource-token-fixture'
                assert data=={'downloadCode':'private-native-resource-code','robotCode':value['robot_code']}
                response={'downloadUrl':'https://content.fixture.invalid/private%2Fobject?cap=private-cdn-capability'}
                if state['mode']=='private-dns':response['downloadUrl']='https://api.dingtalk.com/private-object'
                if state['mode']=='api-401':self.respond(401,b'{}');return
                if state['mode']=='api-429':self.respond(429,b'{}');return
            self.respond(200,json.dumps(response).encode(),headers={'Set-Cookie':'private-api-cookie=never-forward'})
        def do_GET(self):
            assert self.server.server_address[0]=='8.8.8.8'
            assert self.headers.get('Authorization') is None and self.headers.get('x-acs-dingtalk-access-token') is None
            assert self.headers.get('Cookie') is None and self.headers['Accept-Encoding']=='identity'
            assert self.path=='/private%2Fobject?cap=private-cdn-capability'
            seen.append('cdn');mode=state['mode']
            if mode=='cdn-redirect-private':self.respond(302,b'',headers={'Location':'https://api.dingtalk.com/private-object'});return
            if mode=='cdn-403':self.respond(403,b'');return
            if mode=='cdn-429':self.respond(429,b'',headers={'Retry-After':'120'});return
            data,mime=(large_document+(b' changed' if mode=='intent-changed' and state['intent_reads']>0 else b''),'application/pdf') if mode in {'intent-same','intent-changed'} else (voice,'audio/wav') if mode=='voice' else (document,'application/pdf') if mode=='document' else (video,'video/mp4') if mode=='video' else (image,'image/png')
            if mode in {'intent-same','intent-changed'}:state['intent_reads']+=1
            self.respond(200,data,mime)
    # Second isolated alias is the actual fixed WSS peer, with its own TLS leaf.
    link=socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,socket.NETLINK_ROUTE);link.bind((0,0))
    attribute=struct.pack('HH',8,2)+socket.inet_aton('8.8.4.4');payload=struct.pack('BBBBI',socket.AF_INET,32,0,254,1)+attribute
    link.send(struct.pack('IHHII',16+len(payload),20,1|4|0x400|0x200,1,0)+payload)
    response=link.recv(4096);link.close();assert struct.unpack_from('i',response,16)[0]==0
    ws_directory=work/'wss';ws_directory.mkdir();create(ws_directory,'wss-open-connection.dingtalk.com')
    with Path('/etc/ssl/certs/ca-certificates.crt').open('ab') as stream:stream.write(b'\n'+(ws_directory/'ca.pem').read_bytes())
    with Path('/etc/hosts').open('a') as stream:stream.write('\n8.8.4.4 wss-open-connection.dingtalk.com\n')
    ws_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ws_tls.load_cert_chain(ws_directory/'certificate.pem',ws_directory/'key.pem')
    from websockets.sync.server import serve
    from websockets.exceptions import ConnectionClosed
    ws_acks=[];ws_errors=[]
    def socket_handler(ws):
        try:
            assert ws.request.path=='/connect?ticket=private-resource-socket-ticket'
            frame={'specVersion':'1.0','type':'CALLBACK','headers':{'appId':value['client_id'],
                'messageId':'resource-native-callback','time':str(int(time.time()*1000)),
                'contentType':'application/json','topic':'/v1.0/im/bot/messages/get'},'data':json.dumps(body)}
            ws.send(json.dumps(frame));ack=json.loads(ws.recv(timeout=15))
            assert ack['code']==200 and ack['headers']['messageId']=='resource-native-callback'
            with __import__('sqlite3').connect(base/'media-inbox.db') as db:
                assert db.execute('SELECT COUNT(*) FROM native_inbox WHERE message_id=?',(body['msgId'],)).fetchone()[0]==1
            ws_acks.append(True)
            try:ws.recv(timeout=35)
            except ConnectionClosed:pass
        except Exception as error:ws_errors.append(type(error).__name__)
    ws_server=serve(socket_handler,'8.8.4.4',443,ssl=ws_tls,compression=None)
    ws_thread=threading.Thread(target=ws_server.serve_forever,daemon=True);ws_thread.start()
    servers=[];threads=[]
    for address,directory in [('127.0.0.1',work),('8.8.8.8',cdn)]:
        server=Server((address,443),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(directory/'certificate.pem',directory/'key.pem');server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();servers.append(server);threads.append(thread)
    script=work/'resource_fixture.py';script.write_text('''
import asyncio,json,sys,os
from pathlib import Path
from haos.gateway_dingtalk import authority
from haos.gateway_dingtalk_resource_process import resource
async def main():
    value=json.loads(Path(sys.argv[1]).read_text());proof=json.loads(Path(sys.argv[2]).read_text())
    if len(sys.argv)>3:
        from haos.gateway_dingtalk import PreparedDingTalkPolicy
        from haos.gateway_dingtalk_profile import build
        from haos.gateway_dingtalk_ingress import capture,dispatch_stored
        from haos.gateway_media_relay import MediaCache,event_media
        from haos.gateway_raw import NativeInbox
        from haos.gateway_relay import RelayInbox
        from haos.gateway_runtime import adapter_envelope
        from haos.redaction import Redactor
        import base64,hashlib
        base=Path('/var/lib/haos-gateway');parent=base/'media-profiles';parent.mkdir(mode=0o700,exist_ok=True)
        policy=lambda:PreparedDingTalkPolicy(json.loads(Path('/etc/haos/gateways.json').read_text()))
        inbox=NativeInbox(base/'media-inbox.db',Redactor());relay=RelayInbox(base/'media-relay.db',Redactor())
        adapter=build(value,parent=parent,connector='dingtalk',policy=policy,inbox=inbox);cache=MediaCache(inbox);seen=[]
        expected_kind=sys.argv[3].removeprefix('media-') if sys.argv[3] in {'media-voice','media-document','media-video'} else 'document' if sys.argv[3].startswith('media-intent') else 'image'
        relay_before=relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]
        def receive(event):
            ids=event_media(event,'dingtalk');assert len(ids)==1 and event.raw_message is None and event.source.user_id_alt is None
            item=cache.get(policy(),ids[0]);assert item['descriptor']['kind']==expected_kind
            assert item['descriptor']['format']==('png' if expected_kind=='image' else 'mp4' if expected_kind=='video' else 'bin')
            assert value['client_secret'].encode() not in item['data']
            envelope=adapter_envelope(event,'dingtalk');assert 'private-native-resource-code' not in json.dumps(envelope)
            seen.append((ids,item['descriptor']['sha256']))
            if len(seen)==1:raise OSError('fixture relay commit crash after native media retention')
            relay.admit(policy(),'dingtalk',envelope,media=ids);return True
        adapter.set_durable_message_handler(receive)
        try:
            if sys.argv[3]=='ws-media':
                assert await adapter.connect(),adapter.native_health()
                end=__import__('time').monotonic()+30
                while len(seen)<2:
                    assert __import__('time').monotonic()<end,adapter.native_health()
                    await asyncio.sleep(.05)
                assert seen[0]==seen[1]
                assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==relay_before+1
                print(json.dumps({'media_relay':True,'sha256':seen[0][1]}));return
            key=capture(adapter,base64.b64decode(proof['source_base64']))
            if sys.argv[3].startswith('media-intent'):
                import sqlite3
                inbox.db.execute('CREATE TABLE IF NOT EXISTS dingtalk_input_media(input_id TEXT NOT NULL,resource_index INTEGER NOT NULL,fingerprint TEXT NOT NULL,upload_id TEXT NOT NULL,mime TEXT NOT NULL,PRIMARY KEY(input_id,resource_index))')
                old_limit=inbox.db.execute('PRAGMA max_page_count').fetchone()[0]
                pages=inbox.db.execute('PRAGMA page_count').fetchone()[0]
                inbox.db.execute('PRAGMA max_page_count='+str(pages+4))
                try:
                    try:await dispatch_stored(adapter,key)
                    except sqlite3.OperationalError as error:assert error.sqlite_errorcode==sqlite3.SQLITE_FULL
                    else:raise AssertionError('real SQLite page budget did not interrupt blob insertion')
                finally:inbox.db.execute('PRAGMA max_page_count='+str(old_limit))
                intent=inbox.db.execute('SELECT * FROM dingtalk_input_media WHERE input_id=?',(key,)).fetchone()
                assert intent is not None and not seen
                assert inbox.db.execute('SELECT 1 FROM native_media_cache WHERE id=?',(intent['upload_id'],)).fetchone() is None
                inbox.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(key,))
                if sys.argv[3]=='media-intent-changed':
                    from haos.gateway import Conflict
                    try:await dispatch_stored(adapter,key)
                    except Conflict:pass
                    else:raise AssertionError('changed resource replaced first committed byte-hash intent')
                    assert not seen and inbox.db.execute('SELECT 1 FROM native_media_cache WHERE id=?',(intent['upload_id'],)).fetchone() is None
                    assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='failed'
                    print(json.dumps({'intent_changed_refused':True}));return
            if sys.argv[3].startswith('media-error:'):
                expected=sys.argv[3].split(':',1)[1];started=__import__('time').time()
                from haos.gateway_dingtalk_admission import Refused
                try:await dispatch_stored(adapter,key)
                except Refused as error:
                    assert error.reason=='resource-'+expected
                    delay=error.retry_after
                else:raise AssertionError('failed private resource became native mission input')
                assert not seen and adapter._haos_dingtalk_publisher.health()['status']=='ready'
                row=inbox.db.execute('SELECT state,next_attempt FROM native_inbox WHERE id=?',(key,)).fetchone()
                assert row['state']=='pending'
                if expected=='content-rate-limited':assert delay==120 and row['next_attempt']>=started+120
                assert await dispatch_stored(adapter,key) is False
                print(json.dumps({'media_error':expected,'retry_after':delay,'account_status':'ready'}));return
            try:await dispatch_stored(adapter,key)
            except OSError:pass
            else:raise AssertionError('native handler failure consumed media input')
            assert inbox.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='pending'
            inbox.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(key,))  # Explicit fixture recovery clock.
            assert await dispatch_stored(adapter,key) is True and seen[0]==seen[1]
            assert await dispatch_stored(adapter,key) is False
            assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==relay_before+1
            print(json.dumps({'media_relay':True,'sha256':seen[0][1]}));return
        finally:await adapter.close_profile();relay.close();inbox.close()
    try:result=await resource(value,'dingtalk',lambda:authority('dingtalk',value),proof)
    except PermissionError:
        assert os.geteuid() in {0,65533};print('denied');return
    if 'error' in result:print(json.dumps(result));return
    import hashlib
    assert result['descriptor']['kind']=='image' and result['descriptor']['format']=='png'
    assert hashlib.sha256(result['data']).hexdigest()==result['descriptor']['sha256']
    assert result['mime']=='image/png'
    print(json.dumps({'sha256':result['descriptor']['sha256'],'size':len(result['data'])}))
asyncio.run(main())
''');script.chmod(0o644)
    cases=[]
    def run(uid=65534,media=False):
        return subprocess.run([str(runtime/'bin/python'),'-E','-s',str(script),str(account),str(source)]+([media if isinstance(media,str) else 'media'] if media else []),
            user=uid,group=uid,extra_groups=[],capture_output=True,text=True,timeout=40,umask=0o077,
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HERMES_SAFE_MODE':'1'})
    try:
        # Wrong identities are denied before reading private input files. Use a
        # separate closed call so file access itself cannot masquerade as proof.
        denied="import asyncio;from haos.gateway_dingtalk_resource_process import resource\ntry:asyncio.run(resource({},'dingtalk',lambda:None,{}))\nexcept PermissionError:print('denied')\nelse:raise AssertionError('wrong UID invoked resource worker')"
        for uid in [0,65533]:
            before=len(seen);result=subprocess.run([str(runtime/'bin/python'),'-E','-s','-c',denied],
                user=uid,group=uid,extra_groups=[],capture_output=True,text=True,timeout=5,
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
            assert result.returncode==0 and result.stdout=='denied\n' and len(seen)==before
            cases.append('actual_'+str(uid)+'_UID_denied_before_native_resource_request')
        for mode,expected in [('ok',None),('private-dns','invalid-response'),('cdn-redirect-private','invalid-response'),
                              ('api-401','authentication-refused'),('api-429','rate-limited'),('cdn-403','content-refused')]:
            state['mode']=mode;before=len(seen);result=run();assert result.returncode==0,result.stderr[-2000:]
            assert all(secret not in result.stdout+result.stderr for secret in [value['client_secret'],'private-resource-token-fixture',
                'private-cdn-capability','private-native-resource-code'])
            outcome=json.loads(result.stdout)
            if expected is None:assert outcome=={'sha256':hashlib.sha256(image).hexdigest(),'size':len(image)}
            else:assert outcome==({'error':expected,'retry_after':60} if expected=='rate-limited' else {'error':expected}),outcome
            assert seen[before:before+2]==['/v1.0/oauth2/accessToken','/v1.0/robot/messageFiles/download']
            assert seen[before+2:]==(['cdn'] if mode not in {'private-dns','api-401','api-429'} else [])
            cases.append('actual_private_UID_native_Hermes_token_Robot_SDK_public_numeric_DNS_verified_TLS_binary_'+mode)
        state['mode']='ok';before=len(seen);result=run(media=True);assert result.returncode==0,result.stderr[-2000:]
        assert json.loads(result.stdout)=={'media_relay':True,'sha256':hashlib.sha256(image).hexdigest()}
        assert seen[before:]==['/v1.0/oauth2/accessToken','/v1.0/robot/messageFiles/download','cdn']
        cases.append('actual_native_Hermes_retained_image_dispatch_sealed_ID_media_cache_relay_crash_retry_and_replay_never_refetch_bytes_or_leak_codes')
        for mode,expected in [('cdn-403','content-refused'),('cdn-429','content-rate-limited')]:
            state['mode']=mode;body['msgId']='native-failure-'+mode;raw=json.dumps(body).encode()
            proof.update(source_base64=base64.b64encode(raw).decode(),source_sha256=hashlib.sha256(raw).hexdigest())
            source.write_text(json.dumps(proof));before=len(seen);result=run(media='media-error:'+expected)
            assert result.returncode==0,result.stderr[-2000:]
            assert json.loads(result.stdout)=={'media_error':expected,'retry_after':120 if mode=='cdn-429' else 0,'account_status':'ready'}
            assert seen[before:]==['/v1.0/oauth2/accessToken','/v1.0/robot/messageFiles/download','cdn']
            cases.append('actual_native_media_'+mode+'_retains_pending_input_without_global_account_block_or_early_retry')
        policy['bindings'][0].update(allow_voice=True,allow_video=True);publish(policy)
        for kind,data in [('voice',voice),('document',document),('video',video)]:
            state['mode']=kind;body['msgId']='native-resource-'+kind
            if kind=='voice':
                body['msgtype']='richText';body['content']={'richText':[{'type':'text','text':'Review the approved voice attachment.'},
                    {'type':'voice','downloadCode':'private-native-resource-code'}]}
            else:
                body['msgtype']='file';body['content']={'downloadCode':'private-native-resource-code',
                    'fileName':'fixture.mp4' if kind=='video' else 'fixture.pdf'}
            raw=json.dumps(body).encode();proof.update(binding_digest=digest(policy['bindings'][0]),
                source_base64=base64.b64encode(raw).decode(),source_sha256=hashlib.sha256(raw).hexdigest())
            source.write_text(json.dumps(proof));before=len(seen);result=run(media='media-'+kind)
            assert result.returncode==0,result.stderr[-2000:]
            assert json.loads(result.stdout)=={'media_relay':True,'sha256':hashlib.sha256(data).hexdigest()}
            assert seen[before:]==['/v1.0/oauth2/accessToken','/v1.0/robot/messageFiles/download','cdn']
            cases.append('actual_native_'+kind+'_resource_sealed_ID_relay_bytes_and_grant_bound_crash_replay_without_refetch')
        for mode in ['intent-same','intent-changed']:
            state.update(mode=mode,intent_reads=0);body.update(msgId='native-resource-'+mode,msgtype='file',
                content={'downloadCode':'private-native-resource-code','fileName':'fixture.pdf'})
            raw=json.dumps(body).encode();proof.update(source_base64=base64.b64encode(raw).decode(),source_sha256=hashlib.sha256(raw).hexdigest())
            source.write_text(json.dumps(proof));before=len(seen);result=run(media='media-'+mode)
            assert result.returncode==0,result.stderr[-2000:]
            assert json.loads(result.stdout)==({'media_relay':True,'sha256':hashlib.sha256(large_document).hexdigest()}
                if mode=='intent-same' else {'intent_changed_refused':True})
            assert seen[before:]==['/v1.0/oauth2/accessToken','/v1.0/robot/messageFiles/download','cdn']*2
            cases.append('actual_SQLite_full_after_resource_intent_before_blob_'+mode+'_recovery_preserves_first_hash_without_silent_replacement')
        state['mode']='ok';body.update(msgId='native-resource-from-real-WSS',msgtype='picture',content={'downloadCode':'private-native-resource-code'})
        raw=json.dumps(body).encode();proof.update(source_base64=base64.b64encode(raw).decode(),source_sha256=hashlib.sha256(raw).hexdigest())
        source.write_text(json.dumps(proof));before=len(seen);result=run(media='ws-media')
        assert result.returncode==0,result.stderr[-2000:]
        assert json.loads(result.stdout)=={'media_relay':True,'sha256':hashlib.sha256(image).hexdigest()}
        assert seen[before:]==['/v1.0/gateway/connections/open','/v1.0/oauth2/accessToken','/v1.0/robot/messageFiles/download','cdn'],seen[before:]
        assert ws_acks==[True] and not ws_errors,ws_errors
        cases.append('actual_native_verified_WSS_parent_pre_ACK_custody_Robot_SDK_binary_cache_media_relay_and_crash_retry_without_refetch')
        print(json.dumps({'passed':len(cases),'cases':cases,'actual_UIDs':[0,65533,65534],
            'actual_production_public_resolver_no_mocks':True,'synthetic_global_IP_on_loopback_in_network_none_namespace':True,
            'native_API_and_CDN_have_different_origins_no_account_headers_or_cookies_forwarded':True,
            'owner_publication_and_source_are_fixtures':True,'live_account_mission_or_installed_acceptance':False,'voice_PCM_transport_only_no_local_ASR_or_playback_acceptance':True}))
    finally:
        ws_server.shutdown();ws_thread.join(timeout=5)
        for server in servers:server.shutdown();server.server_close()
        for thread in threads:thread.join(timeout=5)


if __name__=='__main__':main()
