#!/usr/bin/env python3
"""Real pinned ntfy decoder after independent capture and actual SQLite commit."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from haos.gateway import GatewayPolicy
    from haos.gateway_ntfy import PreparedNtfyPolicy, snapshot, envelope, capture, dispatch_stored, install
    from haos.gateway_raw import NativeInbox
    from haos.gateway_ingress import durable_adapter
    from haos.redaction import Redactor
    cases = []
    async def exercise(directory):
        os.environ['HERMES_HOME'] = str(directory / 'hermes')
        os.environ['HERMES_SAFE_MODE'] = '1'
        from gateway.config import PlatformConfig
        from gateway.platform_registry import PlatformEntry
        from plugins.platforms.ntfy import adapter as module
        class Context:
            def register_platform(self, **kwargs):
                self.entry = PlatformEntry(**kwargs)
        context = Context()
        module.register(context)
        native = NativeInbox(directory / 'native.db', Redactor([]))
        config = {'version': 1, 'connectors': [{'id': 'fixture', 'platform': 'ntfy'}], 'bindings': [
            {'id': 'owner', 'connector': 'fixture', 'sender': 'private-in', 'chat': 'private-in', 'scope': '', 'thread': '',
             'identity': 'owner', 'capabilities': ['create'], 'since': int(time.time()*1000)-10000,
             'generation': 'a'*64, 'trust_topic_publishers': True}]}
        policy = lambda: PreparedNtfyPolicy(config)
        def denied(action):
            try: action()
            except (ValueError, PermissionError): return
            raise AssertionError('unsafe ntfy authority unexpectedly admitted')
        assert GatewayPolicy(config).bindings==policy().bindings
        cases.append('public_policy_uses_same_exact_topic_and_explicit_publisher_trust')
        for field, value in [('trust_topic_publishers', False), ('sender', 'forged-name'), ('thread', 'invented'), ('scope', 'invented')]:
            changed = copy.deepcopy(config); changed['bindings'][0][field] = value
            denied(lambda: PreparedNtfyPolicy(changed)); cases.append('explicit_topic_boundary_'+field)
        adapter = install(durable_adapter(context.entry.adapter_factory(PlatformConfig(enabled=True, extra={
            'topic': 'private-in', 'server': 'https://fixture.invalid', 'token': 'local-only-token'}))))
        adapter._haos_native = SimpleNamespace(inbox=native, connector='fixture', policy=policy)
        accepted = []
        fail = [False]
        def receive(event):
            with sqlite3.connect(directory / 'native.db') as observer:
                assert observer.execute('SELECT state FROM native_inbox WHERE message_id=?', (event.message_id,)).fetchone() == ('processing',)
            assert event.source.user_id == 'private-in' and event.source.chat_id == 'private-in'
            if fail[0]: raise ConnectionError('disposable local interruption')
            accepted.append(event.text)
            return True
        adapter.set_durable_message_handler(receive)
        base = {'event': 'message', 'id': 'event1', 'time': int(time.time()), 'topic': 'private-in', 'message': '  native text  ',
                'title': 'Administrator', 'sender': 'pretend-owner', 'user': 'root'}
        authority = snapshot(policy(), 'fixture')
        for change in [{'topic': 'unapproved'}, {'id': ''}, {'time': True}, {'attachment': {}}, {'actions': []},
                       {'click': 'https://external.invalid'}, {'encoding': 'base64'}, {'tags': ['hermes-agent']}, {'message': 'é'*2049}]:
            assert envelope({**base, **change}, 'private-in') is None
            cases.append('invalid_native_source_'+next(iter(change)))
        assert capture(adapter,{**base,'id':adapter._token},authority) is None
        cases.append('reflected_private_token_cannot_become_public_native_source_id')
        original_token=adapter._token;adapter._token='u:p'
        assert capture(adapter,{**base,'id':'dTpw'},authority) is None
        adapter._token=original_token
        cases.append('reflected_basic_credential_cannot_become_public_native_source_id')
        key = capture(adapter, base, authority)
        assert await dispatch_stored(adapter, key)
        assert accepted == ['native text']
        cases.append('actual_native_decoder_runs_after_observable_commit_and_ignores_forged_publisher_identity')
        assert not await dispatch_stored(adapter, key) and accepted == ['native text']
        cases.append('durable_replay_does_not_repeat_native_admission')
        try: await adapter._on_message(base)
        except PermissionError: pass
        else: raise AssertionError('native callback bypassed capture')
        cases.append('direct_native_callback_has_no_authority')
        stale = {**base, 'id': 'old', 'time': (config['bindings'][0]['since']//1000)-1}
        denied(lambda: capture(adapter, stale, authority)); cases.append('pregrant_original_refused')
        denied(lambda: capture(adapter, {**base, 'time': int(time.time())+301}, authority)); cases.append('future_original_refused')
        changed = {**base, 'id': 'changed'}
        config['bindings'][0]['generation'] = 'b'*64
        denied(lambda: capture(adapter, changed, authority)); cases.append('old_stream_snapshot_cannot_inherit_new_grant')
        key = capture(adapter, changed, snapshot(policy(), 'fixture'))
        retry_event = {**base, 'id': 'retry'}
        retry_key = capture(adapter, retry_event, snapshot(policy(), 'fixture'))
        fail[0] = True
        try: await dispatch_stored(adapter, retry_key)
        except ConnectionError: pass
        else: raise AssertionError('failed durable admission was swallowed')
        assert native.db.execute('SELECT state,attempt FROM native_inbox WHERE id=?', (retry_key,)).fetchone()[:] == ('pending', 1)
        cases.append('native_decode_failure_retains_pending_obligation')
        native.close()
        native = NativeInbox(directory / 'native.db', Redactor([]))
        adapter._haos_native.inbox = native
        fail[0] = False
        await asyncio.sleep(2.1)
        assert await dispatch_stored(adapter, retry_key)
        assert accepted == ['native text', 'native text']
        cases.append('actual_sqlite_reopen_and_elapsed_retry_bypass_native_ttl_dedup')
        assert not await dispatch_stored(adapter, retry_key)
        cases.append('recovered_native_admission_is_idempotent')
        config['bindings'] = []
        assert not await dispatch_stored(adapter, key)
        cases.append('revoked_retained_source_never_reaches_native_decoder')
        native.close()
    with tempfile.TemporaryDirectory(prefix='haos-ntfy-ingress-') as value:
        asyncio.run(exercise(Path(value)))
    receipt = {'passed': len(cases), 'cases': cases, 'actual_pinned_decoder': True,
               'public_gateway_enabled': True, 'external_connections': False, 'live_delivery_accepted': False}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt))


if __name__ == '__main__': main()
