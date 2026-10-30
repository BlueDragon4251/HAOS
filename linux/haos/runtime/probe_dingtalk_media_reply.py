#!/usr/bin/env python3
"""Actual Robot media SDK payloads over local TLS; private upload receipts are fixtures."""
import asyncio,base64,hashlib,json,socket,ssl,sys,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import httpx,requests,dingtalk_stream.stream as stream
    from plugins.platforms.dingtalk import adapter as native
    from gateway.config import PlatformConfig
    from haos import gateway_dingtalk_http as token_wire,gateway_dingtalk_robot_reply as robot
    from haos.gateway_dingtalk import PreparedDingTalkPolicy,scope
    from haos.gateway_dingtalk_media_reply import specification,wire_target
    from haos.gateway_matrix_profile import scope as private_scope
    from haos.gateway import digest
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    value={'client_id':'ding_fixture_app','client_secret':'private-robot-reply-fixture',
        'corp_id':'ding_fixture_corp','robot_code':'ding_fixture_robot','reply_mode':'robot'}
    grant={'id':'owner','connector':'dingtalk','sender':'$:LWCP_v1:$opaque-owner','chat':'cidExactConversation/+=',
        'scope':scope(value),'thread':'','identity':'personal','capabilities':['create','read'],
        'generation':'a'*64,'since':1,'require_mention':True,'allow_outbound_media':True,'allow_voice':True,'allow_video':True}
    config={'version':1,'connectors':[{'id':'dingtalk','platform':'dingtalk'}],'bindings':[grant]}
    policy=lambda:PreparedDingTalkPolicy(config)
    now=int(time.time()*1000)
    original={'msgId':'nativeMessage-robot-123','createAt':now-1000,'senderId':grant['sender'],
        'senderStaffId':'native-approved-staff','conversationId':grant['chat'],'conversationType':'1',
        'chatbotCorpId':value['corp_id'],'senderCorpId':value['corp_id'],'robotCode':value['robot_code'],
        'msgtype':'text','text':{'content':'Durably approved goal.'},'isInAtList':True,
        'sessionWebhook':'https://oapi.dingtalk.com/robot/sendBySession?session=private-expired-fixture',
        'sessionWebhookExpiredTime':now-500}
    state={'mode':'ok','expected':None,'kind':'image','media':None};seen=[];cases=[];live=[True];access='private-robot-fixture-access'
    class Server(ThreadingHTTPServer):
        def handle_error(self,*_args):pass
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_args):pass
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers.get('Cookie') is None and self.headers['Accept-Encoding']=='identity'
            seen.append(self.path);status=200;mode=state['mode']
            if self.path=='/v1.0/oauth2/accessToken':
                assert data=={'appKey':value['client_id'],'appSecret':value['client_secret']}
                payload={'accessToken':access,'expireIn':7200};mode='ok'
            else:
                target=state['expected'];assert self.path==target['url'].split('api.dingtalk.com')[1]
                assert data==target['payload'] and self.headers['x-acs-dingtalk-access-token']==access
                assert self.headers['Host']=='api.dingtalk.com'
                payload={'processQueryKey':'fixture-queued-native-result'}
                if 'userIds' in data:
                    payload.update(invalidStaffIdList=[],flowControlledStaffIdList=[])
                    if mode=='invalid-recipient':payload['invalidStaffIdList']=data['userIds']
                    if mode=='flow-controlled':payload['flowControlledStaffIdList']=data['userIds']
                    if mode=='foreign-recipient':payload['invalidStaffIdList']=['unapproved-staff']
                if mode in {'401','403','429','302','500'}:status=int(mode)
                if mode=='missing-key':payload={}
                if mode=='private-key':payload['processQueryKey']=access
            raw=json.dumps(payload).encode()
            if mode=='duplicate':raw=b'{"processQueryKey":"one","processQueryKey":"two"}'
            if mode=='nonfinite':raw=b'{"processQueryKey":"one","extra":NaN}'
            if mode=='large':raw=json.dumps({**payload,'padding':'x'*70000}).encode()
            if mode=='drop':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if mode=='withdraw':live[0]=False
            self.send_response(status);self.send_header('Content-Type','text/plain' if mode=='wrong-type' else 'application/json')
            self.send_header('Content-Length',str(len(raw)+(10 if mode=='truncated' else 0)))
            self.send_header('Connection','close');self.send_header('Set-Cookie','fixture-only=not-forwarded')
            if mode=='429':self.send_header('Retry-After','120')
            if mode=='302':self.send_header('Location','https://unapproved.invalid/never')
            if mode=='encoding':self.send_header('Content-Encoding','gzip')
            self.end_headers()
            try:self.wfile.write(raw);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            self.close_connection=True
    with tempfile.TemporaryDirectory(prefix='haos-dingtalk-robot-reply-') as td:
        directory=Path(td);create(directory,'robot-reply.fixture.invalid')
        server=Server(('127.0.0.1',0),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(directory/'certificate.pem',directory/'key.pem');server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='https://localhost:'+str(server.server_port);verified=ssl.create_default_context(cafile=str(directory/'ca.pem'))
        actual_client=httpx.AsyncClient;actual_boundary=token_wire.Boundary
        class FixtureBoundary(actual_boundary):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                self.session=requests.Session();self.session.trust_env=False;self.session.headers.clear()
                self.session.headers['Accept-Encoding']='identity';self.session.verify=str(directory/'ca.pem')
        class Loopback(httpx.AsyncBaseTransport):
            def __init__(self):self.real=httpx.AsyncHTTPTransport(verify=True if state['mode']=='untrusted-tls' else verified,retries=0)
            async def handle_async_request(self,request):
                assert request.method=='POST' and request.url.scheme=='https' and request.url.host=='api.dingtalk.com'
                destination=request.url.copy_with(host='localhost',port=server.server_port)
                return await self.real.handle_async_request(httpx.Request(request.method,destination,
                    headers=request.headers,content=request.content,extensions=request.extensions))
            async def aclose(self):await self.real.aclose()
        def fixture_client(**kwargs):
            assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
            return actual_client(**kwargs,transport=Loopback())
        def current():
            if not live[0]:raise PermissionError('fixture owner withdrew reply permission')
        def prepare(body):
            raw=json.dumps(body).encode()
            item={'binding_id':grant['id'],'binding_digest':digest(grant),'delivery_id':'b'*64,'attempt':1,
                'source_id':body['msgId'],'source_sha256':hashlib.sha256(raw).hexdigest(),
                'source_base64':base64.b64encode(raw).decode(),'body':'Approved native reply.\n1. numbered item'}
            item.pop('body')
            kind=state['kind']
            names={'image':('png','image/png'),'file':('pdf','application/pdf'),'voice':('amr','audio/amr'),'video':('mp4','video/mp4')}
            extension,mime=names[kind]
            item['output']={'id':'c'*64,'kind':kind,'name':'result-0.'+extension,'mime':mime,'size':100,'sha256':'d'*64}
            receipt={'state':'confirmed','kind':kind,'media_id':'$fixturePrivateUploadedMedia','created_at':now}
            cover=None
            if kind=='video':
                thumbnail={**item,'output':{'id':'e'*64,'kind':'image','name':'cover-0.png','mime':'image/png','size':100,'sha256':'f'*64}}
                cover={'upload':thumbnail,'receipt':{'state':'confirmed','kind':'image','media_id':'$fixturePrivateUploadedCover','created_at':now}}
            checked=specification(value,policy(),'dingtalk',{'upload':item,'receipt':receipt,
                'duration_ms':11020 if kind in {'voice','video'} else 0,'width':640 if kind=='video' else 0,
                'height':360 if kind=='video' else 0,'cover':cover},Redactor())
            state['media']=checked['media'];return checked['blueprint']
        async def exercise():
            import itertools
            for route,kind in itertools.product(('oto','group'),('image','file','voice','video')):
                state['kind']=kind
                source={**original,'conversationType':'2' if route=='group' else '1'}
                with private_scope(directory,{'HERMES_SAFE_MODE':'1'}):
                    adapter=native.DingTalkAdapter(PlatformConfig(enabled=True,extra={
                        'client_id':value['client_id'],'client_secret':value['client_secret'],'robot_code':value['robot_code']}))
                adapter._haos_robot_credentials=value
                modes=['ok','401','403','429','302','500','drop','truncated','duplicate','nonfinite',
                    'large','wrong-type','encoding','missing-key','private-key','untrusted-tls','withdraw']
                if route=='oto':modes+=['invalid-recipient','flow-controlled','foreign-recipient']
                for mode in modes:
                    live[0]=True;state['mode']=mode;blueprint=prepare(source)
                    state['expected']=wire_target(adapter,blueprint,state['media']);before=len(seen)
                    expected_key={'image':'sampleImageMsg','file':'sampleFile','voice':'sampleAudio','video':'sampleVideo'}[kind]
                    assert state['expected']['payload']['msgKey']==expected_key
                    actual=json.loads(state['expected']['payload']['msgParam'])
                    expected={'image':{'photoURL':'$fixturePrivateUploadedMedia'},
                        'file':{'mediaId':'$fixturePrivateUploadedMedia','fileName':'result-0.pdf','fileType':'pdf'},
                        'voice':{'mediaId':'$fixturePrivateUploadedMedia','duration':'11020'},
                        'video':{'duration':'12','videoMediaId':'$fixturePrivateUploadedMedia','videoType':'mp4',
                            'picMediaId':'$fixturePrivateUploadedCover','width':640,'height':360}}[kind]
                    assert actual==expected
                    with patch.object(token_wire,'API',origin),patch.object(stream,'DINGTALK_OPENAPI_ENDPOINT',origin),\
                            patch.object(robot,'TokenBoundary',FixtureBoundary),patch.object(httpx,'AsyncClient',fixture_client):
                        result=await robot.invoke(adapter,blueprint,current,Redactor(),media=state['media'])
                        if mode=='ok':
                            assert result['state']=='confirmed' and result['acceptance_id'].startswith('haos-dingtalk-')
                            assert result['remote_message_id'] is None and result['recipient_read_verified'] is False
                        elif mode in {'401','403','429','invalid-recipient','flow-controlled'}:
                            error={'401':'authentication-refused','403':'authentication-refused','429':'rate-limited',
                                'invalid-recipient':'native-refused','flow-controlled':'rate-limited'}[mode]
                            assert result=={'state':'rejected','error':error,'retry_after':120 if mode=='429' else 60 if mode=='flow-controlled' else 0},result
                        else:assert result=={'state':'uncertain'},result
                        assert access not in json.dumps(result) and value['client_secret'] not in json.dumps(result)
                    assert len(seen)==before+(1 if mode=='untrusted-tls' else 2),seen[before:]
                    cases.append('actual_Robot_SDK_'+kind+'_'+route+'_verified_TLS_'+mode+'_one_write_no_implicit_fallback_honest_acceptance')
            live[0]=True
            for altered in ({'senderStaffId':None},{'senderId':'native-approved-staff'},{'senderId':'unapproved-opaque-sender'}):
                try:prepare({**original,**altered})
                except (PermissionError,ValueError,TypeError):pass
                else:raise AssertionError('staff hint replaced canonical sender authorization or missing recipient admitted')
            cases.append('canonical_opaque_sender_authority_required_staff_hint_only_routes_exact_source')
            blueprint=prepare({key:item for key,item in original.items() if key not in {'sessionWebhookExpiredTime','sessionWebhook'}})
            assert blueprint['robot_route']=='oto' and blueprint['session_webhook']==''
            cases.append('owner_selected_stable_Robot_mode_does_not_require_or_fallback_to_expired_session')
        try:asyncio.run(exercise())
        finally:server.shutdown();server.server_close();thread.join(timeout=5)
    result={'cases':cases,'scope':'Actual pinned Hermes token/SDK helper and generated group/OTO media builders, SPI/response models over verified local TLS; fixture origins/CA and synthetic private upload receipts.',
        'actual_upload_kernel_UID_parent_journal_live_delivery_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
