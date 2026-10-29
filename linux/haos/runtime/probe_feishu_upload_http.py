#!/usr/bin/env python3
"""Actual pinned image/file builders and SDK multipart over loopback TLS only."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
from unittest.mock import patch


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_feishu import DOMAINS
    from haos.gateway_feishu_upload_http import UploadBoundary
    from haos.gateway_feishu_http import Failure,sdk_scope
    from haos.gateway_matrix_profile import scope
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-upload-fixture','domain':'feishu',
        'tenant_key':'tenant_fixture','bot_open_id':'ou_'+'b'*32,'connection_mode':'websocket'}
    payload=b'Actual native sealed output bytes.';state={'mode':'ok','allowed':True};seen=[];cases=[]
    exact={'kind':'file','name':'result-0.bin','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'file_type':'stream','duration_ms':0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def send(self,code,body,**headers):
            raw=body if isinstance(body,bytes) else json.dumps(body).encode()
            self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            for key,item in headers.items():self.send_header(key,item)
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']))
            if self.path=='/open-apis/auth/v3/tenant_access_token/internal':
                assert json.loads(raw)=={'app_id':value['app_id'],'app_secret':value['app_secret']}
                return self.send(200,{'code':0,'tenant_access_token':'private-upload-access-capability','expire':7200})
            assert self.path==('/open-apis/im/v1/images' if exact['kind']=='image' else '/open-apis/im/v1/files')
            assert self.headers['Authorization']=='Bearer private-upload-access-capability' and self.headers['Accept-Encoding']=='identity'
            document=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\n\r\n').encode()+raw)
            fields={part.get_param('name',header='content-disposition'):part.get_payload(decode=True) for part in document.iter_parts()}
            assert fields['image' if exact['kind']=='image' else 'file']==payload
            assert hashlib.sha256(raw).hexdigest() and len(raw)<len(payload)+16384
            seen.append(self.path);mode=state['mode']
            if mode in {'401','429','500'}:return self.send(int(mode),{'code':1})
            if mode=='redirect':return self.send(302,{},Location='/must-not-follow')
            if mode=='drop':self.connection.shutdown(2);self.connection.close();return
            if mode=='malformed':return self.send(200,b'{')
            if mode=='oversize':return self.send(200,b' '* (1024*1024+1))
            if mode=='duplicate':return self.send(200,b'{"code":0,"code":0}')
            if mode=='withdraw':state['allowed']=False
            key='image_key' if exact['kind']=='image' else 'file_key'
            uploaded=('img_' if exact['kind']=='image' else 'file_')+'v3_0000000000000000'
            if mode=='missing':return self.send(200,{'code':0,'data':{}})
            if mode=='numeric':uploaded='1'
            if mode=='native-rate':return self.send(200,{'code':99991400})
            return self.send(200,{'code':0,'data':{key:uploaded}})
    with tempfile.TemporaryDirectory(prefix='haos-feishu-upload-') as name:
        root=Path(name);create(root,'fixture.invalid');tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.socket=tls.wrap_socket(http.socket,server_side=True)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        origin='https://localhost:'+str(http.server_port);old=DOMAINS['feishu'];DOMAINS['feishu']=origin
        def current():
            if not state['allowed']:raise PermissionError('fixture grant withdrawn')
        boundary=UploadBoundary(value,current,lambda purpose,target:purpose=='upload' and target==exact,Redactor([value['app_secret']]))
        try:
            with patch.dict(os.environ,{'REQUESTS_CA_BUNDLE':str(root/'ca.pem')}),scope(root,{'HERMES_SAFE_MODE':'1'}):
                from plugins.platforms.feishu import adapter as native
                assert native._load_lark_oapi()
                client=native._build_lark_client(value['app_id'],value['app_secret'],origin)
                def upload(data=payload):
                    stream=io.BytesIO(data);stream.name=exact['name']
                    if exact['kind']=='image':
                        body=native.FeishuAdapter._build_image_upload_body(image_type='message',image=stream)
                        request=native.FeishuAdapter._build_image_upload_request(body)
                        return client.im.v1.image.create(request)
                    body=native.FeishuAdapter._build_file_upload_body(file_type=exact['file_type'],file_name=exact['name'],file=stream,duration=exact['duration_ms'])
                    request=native.FeishuAdapter._build_file_upload_request(body)
                    return client.im.v1.file.create(request)
                with sdk_scope():
                    try:upload()
                    except Failure:pass
                    else:raise AssertionError('upload escaped private capability')
                    assert not seen;cases.append('actual_native_upload_refused_outside_explicit_private_capability')
                    for kind,file_type,name,duration in [('file','stream','result-0.bin',0),('file','pdf','result-0.pdf',0),
                            ('file','opus','result-0.ogg',1000),('file','mp4','result-0.mp4',0),('image','','result-0.png',0)]:
                        exact.update(kind=kind,file_type=file_type,name=name,duration_ms=duration)
                        with boundary.operation(client._config,'upload',exact) as operation:
                            result=upload();assert result.success() and operation['write_started'] is True
                            key='image_key' if kind=='image' else 'file_key'
                            assert getattr(result.data,key)==operation['accepted_key']
                            before=len(seen)
                            try:upload()
                            except Failure:pass
                            else:raise AssertionError('native upload repeated within one durable intent')
                            assert len(seen)==before
                        cases.append('actual_native_'+(file_type or 'image')+'_multipart_builder_SDK_model_and_single_write')
                    exact.update(kind='file',file_type='stream',name='result-0.bin',duration_ms=0)
                    with boundary.operation(client._config,'upload',exact):
                        before=len(seen)
                        try:upload(b'changed output')
                        except Failure as error:assert error.kind=='changed-upload'
                        else:raise AssertionError('changed output bytes uploaded')
                        assert len(seen)==before
                    cases.append('actual_native_multipart_changed_artifact_refused_before_API_write')
                    for mode,expected in [('401','authentication-refused'),('429','rate-limited'),('500','server-refused'),
                            ('redirect','redirect-refused'),('drop','transport-unavailable'),('malformed','invalid-response'),
                            ('oversize','response-too-large'),('duplicate','invalid-response'),('missing','invalid-response'),('numeric','invalid-response')]:
                        state['mode']=mode;before=len(seen)
                        with boundary.operation(client._config,'upload',exact) as operation:
                            try:upload()
                            except Failure as error:assert error.kind==expected,(mode,error.kind)
                            else:raise AssertionError('false native upload acceptance: '+mode)
                            assert operation['write_started'] is True
                        assert len(seen)==before+1
                        cases.append('actual_native_upload_'+mode+'_has_no_false_receipt_or_implicit_retry')
                    state['mode']='native-rate'
                    with boundary.operation(client._config,'upload',exact) as operation:
                        result=upload();assert not result.success() and operation['upload_response']['code']==99991400 and 'accepted_key' not in operation
                    cases.append('native_HTTP_200_rate_code_is_not_upload_acceptance')
                    state['mode']='withdraw'
                    with boundary.operation(client._config,'upload',exact):
                        try:upload()
                        except PermissionError:pass
                        else:raise AssertionError('upload receipt released after withdrawal')
                    cases.append('withdrawal_during_actual_upload_response_prevents_receipt_release')
        finally:DOMAINS['feishu']=old;http.shutdown();http.server_close();thread.join(5)
    report={'passed':len(cases),'cases':cases,'loopback_fixture_only':True,
        'kernel_upload_worker_durable_journal_reply_delivery_or_public_activation':False}
    Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
