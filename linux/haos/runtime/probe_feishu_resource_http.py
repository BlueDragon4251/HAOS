#!/usr/bin/env python3
"""Actual frozen SDK binary reads over verified loopback TLS; no live account."""
import asyncio
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
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
    from haos.gateway_feishu_resource_http import ResourceBoundary
    from haos.gateway_feishu_http import Failure,sdk_scope
    from haos.gateway_media import MAX_BYTES
    from haos.gateway_matrix_profile import scope
    from haos.redaction import Redactor
    from webhook_tls_fixture import create
    value={'app_id':'cli_0123456789abcdef','app_secret':'private-feishu-resource-fixture','domain':'feishu',
        'tenant_key':'tenant_fixture','bot_open_id':'ou_'+'b'*32,'connection_mode':'websocket'}
    exact={'message_id':'om_'+'a'*32,'file_key':'file_v3_0000000000000000','types':['file']}
    state={'mode':'ok','allowed':True};seen=[];cases=[];secret='private-resource-access-capability'
    body=b'Actual native resource bytes.'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_args):pass
        def send(self,code,data,*,mime='application/octet-stream',length=None,extra=None):
            self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data) if length is None else length))
            for key,item in (extra or {}).items():self.send_header(key,item)
            self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
        def do_POST(self):
            assert self.path=='/open-apis/auth/v3/tenant_access_token/internal'
            assert json.loads(self.rfile.read(int(self.headers['Content-Length'])))=={'app_id':value['app_id'],'app_secret':value['app_secret']}
            self.send(200,json.dumps({'code':0,'tenant_access_token':secret,'expire':7200}).encode(),mime='application/json')
        def do_GET(self):
            expected='/open-apis/im/v1/messages/'+exact['message_id']+'/resources/'+exact['file_key']
            assert self.path in {expected+'?type=file',expected+'?type=audio'}
            assert self.headers['Authorization']=='Bearer '+secret and self.headers['Accept-Encoding']=='identity'
            seen.append(self.path);mode=state['mode']
            if mode=='partial':return self.send(206,b'partial')
            if mode in {'401','429','500'}:return self.send(int(mode),b'failure')
            if mode=='redirect':return self.send(302,b'failure',extra={'Location':'/must-not-follow'})
            if mode=='oversize':return self.send(200,b'x',length=MAX_BYTES+1)
            if mode=='oversize-stream':
                self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.end_headers()
                try:self.wfile.write(b'R'*(MAX_BYTES+1))
                except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
                self.close_connection=True;return
            if mode=='exact-limit':return self.send(200,b'R'*MAX_BYTES)
            if mode=='truncated':self.send(200,b'x',length=100);self.close_connection=True;return
            if mode=='compressed':return self.send(200,body,extra={'Content-Encoding':'gzip'})
            if mode=='mime':return self.send(200,body,mime='bad mime')
            if mode=='secret':return self.send(200,secret.encode())
            if mode=='api-error':return self.send(200,b'{"code":99991400}',mime='application/json')
            if mode=='json-file':return self.send(200,b'{"code":17,"owner_file":true}',mime='application/json',
                extra={'Content-Disposition':'attachment; filename="owner-document.json"'})
            if mode=='withdraw':state['allowed']=False
            if mode=='fallback' and self.path.endswith('type=audio'):return self.send(500,b'not available')
            self.send(200,body,extra={'Content-Disposition':'attachment; filename="../../vendor-path.txt"','X-Private-Vendor-Header':secret})
    with tempfile.TemporaryDirectory(prefix='haos-feishu-resource-') as name:
        root=Path(name);create(root,'fixture.invalid');tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(root/'certificate.pem',root/'key.pem')
        http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.socket=tls.wrap_socket(http.socket,server_side=True)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        origin='https://localhost:'+str(http.server_port);original=DOMAINS['feishu'];DOMAINS['feishu']=origin
        def current():
            if not state['allowed']:raise PermissionError('fixture grant withdrawn')
        def authorize(purpose,target):return state['allowed'] and purpose=='resource' and target==exact
        boundary=ResourceBoundary(value,current,authorize,Redactor([value['app_secret']]))
        try:
            with patch.dict(os.environ,{'REQUESTS_CA_BUNDLE':str(root/'ca.pem')}),scope(root,{'HERMES_SAFE_MODE':'1'}):
                from plugins.platforms.feishu import adapter as native
                from gateway.config import PlatformConfig
                assert native._load_lark_oapi()
                adapter=native.FeishuAdapter(PlatformConfig(enabled=True))
                client=native._build_lark_client(value['app_id'],value['app_secret'],origin);adapter._client=client
                def read():
                    request=native.FeishuAdapter._build_message_resource_request(message_id=exact['message_id'],file_key=exact['file_key'],resource_type=exact['types'][0])
                    return client.im.v1.message_resource.get(request)
                with sdk_scope():
                    try:read()
                    except Failure:pass
                    else:raise AssertionError('resource read escaped private capability')
                    assert not seen;cases.append('actual_native_resource_request_refused_outside_private_capability')
                    with boundary.operation(client._config,'resource',exact):
                        result=read();assert result.success() and native.FeishuAdapter._read_binary_response(result)==body
                        assert result.file_name=='attachment.bin' and result.raw.headers['Content-Type']=='application/octet-stream'
                        assert secret not in str(result.raw.headers)
                    cases.append('actual_native_builder_SDK_binary_decoder_original_bytes_verified_TLS_and_sanitized_filename_headers')
                    for mode,kind in [('401','authentication-refused'),('429','rate-limited'),('500','server-refused'),
                            ('redirect','redirect-refused'),('partial','server-refused'),('oversize','response-too-large'),('oversize-stream','response-too-large'),('truncated','transport-unavailable'),
                            ('compressed','invalid-response'),('mime','invalid-response'),('secret','credential-reflection'),('api-error','rate-limited')]:
                        state['mode']=mode;before=len(seen)
                        with boundary.operation(client._config,'resource',exact):
                            try:read()
                            except Failure as error:assert error.kind==kind,(mode,error.kind)
                            else:raise AssertionError('native resource error accepted: '+mode)
                        assert len(seen)==before+1
                        cases.append('native_resource_'+mode+'_refused_without_redirect_or_implicit_retry')
                    state['mode']='exact-limit'
                    with boundary.operation(client._config,'resource',exact):
                        result=read();assert native.FeishuAdapter._read_binary_response(result)==b'R'*MAX_BYTES
                    cases.append('actual_native_binary_at_exact_byte_limit_preserves_complete_original_data')
                    state['mode']='ok';before=len(seen)
                    other=root/'untrusted';other.mkdir();create(other,'other.invalid')
                    with patch.dict(os.environ,{'REQUESTS_CA_BUNDLE':str(other/'ca.pem')}),boundary.operation(client._config,'resource',exact):
                        try:read()
                        except Failure as error:assert error.kind=='tls-refused'
                        else:raise AssertionError('untrusted resource TLS issuer accepted')
                    assert len(seen)==before
                    cases.append('actual_native_resource_TLS_untrusted_issuer_refused_before_HTTP_or_byte_release')
                    state['mode']='json-file'
                    with boundary.operation(client._config,'resource',exact):
                        result=read();assert native.FeishuAdapter._read_binary_response(result)==b'{"code":17,"owner_file":true}'
                    cases.append('actual_JSON_document_with_native_attachment_header_is_not_confused_with_API_error')
                    state['mode']='withdraw'
                    with boundary.operation(client._config,'resource',exact):
                        try:read()
                        except PermissionError:pass
                        else:raise AssertionError('withdrawn resource bytes released')
                    cases.append('withdrawal_during_actual_HTTP_response_prevents_private_byte_release')
                    state.update(mode='fallback',allowed=True);exact['types']=['audio','file'];before=len(seen)
                    with boundary.operation(client._config,'resource',exact):
                        cached,mime=asyncio.run(adapter._download_feishu_message_resource(message_id=exact['message_id'],file_key=exact['file_key'],
                            resource_type='audio',fallback_filename='owner-name.ogg'))
                        path=Path(cached);assert path.resolve().is_relative_to(root.resolve()) and path.read_bytes()==body
                        assert mime=='application/octet-stream'
                    assert [item.rsplit('=',1)[1] for item in seen[before:]]==['audio','file']
                    cases.append('actual_native_download_cache_helper_and_same_resource_audio_file_fallback_remain_private')
                    state['mode']='429';before=len(seen)
                    with boundary.operation(client._config,'resource',exact):
                        cached,mime=asyncio.run(adapter._download_feishu_message_resource(message_id=exact['message_id'],file_key=exact['file_key'],
                            resource_type='audio',fallback_filename='owner-name.ogg'))
                        assert (cached,mime)==('','')
                    assert len(seen)==before+1;cases.append('actual_native_helper_cannot_bypass_rate_refusal_using_file_fallback')
        finally:
            if 'adapter' in locals():adapter._shutdown_sdk_executor()
            DOMAINS['feishu']=original;http.shutdown();http.server_close();thread.join(5)
    report={'passed':len(cases),'cases':cases,'loopback_fixture_only':True,'private_kernel_media_worker_or_public_activation':False}
    Path(sys.argv[2]).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
