"""Root driver for actual serve/reconnect/withdrawal inside the SDK namespace."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import ssl
import subprocess


async def exercise(*,scenario,profile,original_path,publish,policy,event,token,port,ca_bytes,queue,api_calls,payloads,child,reconnect):
    if os.geteuid()!=0 or os.getpid()!=1 or not Path('/.dockerenv').exists():raise PermissionError('disposable Root serve fixture required')
    from aiohttp import ClientSession,TCPConnector
    async def state(expected):
        deadline=asyncio.get_running_loop().time()+15
        while True:
            if child.returncode is not None:raise AssertionError('actual production service stopped before expected state')
            marker=profile/'profile-status.json'
            value=json.loads(marker.read_text()) if marker.exists() else {}
            if expected(value):return value
            if asyncio.get_running_loop().time()>=deadline:
                diagnostic={'expected_production_state_missing':value,'operations':list(api_calls)}
                with sqlite3.connect('/var/lib/haos-gateway/inbox.db') as db:
                    diagnostic['relay_states']=db.execute('SELECT state,COUNT(*) FROM inbox GROUP BY state').fetchall()
                with sqlite3.connect(Path(reconnect).parent/'controller-private/missions.sqlite') as db:
                    diagnostic['outbox_states']=db.execute('SELECT state,error,COUNT(*) FROM gateway_outbox GROUP BY state,error').fetchall()
                raise AssertionError(diagnostic)
            await asyncio.sleep(.05)
    context=ssl.create_default_context(cadata=ca_bytes.decode())
    async with ClientSession(connector=TCPConnector(ssl=context),trust_env=False) as client:
        async def send(mid,sender='users/123'):
            if scenario=='pubsub':queue.put((mid,sender));return
            async with client.post('https://localhost:'+str(port)+'/google-chat',json=event(mid,sender),
                    headers={'Authorization':'Bearer '+token()}) as response:
                assert response.status==200 and await response.read()==b'{}'
        await send('shared');await send('unknown','users/456')
        await state(lambda value:value.get('parent_records')==1 and value.get('confirmed_outputs')==1)
        # Root parent is a real process above PID1; it only gives the private
        # worker account fingerprints. This runs while the profile lease and
        # actual listener/pull process remain active.
        status_code="import sys,json;sys.path.insert(0,'/usr/lib/haos');from haos.google_chat_retired_setup import status;print(json.dumps(status('google')))"
        before_calls=list(api_calls)
        status_process=subprocess.run(['/usr/lib/haos/hermes/.venv/bin/python','-E','-s','-c',status_code],capture_output=True,text=True,timeout=45,
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'})
        assert status_process.returncode==0 and not status_process.stderr,status_process.stderr
        recorded=json.loads(status_process.stdout)
        assert recorded['active_authorization_returned'] is False and recorded['result']['status']==('connected-pull' if scenario=='pubsub' else 'listening-tls')
        assert recorded['result']['observed_only'] and not recorded['result']['live_transport_verified'] and not recorded['result']['network_requested']
        assert api_calls==before_calls and child.returncode is None
        assert 'BEGIN PRIVATE KEY' not in status_process.stdout and 'local-profile-google-fixture-token' not in status_process.stdout
        Path(reconnect).write_text('explicit fixture transport interruption; actual maintain must reconnect')
        await state(lambda value:value.get('restarted') is True and value.get('connected') is True)
        await send('shared');await send('second')
        await state(lambda value:value.get('parent_records')==2 and value.get('confirmed_outputs')==2)
        with sqlite3.connect(original_path) as db:
            assert db.execute('SELECT COUNT(*) FROM google_chat_originals').fetchone()[0]==2
            assert db.execute('SELECT COUNT(*) FROM google_chat_source_refusals').fetchone()[0]==1
        assert api_calls.count('native-message-create')==2 and api_calls.count('own-bot-membership')==2
        with sqlite3.connect('/var/lib/haos-gateway/inbox.db') as db:
            assert db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0]==2
        # Explicit local mission completion fixture, not an agent/inference run.
        # The actual controller journal, event projection, manifest RPC and
        # production output preparation must still carry its exact authority.
        from haos.store import MissionStore
        store=MissionStore(Path(reconnect).parent/'controller-private/missions.sqlite')
        try:
            mission=store.claim();assert mission is not None
            store.session(mission['id'],'fixture-session','fixture-stored-session')
            store.settle(mission['id'],'completed',result='Local completion fixture\nMEDIA:/agent/report.pdf')
        finally:store.close()
        await state(lambda value:value.get('confirmed_outputs')==4)
        assert api_calls.count('native-message-create')==4
        completed=next(row['text'] for row in payloads if 'Local completion fixture' in row.get('text',''))
        assert '/agent/report.pdf' not in completed and 'MEDIA:' not in completed and 'Result files require separate owner approval.' in completed
        with sqlite3.connect('/var/lib/haos-gateway/native-inbox.db') as db:
            assert db.execute('SELECT COUNT(*) FROM google_chat_output_manifests').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM google_chat_output_files').fetchone()[0]==0
        with sqlite3.connect(Path(reconnect).parent/'controller-private/missions.sqlite') as db:
            assert db.execute('SELECT COUNT(*) FROM gateway_output_manifests').fetchone()[0]==1
        publish({**policy,'bindings':[]})
        assert await asyncio.wait_for(child.wait(),10)==0
        assert json.loads(Path('/etc/haos/gateways.json').read_text())['bindings']==[]
        if scenario=='active':
            try:await send('after-withdrawal')
            except OSError:pass
            else:raise AssertionError('production service retained callback listener after Root withdrawal')
    return [
        'actual_production_serve_reads_matched_Root_publication_and_read_only_credentials_under_private_UID',
        'actual_serve_factory_maintain_native_SDK_TLS_original_relay_Unix_controller_and_native_reply_loop',
        'unknown_sender_retained_as_hash_refusal_without_controller_authority_or_reply',
        'actual_Root_private_UID_read_only_status_during_live_profile_lease_never_stops_service_requests_network_or_returns_credentials_and_does_not_claim_live_verification',
        'actual_production_maintain_reconnect_retains_two_unique_sources_and_two_replies_despite_replay',
        'actual_Root_fixture_completion_event_manifest_Unix_RPC_and_public_policy_output_projection_refuse_unapproved_file_export_without_leaking_agent_path',
        'actual_Root_atomic_republication_withdrawal_stops_production_service_and_callback_or_pull_without_resend']
