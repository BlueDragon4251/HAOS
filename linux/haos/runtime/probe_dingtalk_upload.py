#!/usr/bin/env python3
"""Actual Stream SDK multipart upload over verified local TLS; no live delivery."""
import base64,hashlib,json,socket,ssl,sys,tempfile,threading,time
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import requests,dingtalk_stream.stream as stream
    from haos import gateway_dingtalk_http as token_wire
    from haos.gateway_dingtalk_http import Boundary,sdk_scope
    from haos.gateway_dingtalk_upload_http import Upload,invoke
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    value={'client_id':'ding_fixture_app','client_secret':'private-native-upload-fixture',
        'corp_id':'ding_fixture_corp','robot_code':'ding_fixture_robot'}
    access='private-native-upload-token';key='$fixtureUploadedNativeMediaId'
    state={'mode':'ok','target':None,'data':None};seen=[];cases=[];live=[True]
    class Server(ThreadingHTTPServer):
        def handle_error(self,*_args):pass
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_args):pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']));mode=state['mode'];status=200
            assert self.headers.get('Cookie') is None and self.headers['Accept-Encoding']=='identity'
            if self.path=='/v1.0/oauth2/accessToken':
                assert json.loads(raw)=={'appKey':value['client_id'],'appSecret':value['client_secret']}
                payload={'accessToken':access,'expireIn':7200};mode='ok'
            else:
                assert self.path=='/media/upload?access_token='+access and self.headers['Host']=='oapi.dingtalk.com'
                message=BytesParser(policy=default).parsebytes(b'Content-Type: '+self.headers['Content-Type'].encode()+b'\r\nMIME-Version: 1.0\r\n\r\n'+raw)
                parts=list(message.iter_parts());assert len(parts)==2
                assert parts[0].get_param('name',header='content-disposition')=='type'
                assert parts[0].get_payload(decode=True).decode()==state['target']['kind']
                assert parts[1].get_param('name',header='content-disposition')=='media'
                assert parts[1].get_filename()==state['target']['name']
                assert parts[1].get_content_type()==state['target']['mime'] and parts[1].get_payload(decode=True)==state['data']
                seen.append((state['target']['kind'],mode))
                payload={'errcode':0,'errmsg':'ok','type':state['target']['kind'],'media_id':key,'created_at':int(time.time()*1000)}
                if mode in {'401','403','429','302','500'}:status=int(mode)
                if mode=='native-error':payload={'errcode':40004,'errmsg':'private fixture rejection'}
                if mode=='bool-code':payload['errcode']=False
                if mode=='missing-key':payload.pop('media_id')
                if mode=='wrong-kind':payload['type']='wrong'
                if mode=='private-key':payload['media_id']=access
                if mode=='future-time':payload['created_at']=int(time.time()*1000)+86400000
                if mode=='bool-time':payload['created_at']=True
            raw=json.dumps(payload).encode()
            if mode=='duplicate':raw=b'{"errcode":0,"errcode":1}'
            if mode=='nonfinite':raw=b'{"errcode":0,"media_id":NaN}'
            if mode=='large':raw=json.dumps({**payload,'padding':'x'*70000}).encode()
            if mode=='drop':self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if mode=='withdraw':live[0]=False
            self.send_response(status);self.send_header('Content-Type','text/plain' if mode=='wrong-type' else 'application/json')
            self.send_header('Content-Length',str(len(raw)+(10 if mode=='truncated' else 0)))
            self.send_header('Connection','close');self.send_header('Set-Cookie','fixture-only=never-forwarded')
            if mode=='302':self.send_header('Location','https://unapproved.invalid/never')
            if mode=='429':self.send_header('Retry-After','120')
            if mode=='encoding':self.send_header('Content-Encoding','gzip')
            self.end_headers()
            try:self.wfile.write(raw);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            self.close_connection=True
    with tempfile.TemporaryDirectory(prefix='haos-dingtalk-upload-') as td:
        directory=Path(td);create(directory,'upload.fixture.invalid')
        server=Server(('127.0.0.1',0),Handler);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(directory/'certificate.pem',directory/'key.pem');server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='https://localhost:'+str(server.server_port);actual_session=requests.Session
        class Loopback(actual_session):
            def send(self,request,**kwargs):
                parsed=urlsplit(request.url)
                assert parsed.scheme=='https' and parsed.hostname=='oapi.dingtalk.com' and parsed.port in {None,443}
                request.headers['Host']='oapi.dingtalk.com';request.url=origin+parsed.path+'?'+parsed.query
                kwargs['verify']=True if state['mode']=='untrusted-tls' else str(directory/'ca.pem')
                return super().send(request,**kwargs)
        def current():
            if not live[0]:raise PermissionError('fixture upload approval withdrawn')
        owner=Boundary(value,current,Redactor());client=owner.client()
        owner.session=actual_session();owner.session.trust_env=False;owner.session.headers.clear()
        owner.session.headers['Accept-Encoding']='identity';owner.session.verify=str(directory/'ca.pem')
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6p9sAAAAASUVORK5CYII=')
        fixtures=[('image','result-0.png','image/png',png),('voice','result-1.amr','audio/amr',b'#!AMR\n'+b'\x3c'+bytes(31)),
            ('file','result-2.pdf','application/pdf',b'%PDF-1.4\nfixture byte transport only'),
            ('video','result-3.mp4','video/mp4',bytes.fromhex('000000186674797069736f6d0000020069736f6d69736f32'))]
        try:
            for kind,name,mime,data in fixtures:
                modes=['ok']
                if kind=='image':modes+=['401','403','429','302','500','native-error','bool-code','missing-key','wrong-kind',
                    'private-key','future-time','bool-time','duplicate','nonfinite','large','drop','truncated','wrong-type',
                    'encoding','untrusted-tls','withdraw']
                for mode in modes:
                    live[0]=True;state['mode']=mode
                    with patch.object(token_wire,'API',origin),patch.object(stream,'DINGTALK_OPENAPI_ENDPOINT',origin),sdk_scope(),owner.operation('token',client):
                        token=client.get_access_token()
                    assert token==access
                    item={'kind':kind,'name':name,'mime':mime,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                    state.update(target=item,data=data);operation=Upload(owner,token,item,data,current);before=len(seen)
                    with patch.object(requests,'Session',Loopback):result=invoke(client,operation)
                    assert len(seen)==before+(0 if mode=='untrusted-tls' else 1)
                    if mode=='ok':assert result['state']=='confirmed' and result['media_id']==key and result['kind']==kind
                    elif mode in {'401','403','429','native-error'}:
                        assert result=={'state':'rejected','error':{'401':'authentication-refused','403':'authentication-refused','429':'rate-limited','native-error':'native-refused'}[mode],'retry_after':120 if mode=='429' else 0},result
                    else:assert result=={'state':'uncertain'},result
                    assert access not in json.dumps(result) and value['client_secret'] not in json.dumps(result)
                    cases.append('actual_Stream_SDK_multipart_'+kind+'_verified_TLS_'+mode+'_one_upload_finite_private_result')
            live[0]=True
            state['mode']='ok';kind,name,mime,data=fixtures[0]
            item={'kind':kind,'name':name,'mime':mime,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            for change,content in [({'name':'/owner/private.png'},data),({'mime':'application/octet-stream'},data),
                ({'sha256':'0'*64},data),({},value['client_secret'].encode()),({'kind':'voice'},data)]:
                try:Upload(owner,access,{**item,**change},content,current)
                except (PermissionError,ValueError):pass
                else:raise AssertionError('changed output proof, private credential or host-path upload admitted')
            cases.append('changed_bytes_format_MIME_host_paths_and_private_credential_reflection_refused_before_upload')
            for disguised in [fixtures[0][3],fixtures[1][3],fixtures[3][3]]:
                item={'kind':'file','name':'result-0.pdf','mime':'application/pdf','size':len(disguised),'sha256':hashlib.sha256(disguised).hexdigest()}
                try:Upload(owner,access,item,disguised,current)
                except (PermissionError,ValueError):pass
                else:raise AssertionError('image/voice/video disguised as a native PDF upload admitted')
            cases.append('known_image_voice_or_video_bytes_cannot_be_uploaded_under_an_unrelated_document_format')
        finally:owner.close();server.shutdown();server.server_close();thread.join(timeout=5)
    result={'passed':len(cases),'cases':cases,'scope':'Actual pinned Stream SDK token and multipart upload builders, real requests multipart encoder and verified local TLS; only fixture origins and CA are substituted.',
        'kernel_UID_parent_journal_outbound_message_ASR_playback_or_live_account_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
