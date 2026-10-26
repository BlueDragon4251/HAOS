#!/usr/bin/env python3
"""Actual loopback aiohttp requests into prepared signed LINE durable admission."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway_line_ingress import PreparedLINEPolicy
    from haos.gateway_line_listener import application
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        from aiohttp import web,ClientSession
        os.environ['HERMES_HOME']=str(directory/'hermes');os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from plugins.platforms.line.adapter import LineAdapter
        user='U'+'a'*32;destination='U'+'d'*32
        config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':user,'chat':user,'scope':destination,'thread':'',
            'identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':int((time.time()-10)*1000)}]}
        inbox=NativeInbox(directory/'native.db',Redactor());adapter=LineAdapter(PlatformConfig(enabled=True,extra={'channel_secret':'disposable-webhook-secret'}))
        adapter._haos_native=SimpleNamespace(connector='line',policy=lambda:PreparedLINEPolicy(config),inbox=inbox)
        runner=web.AppRunner(application(adapter,destination),access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1];url=f'http://127.0.0.1:{port}/line/webhook'
        event={'type':'message','mode':'active','timestamp':int(time.time()*1000),'webhookEventId':'01K8'+'A'*22,
            'source':{'type':'user','userId':user},'message':{'type':'text','id':'1234','text':'retained loopback text'},
            'replyToken':'private-unused-single-use-fixture'}
        def signed(events=None):
            body=json.dumps({'destination':destination,'events':[event] if events is None else events}).encode()
            return body,{'X-Line-Signature':base64.b64encode(hmac.new(adapter.channel_secret.encode(),body,hashlib.sha256).digest()).decode()}
        try:
            async with ClientSession() as client:
                body,headers=signed()
                async with client.post(url,data=body,headers=headers) as response:assert response.status==200
                with sqlite3.connect(directory/'native.db') as observer:
                    state,payload=observer.execute('SELECT state,payload FROM native_inbox').fetchone()
                    assert state=='pending' and 'retained loopback text' in payload and 'private-unused' not in payload
                cases.append('actual_signed_http_200_only_after_observable_private_sqlite_commit_without_reply_capability')
                async with client.post(url,data=body,headers=headers) as response:assert response.status==200
                assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
                cases.append('remote_redelivery_returns_success_without_duplicate_durable_input')
                for label,data,h,status in [('missing_signature',body,{},401),('tampered_body',body+b' ',headers,401),
                    ('duplicate_signature',body,list(headers.items())*2,401),('oversized_request',b'x'*65537,headers,413)]:
                    async with client.post(url,data=data,headers=h) as response:assert response.status==status,label
                    cases.append(label)
                for path in ['/line/media/token/file','/line/webhook/health','/plugins/line']:
                    async with client.get(f'http://127.0.0.1:{port}'+path) as response:assert response.status==404
                    cases.append('no_native_auxiliary_route_'+path)
                malformed=b'{invalid';mh={'X-Line-Signature':base64.b64encode(hmac.new(adapter.channel_secret.encode(),malformed,hashlib.sha256).digest()).decode()}
                async with client.post(url,data=malformed,headers=mh) as response:assert response.status==400
                cases.append('signed_malformed_json_is_rejected_without_admission')
                # Real SQLite storage fault, with no monkeypatch of the verifier,
                # network, commit boundary or returned HTTP status.
                inbox.db.execute("CREATE TRIGGER disposable_storage_failure BEFORE INSERT ON native_inbox BEGIN SELECT RAISE(ABORT,'private-disposable-storage-fault'); END")
                next_event={**event,'webhookEventId':'01K8'+'B'*22};body,headers=signed([next_event])
                async with client.post(url,data=body,headers=headers) as response:
                    assert response.status==503 and 'private-disposable' not in await response.text()
                assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==1
                cases.append('actual_sqlite_commit_failure_returns_503_without_private_error_or_false_ack')
                inbox.db.execute('DROP TRIGGER disposable_storage_failure')
                async with client.post(url,data=body,headers=headers) as response:assert response.status==200
                cases.append('same_remote_event_can_be_redelivered_after_actual_storage_recovery')
                config['bindings']=[]
                next_event={**event,'webhookEventId':'01K8'+'C'*22};body,headers=signed([next_event])
                async with client.post(url,data=body,headers=headers) as response:assert response.status==200
                assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0]==2
                cases.append('current_owner_withdrawal_prevents_new_http_admission_without_restart')
        finally:await runner.cleanup();inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-line-http-') as temporary:asyncio.run(exercise(Path(temporary)))
    receipt={'passed':len(cases),'cases':cases,'actual_loopback_http_and_native_hmac_and_sqlite':True,
        'public_gateway_enabled':False,'tls_ingress_proxy_or_external_webhook_or_account_acceptance':False}
    text=json.dumps(receipt,indent=2)+'\n'
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(text)
    print(text,end='')


if __name__=='__main__':main()
