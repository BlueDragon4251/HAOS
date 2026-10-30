#!/usr/bin/env python3
"""Actual native send + Google discovery client over explicit loopback HTTP."""
import asyncio
from datetime import datetime,timezone
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
from types import MethodType
from urllib.parse import urlsplit,parse_qs


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from haos.gateway_google_chat import scope,PreparedGoogleChatPolicy
    from haos.gateway_google_chat_text import TextLedger
    from haos.gateway_google_chat_http import single_request_http
    from haos.gateway_raw import NativeInbox
    from haos.gateway import digest,Conflict
    from haos.redaction import Redactor
    from gateway.config import PlatformConfig
    from plugins.platforms.google_chat.adapter import GoogleChatAdapter
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import httplib2
    # Schema-only private account; HTTP account auth is deliberately outside
    # this native-send/SDK-wire fixture (no real provider credential exists).
    email='gateway@haos-fixture.iam.gserviceaccount.com'
    sa={'type':'service_account','project_id':'haos-fixture','private_key_id':'a'*40,
        'private_key':'-----BEGIN PRIVATE KEY-----\n'+'A'*512+'\n-----END PRIVATE KEY-----\n',
        'client_email':email,'client_id':'123456789','auth_uri':'https://accounts.google.com/o/oauth2/auth',
        'token_uri':'https://oauth2.googleapis.com/token','auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')}
    value={'service_account':sa,'bot_user':'users/999','inbound':{'mode':'pubsub','subscription':'projects/haos-fixture/subscriptions/haos-private'}}
    with tempfile.TemporaryDirectory(prefix='haos-google-text-') as directory:
        os.environ['HERMES_HOME']=directory;path=Path(directory)/'reply.sqlite';inbox=NativeInbox(path,Redactor([]))
        binding={'id':'owner','connector':'google','sender':'users/123','chat':'spaces/room1','thread':'spaces/room1/threads/thread1',
            'scope':scope(value),'identity':'personal','capabilities':['read'],'generation':'a'*64,'since':1}
        policy=PreparedGoogleChatPolicy({'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding]})
        route={'binding_id':'owner','binding_digest':digest(binding)};requests=[];stored={};mode={'next':'ok'}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status,data):
                body=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                query=parse_qs(urlsplit(self.path).query);body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(('POST',query,body));client=query['messageId'][0]
                with sqlite3.connect(path) as db:
                    row=db.execute('SELECT state,client_id FROM google_chat_text_writes WHERE client_id=?',(client,)).fetchone();assert row==('writing',client)
                assert query['messageReplyOption']==['REPLY_MESSAGE_OR_FAIL'] and len(query['requestId'][0])==36
                if mode['next']=='auth':
                    mode['next']='ok';self.reply(401,{'error':{'code':401,'message':'local fixture auth refusal'}});return
                if mode['next']=='redirect':
                    mode['next']='ok';self.send_response(302);self.send_header('Location','/foreign-target');self.send_header('Content-Length','0');self.end_headers();return
                if mode['next']=='rate':mode['next']='ok';self.reply(429,{'error':{'code':429,'message':'local fixture rate limit'}});return
                response={'name':'spaces/room1/messages/server.part'+str(len(stored)),'text':body['text'],
                    'thread':body['thread'],'clientAssignedMessageId':client};stored[client]=response
                if mode['next']=='disconnect':
                    mode['next']='ok';self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                self.reply(200,response)
            def do_GET(self):
                client=urlsplit(self.path).path.rsplit('/',1)[1];requests.append(('GET',client))
                if client in stored:self.reply(200,stored[client])
                else:self.reply(404,{'error':{'code':404,'message':'local fixture unknown acceptance'}})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        api=build('chat','v1',http=single_request_http(lambda:None,fixture_origin=origin),cache_discovery=False,static_discovery=True,
            client_options={'api_endpoint':'http://127.0.0.1:'+str(server.server_port)+'/'})
        adapter=GoogleChatAdapter(PlatformConfig(enabled=True));adapter._chat_api=api
        adapter._new_authed_http=lambda:single_request_http(lambda:None,fixture_origin=origin)
        ledger=TextLedger(inbox,'google',value,lambda:policy,lambda:None)
        operation={'id':'1'*64}
        async def create(self,parent,body):return await ledger.create(self,operation['id'],route,parent,body)
        adapter._create_message=MethodType(create,adapter)
        cases=[]
        async def run():
            nonlocal inbox,ledger
            result=await adapter.send(binding['chat'],'native reply',metadata={'thread_id':binding['thread']})
            assert result.success and result.message_id.startswith('spaces/room1/messages/server.part') and len(requests)==1
            result=await adapter.send(binding['chat'],'native reply',metadata={'thread_id':binding['thread']});assert result.success and len(requests)==1
            cases.append('actual_native_send_and_Google_discovery_HTTP_create_use_stable_client_request_IDs_and_OR_FAIL_after_independent_connection_observes_FULL_write_intent_then_confirmed_replay_has_no_HTTP')
            operation['id']='2'*64;mode['next']='disconnect'
            try:await adapter.send(binding['chat'],'uncertain native reply',metadata={'thread_id':binding['thread']})
            except Exception:pass
            else:raise AssertionError('lost acceptance returned success')
            assert len(requests)==2 and requests[-1][0]=='POST'
            inbox.close();inbox=NativeInbox(path,Redactor([]));ledger=TextLedger(inbox,'google',value,lambda:policy,lambda:None)
            result=await adapter.send(binding['chat'],'uncertain native reply',metadata={'thread_id':binding['thread']})
            assert result.success and len(requests)==3 and requests[-1][0]=='GET'
            cases.append('post_body_disconnect_reopen_uses_only_exact_client_ID_GET_reconciliation_without_another_create_or_new_recipient')
            operation['id']='3'*64;mode['next']='rate'
            try:await adapter.send(binding['chat'],'rate limited',metadata={'thread_id':binding['thread']})
            except HttpError as error:assert error.resp.status==429
            else:raise AssertionError('rate limit accepted')
            before=len(requests)
            result=await adapter.send(binding['chat'],'rate limited',metadata={'thread_id':binding['thread']})
            assert not result.success and result.error=='target not found'
            assert len(requests)==before+1 and requests[-1][0]=='GET'
            cases.append('actual_HTTP_429_and_recovery_GET_404_never_automatically_repeat_begun_write_or_reinterpret_not_found_as_non_delivery')
            for identity,kind,status in [('4'*64,'auth',401),('5'*64,'redirect',302)]:
                operation['id']=identity;mode['next']=kind;before=len(requests)
                try:await adapter.send(binding['chat'],'refused '+kind,metadata={'thread_id':binding['thread']})
                except HttpError as error:assert error.resp.status==status
                else:raise AssertionError('authentication or redirect refusal accepted')
                assert len(requests)==before+1 and requests[-1][0]=='POST'
                assert inbox.db.execute('SELECT state FROM google_chat_text_writes WHERE id=?',(identity,)).fetchone()[0]=='writing'
                cases.append('actual_native_HTTP_'+str(status)+'_has_one_wire_attempt_no_redirect_auth_challenge_retry_or_fabricated_acceptance')
            before=len(requests);operation['id']='1'*64
            try:await adapter.send(binding['chat'],'changed reply',metadata={'thread_id':binding['thread']})
            except Conflict:pass
            else:raise AssertionError('retained operation changed content')
            try:await adapter.send(binding['chat'],'native reply',metadata={'thread_id':'spaces/room1/threads/other'})
            except PermissionError:pass
            else:raise AssertionError('cross-thread reply accepted')
            policy.bindings.clear()
            try:await adapter.send(binding['chat'],'native reply',metadata={'thread_id':binding['thread']})
            except PermissionError:pass
            else:raise AssertionError('withdrawn grant accepted')
            assert len(requests)==before
            cases.append('changed_content_cross_thread_and_revoked_grant_refused_before_HTTP_including_previously_confirmed_replies')
        try:asyncio.run(run())
        finally:inbox.close();server.shutdown();server.server_close();thread.join(timeout=2)
        receipt={'passed':len(cases),'cases':cases,'actual_native_send_Google_API_discovery_SDK_HTTP_and_FULL_SQLite':True,
            'HTTP_server_and_account_auth_are_explicit_loopback_fixtures':True,
            'UID_controller_outbox_media_GUI_live_account_recipient_delivery_or_public_activation':False}
        Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases)}))


if __name__=='__main__':main()
