#!/usr/bin/env python3
"""Real Google SDK ACK queue and SQLite custody; service transport is a fixture."""
from datetime import datetime,timezone
import json
from pathlib import Path
import queue
import sqlite3
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from google.cloud.pubsub_v1.types import PubsubMessage
    from google.cloud.pubsub_v1.subscriber.message import Message
    from google.cloud.pubsub_v1.subscriber._protocol.requests import AckRequest,NackRequest
    from haos.gateway_google_chat import scope,PreparedGoogleChatPolicy
    from haos.gateway_google_chat_custody import Originals
    from haos.gateway_google_chat_receive import Receiver
    from haos.redaction import Redactor
    email='gateway@haos-fixture.iam.gserviceaccount.com'
    # Schema-only account fixture, never loaded by a credential SDK or sent.
    sa={'type':'service_account','project_id':'haos-fixture','private_key_id':'a'*40,
        'private_key':'-----BEGIN PRIVATE KEY-----\n'+'A'*512+'\n-----END PRIVATE KEY-----\n',
        'client_email':email,'client_id':'123456789','auth_uri':'https://accounts.google.com/o/oauth2/auth',
        'token_uri':'https://oauth2.googleapis.com/token','auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url':'https://www.googleapis.com/robot/v1/metadata/x509/'+email.replace('@','%40')}
    value={'service_account':sa,'bot_user':'users/999','inbound':{'mode':'pubsub','subscription':'projects/haos-fixture/subscriptions/haos-private'}}
    binding={'id':'owner','connector':'google','sender':'users/123','chat':'spaces/room1','thread':'spaces/room1/threads/thread1',
        'scope':scope(value),'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':int(time.time()*1000)-60000}
    policy=PreparedGoogleChatPolicy({'version':1,'connectors':[{'id':'google','platform':'google_chat'}],'bindings':[binding]})
    def event(mid='msg1',sender='users/123'):
        return {'type':'MESSAGE','space':{'name':'spaces/room1','spaceType':'DIRECT_MESSAGE'},'message':{
            'name':'spaces/room1/messages/'+mid,'sender':{'name':sender,'type':'HUMAN'},'thread':{'name':binding['thread']},
            'createTime':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'text':'/status'}}
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-google-pubsub-') as directory:
        path=Path(directory)/'originals.sqlite';store=Originals(path,Redactor([]))
        receiver=Receiver('google',value,store,lambda:policy,lambda:None)
        class ObservedQueue(queue.Queue):
            def put(self,item,*args,**kwargs):
                if isinstance(item,AckRequest):
                    # Independent connection must observe committed custody
                    # before the unmodified SDK enqueues its ACK request.
                    with sqlite3.connect(path) as db:
                        if item.message_id.startswith('accepted'):
                            assert db.execute('SELECT COUNT(*) FROM google_chat_originals WHERE length(raw)>0').fetchone()[0]>=1
                        else:assert db.execute('SELECT COUNT(*) FROM google_chat_source_refusals').fetchone()[0]>=1
                super().put(item,*args,**kwargs)
        q=ObservedQueue()
        def incoming(data,mid):
            raw=data if isinstance(data,bytes) else json.dumps(data).encode()
            return Message(PubsubMessage(data=raw,message_id=mid)._pb,'local-ack-'+mid,1,q)
        first=event();key=receiver.pubsub(incoming(first,'accepted-first'));assert isinstance(q.get_nowait(),AckRequest)
        store.close();store=Originals(path,Redactor([]));receiver=Receiver('google',value,store,lambda:policy,lambda:None)
        assert receiver.pubsub(incoming(first,'accepted-replay'))==key and isinstance(q.get_nowait(),AckRequest)
        assert store.db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1
        cases.append('actual_Google_SDK_ACK_is_enqueued_only_after_an_independent_connection_observes_FULL_original_commit_and_process_reopen_replay_keeps_one_source')
        for data in [event('unknown','users/456'),b'{invalid-json']:
            assert receiver.pubsub(incoming(data,'refused-source')) is None and isinstance(q.get_nowait(),AckRequest)
        assert store.db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==1
        assert store.db.execute('SELECT COUNT(*) FROM google_chat_source_refusals').fetchone()[0]==2
        cases.append('unknown_sender_and_malformed_event_have_durable_hash_only_refusal_before_actual_SDK_ACK_without_source_admission_or_content_in_audit')
        store.db.execute("CREATE TRIGGER fail_original BEFORE INSERT ON google_chat_originals BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END")
        try:receiver.pubsub(incoming(event('diskfail'),'accepted-diskfail'))
        except sqlite3.IntegrityError:pass
        else:raise AssertionError('failed original commit accepted')
        assert isinstance(q.get_nowait(),NackRequest) and q.empty() and not store.db.in_transaction
        store.db.execute('DROP TRIGGER fail_original')
        cases.append('actual_SQL_commit_failure_produces_native_SDK_NACK_without_ACK_or_lost_original_then_can_retry')
        assert receiver.pubsub(incoming(event('diskretry'),'accepted-diskretry')) and isinstance(q.get_nowait(),AckRequest)
        store.db.execute("CREATE TRIGGER fail_refusal BEFORE INSERT ON google_chat_source_refusals BEGIN SELECT RAISE(ABORT,'fixture audit full'); END")
        try:receiver.pubsub(incoming(event('untracked','users/777'),'refused-untracked'))
        except sqlite3.IntegrityError:pass
        else:raise AssertionError('unaudited refusal acknowledged')
        assert isinstance(q.get_nowait(),NackRequest) and q.empty()
        cases.append('refusal_audit_commit_failure_also_NACKs_without_silent_drop_or_implicit_unknown_sender_authority')
        store.close()
    receipt={'passed':len(cases),'cases':cases,'actual_Google_PubSub_Message_ack_nack_and_SQLite_FULL':True,
        'authenticated_subscriber_and_remote_ack_acceptance_are_not_exercised':True,
        'UID_native_dispatch_missions_media_GUI_live_account_or_public_activation':False}
    Path(sys.argv[1]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':len(cases)}))


if __name__=='__main__':main()
