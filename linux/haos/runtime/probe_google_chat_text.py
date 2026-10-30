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
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import AuthorizedHttp
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
                assert self.headers.get('Authorization')=='Bearer local-wire-token-fixture'
                query=parse_qs(urlsplit(self.path).query);body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(('POST',query,body));client=query['messageId'][0]
                with sqlite3.connect(path) as db:
                    row=db.execute('SELECT state,client_id,owner_retry_generation,id FROM google_chat_text_writes WHERE client_id=?',(client,)).fetchone();assert row[:2]==('writing',client)
                    if row[2]:
                        audit=db.execute('SELECT consumed_at FROM google_chat_reply_owner_events WHERE part_id=? AND generation=?',(row[3],row[2])).fetchone()
                        assert audit is not None and audit[0] is not None
                assert len(query['requestId'][0])==36
                if body.get('thread'):assert query['messageReplyOption']==['REPLY_MESSAGE_OR_FAIL']
                else:assert 'messageReplyOption' not in query
                if mode['next']=='auth':
                    mode['next']='ok';self.reply(401,{'error':{'code':401,'message':'local fixture auth refusal'}});return
                if mode['next']=='redirect':
                    mode['next']='ok';self.send_response(302);self.send_header('Location','/foreign-target');self.send_header('Content-Length','0');self.end_headers();return
                if mode['next']=='rate':mode['next']='ok';self.reply(429,{'error':{'code':429,'message':'local fixture rate limit'}});return
                if mode['next']=='disconnect-empty':
                    mode['next']='ok';self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                response={'name':'spaces/room1/messages/server.part'+str(len(stored)),'text':body['text'],
                    'thread':body.get('thread',{'name':'spaces/room1/threads/servernew'}),'clientAssignedMessageId':client};stored[client]=response
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
        adapter._new_authed_http=lambda:AuthorizedHttp(Credentials('local-wire-token-fixture'),
            http=single_request_http(lambda:None,fixture_origin=origin,redactor=inbox.redactor),max_refresh_attempts=0)
        ledger=TextLedger(inbox,'google',value,lambda:policy,lambda:None)
        operation={'id':'1'*64}
        async def create(self,parent,body):return await ledger.create(self,operation['id'],route,parent,body)
        adapter._create_message=MethodType(create,adapter)
        cases=[]
        async def run():
            nonlocal inbox,ledger
            result=await adapter.send(binding['chat'],'native reply',metadata={'thread_id':binding['thread']})
            assert inbox.redactor.text('local-wire-token-fixture')=='[REDACTED]'
            assert result.success and result.message_id.startswith('spaces/room1/messages/server.part') and len(requests)==1
            result=await adapter.send(binding['chat'],'native reply',metadata={'thread_id':binding['thread']});assert result.success and len(requests)==1
            cases.append('actual_Google_AuthorizedHttp_injects_private_bearer_and_shared_redactor_captures_it_before_any_API_error_or_log_response')
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
            from haos.gateway_google_chat_recovery import outgoing,approve_retry
            # The ledger fixture retains a real SQLite native admission and
            # source projection for the exact Owner decision. Full Root/UID
            # dispatch remains covered separately by process fixtures.
            source_envelope={'platform':'google_chat','scope':scope(value),'sender':binding['sender'],'chat':binding['chat'],
                'thread':binding['thread'],'message_id':binding['chat']+'/messages/recovery-source','is_bot':False,'text':'/status'}
            source_key=inbox.admit(policy,'google',source_envelope,{})
            assert inbox.claim(source_key,policy) is not None;inbox.complete(source_key,True)
            inbox.db.execute('CREATE TABLE google_chat_native_projection(source_key TEXT PRIMARY KEY,raw_id TEXT NOT NULL,raw_sha256 TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,envelope_sha256 TEXT NOT NULL)')
            inbox.db.execute('INSERT INTO google_chat_native_projection VALUES(?,?,?,?,?,?)',
                (source_key,'a'*64,'b'*64,digest(binding),digest(['google',value]),digest(source_envelope)))
            inbox.db.execute('CREATE TABLE google_chat_delivery_groups(id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,source_id TEXT NOT NULL,source_sha256 TEXT NOT NULL,context_sha256 TEXT NOT NULL,content_sha256 TEXT NOT NULL,parts INTEGER NOT NULL,state TEXT NOT NULL,receipt TEXT NOT NULL,connector TEXT NOT NULL)')
            group='c'*64;operation['id']=digest([group,source_key,0]);mode['next']='rate'
            inbox.db.execute('INSERT INTO google_chat_delivery_groups VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (group,binding['id'],digest(binding),digest(value),source_envelope['message_id'],'b'*64,'d'*64,'e'*64,1,'writing','','google'))
            try:await adapter.send(binding['chat'],'Owner inspected reply',metadata={'thread_id':binding['thread']})
            except HttpError as error:assert error.resp.status==429
            else:raise AssertionError('initial uncertain retry fixture accepted')
            def inspect():return outgoing(inbox,policy,'google',value)['outgoing'][0]
            def decision(view):return {'connector':'google','id':group,'part_id':operation['id'],'snapshot_sha256':view['snapshot_sha256'],
                'owner_uid':1000,'note_sha256':'f'*64,'confirmed':True,'confirmed_not_delivered':True}
            request=decision(inspect());before=len(requests)
            release=approve_retry(inbox,policy,'google',value,request)
            assert len(requests)==before and not release['network_requested'] and not release['message_sent']
            mode['next']='disconnect-empty'
            try:await adapter.send(binding['chat'],'Owner inspected reply',metadata={'thread_id':binding['thread']})
            except Exception:pass
            else:raise AssertionError('retry lost connection returned acceptance')
            assert [r[0] for r in requests[before:]]==['GET','POST']
            retried_query=requests[-1][1];assert requests[before-1][1]==retried_query
            cases.append('actual_SDK_retry_queries_late_acceptance_first_and_reuses_exact_client_request_IDs_after_independent_SQL_connection_observes_durable_approval_consumption_before_POST')
            before=len(requests);assert approve_retry(inbox,policy,'google',value,request)==release
            result=await adapter.send(binding['chat'],'Owner inspected reply',metadata={'thread_id':binding['thread']})
            assert not result.success and [r[0] for r in requests[before:]]==['GET']
            cases.append('lost_approved_retry_and_repeated_Owner_decision_do_not_rearm_POST_even_after_read_only_404')
            # A new exact inspection can approve another bounded attempt. Late
            # provider acceptance then prevents that second write entirely.
            next_request=decision(inspect());assert next_request['snapshot_sha256']!=request['snapshot_sha256']
            assert approve_retry(inbox,policy,'google',value,next_request)['retry_generation']==2
            client=retried_query['messageId'][0]
            stored[client]={'name':binding['chat']+'/messages/late.acceptance','text':'Owner inspected reply',
                'thread':{'name':binding['thread']},'clientAssignedMessageId':client}
            before=len(requests);result=await adapter.send(binding['chat'],'Owner inspected reply',metadata={'thread_id':binding['thread']})
            assert result.success and result.message_id.endswith('/late.acceptance') and [r[0] for r in requests[before:]]==['GET']
            assert inbox.db.execute('SELECT COUNT(*) FROM google_chat_reply_owner_events WHERE consumed_at IS NOT NULL').fetchone()[0]==2
            before=len(requests);result=await adapter.send(binding['chat'],'Owner inspected reply',metadata={'thread_id':binding['thread']})
            assert result.success and len(requests)==before
            cases.append('late_acceptance_after_new_Owner_inspection_confirms_exact_retained_reply_with_GET_only_closes_approval_audit_and_confirmed_replay_has_no_network')
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
            wide={**binding,'thread':'','all_threads':True,'generation':'b'*64}
            policy.bindings['owner']=wide;route['binding_digest']=digest(wide)
            for identifier,selected_thread in [('6'*64,'spaces/room1/threads/firstnew'),('7'*64,'spaces/room1/threads/secondnew')]:
                operation['id']=identifier
                result=await adapter.send(wide['chat'],'approved whole-space reply',metadata={'thread_id':selected_thread})
                assert result.success and requests[-1][0]=='POST' and requests[-1][2]['thread']['name']==selected_thread
            cases.append('explicit_whole_space_owner_grant_preserves_each_actual_source_thread_in_native_SDK_create_with_OR_FAIL_and_distinct_client_IDs')
            operation['id']='8'*64
            result=await adapter.send(wide['chat'],'approved root conversation reply',metadata={'thread_id':''})
            assert result.success and 'thread' not in requests[-1][2]
            cases.append('explicit_whole_space_consent_also_supports_no_thread_conversation_reply_without_inventing_a_target_thread')
            before=len(requests);operation['id']='9'*64
            try:await adapter.send(wide['chat'],'wrong space',metadata={'thread_id':'spaces/other/threads/invalid'})
            except PermissionError:pass
            else:raise AssertionError('whole-space approval crossed into another space')
            assert len(requests)==before
            cases.append('whole_space_native_send_still_refuses_foreign_space_thread_before_any_HTTP')

        try:asyncio.run(run())
        finally:inbox.close();server.shutdown();server.server_close();thread.join(timeout=2)
        receipt={'passed':len(cases),'cases':cases,'actual_native_send_Google_API_discovery_SDK_HTTP_and_FULL_SQLite':True,
            'HTTP_server_and_account_auth_are_explicit_loopback_fixtures':True,
            'UID_controller_outbox_media_GUI_live_account_recipient_delivery_or_public_activation':False}
        Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases)}))


if __name__=='__main__':main()
