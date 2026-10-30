#!/usr/bin/env python3
"""Actual native task/result proofs around private file custody and SQL failures.

No external filesystem, TLS, UID or inference acceptance is asserted here; the
separate installed-process probe covers the controller export and HTTPS path.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import GatewayEngine,Conflict,digest
    from haos.store import MissionStore
    from haos.gateway_a2a import credentials,scope,PreparedA2APolicy
    from haos.gateway_a2a_cache import RawEvents
    from haos.gateway_a2a_tasks import Tasks
    from haos.gateway_a2a_native import build
    from haos.gateway_a2a_publisher import Publisher
    from haos.gateway_raw import NativeInbox
    from haos.gateway_runtime import delivery_metadata
    from haos.redaction import Redactor
    from plugins.platforms.a2a import protocol
    from webhook_tls_fixture import create
    cases=[]
    def denied(action):
        try:action()
        except (PermissionError,Conflict):return
        raise AssertionError('unproven private A2A file was accepted')
    with tempfile.TemporaryDirectory(prefix='haos-a2a-files-') as temp:
        root=Path(temp);create(root,'a2a.fixture.invalid')
        value=credentials({'peer_tokens':{'alice':'private_fixture_alice_'+'a'*32},'port':8448,'agent_name':'HAOS',
            'tls':{'public_url':'https://a2a.fixture.invalid/a2a','certificate':(root/'certificate.pem').read_text(),
                'private_key':(root/'key.pem').read_text(),'bind_host':'127.0.0.1','public_listener':False}},verify_tls=False)
        grant={'id':'owner','connector':'a2a','sender':'alice','chat':'ctx-files','scope':scope(value,'alice'),'thread':'',
            'identity':'personal','capabilities':['create','read'],'generation':'a'*64,'since':123,'allow_outbound_media':True}
        config={'version':1,'connectors':[{'id':'a2a','platform':'a2a'}],'bindings':[grant]};active=[True]
        policy=lambda:PreparedA2APolicy(config)
        def current():
            if not active[0]:raise PermissionError('fixture owner publication withdrawal')
        raw=RawEvents(root/'originals.db',Redactor(),current);parent=NativeInbox(root/'parent.db',Redactor())
        tasks=Tasks(root/'tasks.db','alice',value,current,policy,connector='a2a')
        store=MissionStore(root/'missions.db');engine=GatewayEngine(store);home=root/'home';home.mkdir(mode=0o700)
        async def exercise():
            received=[]
            async def receive(event,proof,task_id):
                receipt=parent.admit(policy(),'a2a',proof['envelope'],{'raw_id':proof['id'],'task_id':task_id},received_at=proof['received_at'])
                result=await engine.receive(policy(),'a2a',proof['envelope'],None)
                received.append(result['mission_id']);return receipt
            adapter=build(value,'alice',home,current,policy,tasks,receive);publisher=Publisher(adapter,tasks)
            files=adapter._haos_a2a_artifacts
            request={'jsonrpc':'2.0','id':1,'method':'SendMessage','params':{'message':{'messageId':'source-files',
                'contextId':grant['chat'],'role':'ROLE_USER','parts':[{'text':'Controlled file snapshot checks.'}]}}}
            proof=raw.capture(policy(),'a2a',value,'alice',json.dumps(request).encode())
            def prepare():
                with tasks.source('a2a',proof):return adapter._prepare_task(request['params'],'alice')
            terminal,pending=await asyncio.to_thread(prepare);assert terminal is None
            async with asyncio.timeout(5):
                while not received:await asyncio.sleep(.01)
            task=pending['task_id'];mid=received[0]
            async def send(delivery,projection=None):
                metadata=delivery_metadata(delivery,'a2a')
                if projection is not None:metadata['haos_output']=projection
                result=await publisher.send(delivery['chat'],delivery['content'],delivery['reply_to'],metadata)
                assert result.success
                engine.acknowledge(policy(),delivery['id'],{'attempt':delivery['attempt'],'status':'delivered','message_id':result.message_id})
            await send(engine.next_delivery(policy()));assert store.claim()['id']==mid
            store.settle(mid,'completed',result='Controlled exact bytes file.')
            final=[]
            while (delivery:=engine.next_delivery(policy())) is not None:
                if delivery['event_context']['kind']=='mission.completed':final.append(delivery)
                else:await send(delivery)
            assert len(final)==1
            delivery=final[0];group=delivery['event_context']['group_sha256'];data=b'fixture result bytes\n'
            offer={'id':digest('root-export-snapshot'),'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            def put(body=data,name='result-0.txt'):
                return files.put(task,group,delivery['id'],offer,body,name,'text/plain')
            tasks.db.execute("CREATE TRIGGER reject_artifact BEFORE INSERT ON a2a_output_artifacts BEGIN SELECT RAISE(ABORT,'fixture artifact SQL failure'); END")
            try:put()
            except sqlite3.IntegrityError:pass
            else:raise AssertionError('artifact SQL failure was hidden')
            assert tasks.db.execute('SELECT COUNT(*) FROM a2a_output_artifacts').fetchone()[0]==0
            tasks.db.execute('DROP TRIGGER reject_artifact');identity=put()
            cases.append('real_SQLite_insert_failure_never_creates_an_artifact_receipt_and_retry_retains_exact_bytes')
            denied(lambda:files.get(identity));assert not files.for_task(task)
            cases.append('retained_file_is_unavailable_before_actual_native_result_epoch_commit')
            assert put()==identity
            denied(lambda:put(name='result-1.txt'))
            denied(lambda:files.prepared(identity,task,'f'*64,delivery['id']))
            cases.append('identical_file_replay_is_idempotent_and_changed_metadata_or_group_is_rejected')
            projection={'text':delivery['content'],'artifact_ids':[identity],'source_sha256':delivery['event_context']['content_sha256']}
            await send(delivery,projection);assert tasks.get(task)['state']==protocol.STATE_COMPLETED
            assert files.get(identity)['data']==data and len(files.parts(task))==1
            cases.append('actual_complete_controller_group_and_native_result_epoch_unlock_exact_file_snapshot')
            row=tasks.db.execute('SELECT data FROM a2a_output_artifacts WHERE id=?',(identity,)).fetchone()
            tasks.db.execute('UPDATE a2a_output_artifacts SET data=? WHERE id=?',(b'x'*len(data),identity))
            denied(lambda:files.get(identity))
            tasks.db.execute('UPDATE a2a_output_artifacts SET data=? WHERE id=?',(row['data'],identity))
            cases.append('changed_retained_file_bytes_are_rejected_even_with_unchanged_transport_identity')
            receipt=tasks.db.execute('SELECT receipt_sha256 FROM a2a_result_epochs WHERE task_id=?',(task,)).fetchone()[0]
            tasks.db.execute("UPDATE a2a_result_epochs SET receipt_sha256='' WHERE task_id=?",(task,))
            denied(lambda:files.get(identity))
            tasks.db.execute('UPDATE a2a_result_epochs SET receipt_sha256=? WHERE task_id=?',(receipt,task))
            cases.append('file_read_requires_exact_committed_native_result_acceptance_proof')
            audit=files.begin_read(files.get(identity));files.finish_read(audit,3,False)
            logged=tasks.db.execute('SELECT state,written,size FROM a2a_artifact_reads WHERE id=?',(audit,)).fetchone()
            assert tuple(logged)==('interrupted',3,len(data))
            cases.append('interrupted_local_transfer_keeps_exact_written_count_without_claiming_peer_receipt')
            active[0]=False;denied(lambda:files.get(identity));denied(lambda:files.parts(task));active[0]=True
            grant['allow_outbound_media']=False;denied(lambda:files.get(identity));grant['allow_outbound_media']=True
            cases.append('current_owner_publication_and_separate_file_permission_gate_cached_reads_and_native_parts')
            # Close/reopen the real task index, preserving the same native outcome
            # and exact blob; this does not recreate an agent filesystem read.
            await adapter.close_profile();tasks.close()
            reopened=Tasks(root/'tasks.db','alice',value,current,policy,connector='a2a')
            from haos.gateway_a2a_artifacts import Artifacts
            try:assert Artifacts(reopened).get(identity)['data']==data
            finally:reopened.close()
            cases.append('actual_SQLite_and_native_TaskStore_reopen_preserves_committed_file_without_new_export')
        try:asyncio.run(exercise())
        finally:store.close();parent.close();raw.close()
    Path(sys.argv[2]).write_text(json.dumps({'cases':cases,'pinned_hermes':'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'scope':'actual pinned native A2A task/Future/finalization, MissionStore outbox, FULL SQLite file/result proof and real SQL failures; parent dispatch and sealed export handoff are fixture substitutions',
        'HTTP_TLS_UID_live_peer_inference_or_public_activation':False},indent=2)+'\n')
    print(json.dumps({'passed':len(cases),'public_gateway':False}))


if __name__=='__main__':main()
