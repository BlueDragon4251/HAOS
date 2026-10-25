#!/usr/bin/env python3
"""Real loopback HTTP streaming, pinned ntfy adapter and durable source cursor."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from aiohttp import web
    from haos.gateway_ntfy import PreparedNtfyPolicy, install
    from haos.gateway_ntfy_transport import Subscription
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    cases = []
    async def exercise(directory):
        os.environ['HERMES_HOME'] = str(directory/'hermes'); os.environ['HERMES_SAFE_MODE'] = '1'
        from gateway.config import PlatformConfig
        from gateway.platform_registry import PlatformEntry
        from plugins.platforms.ntfy import adapter as module
        class Context:
            def register_platform(self, **kwargs): self.entry = PlatformEntry(**kwargs)
        context = Context(); module.register(context)
        native = NativeInbox(directory/'native.db', Redactor([]))
        config = {'version': 1, 'connectors': [{'id': 'test', 'platform': 'ntfy'}], 'bindings': [{
            'id': 'owner', 'connector': 'test', 'sender': 'private', 'chat': 'private', 'scope': '', 'thread': '',
            'identity': 'owner', 'capabilities': ['create'], 'since': int(time.time()*1000)-10000,
            'generation': 'a'*64, 'trust_topic_publishers': True}]}
        policy = lambda: PreparedNtfyPolicy(config)
        token = 'disposable-private-token'
        adapter = install(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True, extra={
            'topic': 'private', 'server': 'https://fixture.invalid', 'token': token}))))
        adapter._haos_native = SimpleNamespace(inbox=native, connector='test', policy=policy)
        accepted = []; early = asyncio.Event(); release = asyncio.Event(); held = asyncio.Event()
        def receive(event):
            if state.get('fail_once'):
                state['fail_once'] = False
                raise ConnectionError('disposable durable admission failure')
            accepted.append(event.message_id); early.set(); return True
        adapter.set_durable_message_handler(receive)
        state = {'status': 200, 'calls': [], 'mode': 'stream'}
        payloads = {}
        def event(identity): return payloads.setdefault(identity, {'event': 'message', 'topic': 'private', 'id': identity, 'time': int(time.time()), 'message': 'small immediate text'})
        async def stream(request):
            assert request.headers['Authorization'] == 'Bearer '+token
            assert request.query['poll'] == 'false'
            state['calls'].append(dict(request.query))
            if state['status'] != 200:
                return web.Response(status=state['status'], text=token, headers={'Retry-After': '19', 'Location': '/leak'})
            response = web.StreamResponse(headers={'Content-Type': 'application/x-ndjson'})
            await response.prepare(request)
            if state['mode'] == 'stream':
                await response.write(json.dumps(event('first')).encode()+b'\n')
                await release.wait()
                await response.write(json.dumps(event('second')).encode()+b'\n')
            elif state['mode'] == 'held':
                await response.write(json.dumps(event('running')).encode()+b'\n')
                await held.wait()
            elif state['mode'] == 'fresh': await response.write(json.dumps(event('fresh')).encode()+b'\n')
            elif state['mode'] == 'partial': await response.write(json.dumps(event('partial')).encode())
            elif state['mode'] == 'oversize': await response.write(b'A'*16385)
            elif state['mode'] == 'duplicate': await response.write(b'{"event":"message","topic":"private","id":"x","id":"y"}\n')
            elif state['mode'] == 'old':
                old=event('old'); old['time']=(config['bindings'][0]['since']//1000)-1
                await response.write(json.dumps(old).encode()+b'\n')
            if request.transport is not None and not request.transport.is_closing():
                await response.write_eof()
            return response
        leaked = []
        async def leak(request): leaked.append(True); return web.Response()
        app=web.Application(); app.router.add_get('/private/json',stream); app.router.add_get('/leak',leak)
        runner=web.AppRunner(app); await runner.setup(); site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
        target='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        subscriptions=[]
        def build():
            sub=Subscription(adapter); sub._target=target; subscriptions.append(sub); return sub
        try:
            sub=build(); task=asyncio.create_task(sub.receive_once())
            await asyncio.wait_for(early.wait(),3)
            assert not task.done() and accepted==['first'] and sub.state()['cursor']=='first'
            cases.append('small_actual_http_frame_admitted_before_held_terminal_stream_end')
            release.set(); await task
            assert accepted==['first','second'] and sub.state()['cursor']=='second'
            cases.append('actual_stream_cursor_tracks_last_committed_native_source')
            await sub.close(); native.close()
            native=NativeInbox(directory/'native.db',Redactor([])); adapter._haos_native.inbox=native
            sub=build(); assert sub.state()['cursor']=='second'
            cases.append('cursor_survives_actual_database_and_client_reopen')
            before=len(state['calls']); await sub.receive_once(); assert len(state['calls'])==before
            cases.append('persisted_reconnect_deadline_prevents_immediate_retry')
            await asyncio.sleep(2.1)
            state['mode']='partial'; await sub.receive_once()
            assert state['calls'][-1]['since']=='second' and sub.state()['cursor']=='second' and 'partial' not in accepted
            cases.append('actual_reconnect_supplies_durable_since_cursor_and_partial_line_cannot_advance_it')
            for code in [401,403,404,429,302]:
                adapter._token=token+str(code)
                # The credential used on the wire is the real adapter's token.
                token=adapter._token
                state['status']=code; sub=build(); before=len(state['calls']); await sub.receive_once()
                assert sub.state()['cursor']=='' and not leaked
                assert sub.state()['status']==({401:'authentication-denied',403:'authentication-denied',404:'source-unavailable',429:'rate-limited',302:'transport-unavailable'}[code])
                assert token not in repr(sub.state())
                await sub.receive_once(); assert len(state['calls'])==before+1
                cases.append('actual_http_safe_persisted_single_attempt_'+str(code))
            state['status']=200
            for mode in ['oversize','duplicate','old']:
                adapter._token+='x'; token=adapter._token; sub=build(); state['mode']=mode; await sub.receive_once()
                assert accepted==['first','second']
                assert sub.state()['cursor']==('old' if mode=='old' else '')
                cases.append('actual_http_'+mode+'_has_no_native_admission')
            adapter._token+='x'; token=adapter._token; sub=build()
            before=len(state['calls']); adapter._token+='rotated'
            try: await sub.receive_once()
            except PermissionError: pass
            else: raise AssertionError('superseded credential retained stream authority')
            assert len(state['calls'])==before
            cases.append('credential_rotation_invalidates_old_subscription_before_network')
            before=len(accepted)
            state['mode']='fresh'
            adapter._token+='x'; token=adapter._token; sub=build()
            native.db.execute("CREATE TRIGGER cursor_fault BEFORE UPDATE OF cursor ON ntfy_subscription BEGIN SELECT RAISE(ABORT, 'fixture cursor fault'); END")
            await sub.receive_once()
            assert sub.state()['cursor']=='' and len(accepted)==before
            assert native.db.execute("SELECT state FROM native_inbox WHERE message_id='fresh'").fetchone()[0]=='pending'
            cases.append('actual_sqlite_cursor_failure_preserves_committed_raw_pending_obligation')
            native.db.execute('DROP TRIGGER cursor_fault')
            calls_before_recovery=len(state['calls'])
            assert await sub.recover() and accepted[-1]=='fresh'
            assert len(state['calls'])==calls_before_recovery
            cases.append('retained_pending_input_recovers_without_another_http_fetch')
            adapter._token+='x'; token=adapter._token; sub=build()
            state['mode']='held'; state['fail_once']=True
            calls_before_run=len(state['calls'])
            run_task=asyncio.create_task(sub.run())
            async with asyncio.timeout(6):
                while ('running' not in accepted or len(state['calls'])<calls_before_run+2
                       or sub.state()['status']!='streaming'): await asyncio.sleep(.02)
            assert not run_task.done()
            cases.append('continuous_supervisor_reconnect_and_independent_pending_replay_recover_failed_admission')
            await sub.close(); await asyncio.wait_for(run_task,3); held.set()
            assert sub.client is None and not sub.workers
            cases.append('continuous_supervisor_close_cancels_real_stream_and_recovery_tasks')
            adapter._token+='x'; token=adapter._token; sub=build(); config['bindings']=[]
            before=len(state['calls'])
            try: await sub.receive_once()
            except PermissionError: pass
            else: raise AssertionError('revoked stream started')
            assert len(state['calls'])==before
            cases.append('revocation_prevents_new_http_request')
        finally:
            held.set()
            for sub in subscriptions: await sub.close()
            native.close(); await runner.cleanup()
    with tempfile.TemporaryDirectory(prefix='haos-ntfy-stream-') as value: awaitable=exercise(Path(value)); asyncio.run(awaitable)
    receipt={'passed':len(cases),'cases':cases,'actual_loopback_http_and_native_decoder':True,'loopback_endpoint_replacement_only_in_fixture':True,
             'public_gateway_enabled':False,'external_subscription_or_publish':False,'tls_live_account_accepted':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n'); print(json.dumps(receipt))


if __name__=='__main__': main()
