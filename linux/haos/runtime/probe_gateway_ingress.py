#!/usr/bin/env python3
"""Pinned native dispatch → exact HAOS policy → durable SQLite, without transports."""
import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import sys
import tempfile


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from haos.gateway_runtime import adapter_envelope, build_adapter, native_authorization_prefilter
    from haos.gateway import GatewayPolicy
    from haos.gateway_relay import RelayInbox
    from haos.redaction import Redactor
    from gateway.config import Platform
    from gateway.platforms.event import MessageEvent, MessageType
    from gateway.session import SessionSource
    results = []
    async def run(directory):
        os.environ['HOME'] = directory
        os.environ['HERMES_HOME'] = str(Path(directory) / '.hermes')
        home = Path(os.environ['HERMES_HOME'])
        unknown_plugin = home / 'plugins/haos-unapproved-fixture'
        unknown_plugin.mkdir(parents=True)
        (unknown_plugin / 'plugin.yaml').write_text('name: haos-unapproved-fixture\nversion: 1.0.0\nkind: standalone\n')
        (unknown_plugin / '__init__.py').write_text("from pathlib import Path\nPath(__file__).with_name('UNEXPECTED_IMPORT').write_text('fixture')\ndef register(ctx): pass\n")
        (home / 'config.yaml').write_text(json.dumps({'plugins': {'enabled': ['haos-unapproved-fixture']}}))
        for name in ('telegram', 'discord'):
            adapter = build_adapter(name, {'token': '123456:' + 'x' * 35})
            if name == 'telegram':
                replacement = build_adapter(name, {'token': '123456:' + 'x' * 35})
                assert replacement._update_receipt_dir == adapter._update_receipt_dir
                assert adapter._update_receipt_dir.name == 'haos-durable-v1'
            policy = GatewayPolicy({'version': 1, 'connectors': [{'id': name, 'platform': name}], 'bindings': [
                {'id': 'paired', 'connector': name, 'sender': '42', 'chat': '42', 'scope': '', 'thread': '',
                 'identity': 'principal', 'capabilities': ['create', 'read']}]})
            inbox = RelayInbox(Path(directory) / (name + '.db'), Redactor())
            def event(sender='42', text='fixture'):
                return MessageEvent(text=text, message_type=MessageType.TEXT,
                    source=SessionSource(platform=Platform(name), chat_id='42', user_id=sender), message_id='11')
            # Native background/debounce semantics are intentional upstream,
            # but cannot be used as HAOS's durable admission acknowledgement.
            original = type(adapter).__mro__[1]
            plain = original(adapter.config)
            baseline = []
            async def native_handler(value):
                baseline.append(value)
            plain.set_message_handler(native_handler)
            before_native = set(asyncio.all_tasks())
            await plain.handle_message(event())
            assert not baseline, 'pinned native background dispatch contract changed'
            for task in set(asyncio.all_tasks()) - before_native:
                task.cancel()
            await asyncio.gather(*(set(asyncio.all_tasks()) - before_native), return_exceptions=True)
            before_native = set(asyncio.all_tasks())
            plain._enqueue_text_event(event())
            assert not baseline and plain._pending_text_batches
            for task in set(asyncio.all_tasks()) - before_native:
                task.cancel()
            await asyncio.gather(*(set(asyncio.all_tasks()) - before_native), return_exceptions=True)
            def admit(value):
                inbox.admit(policy, name, adapter_envelope(value, name))
                return True
            adapter.set_durable_message_handler(admit)
            before = set(asyncio.all_tasks())
            first = event()
            await adapter.handle_message(first)
            assert first._gateway_accepted is True and inbox.next(policy) is not None
            assert set(asyncio.all_tasks()) == before, 'durable ingress was deferred into a background task'
            second = event()
            adapter._enqueue_text_event(second)
            assert second._gateway_accepted is True
            assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
            assert set(asyncio.all_tasks()) == before and not adapter._pending_text_batches
            denied = event('unknown')
            try:
                await adapter.handle_message(denied)
            except PermissionError:
                pass
            else:
                raise AssertionError('unknown sender was admitted')
            assert denied._gateway_accepted is False
            from haos.store import Conflict
            changed = event(text='changed replay')
            try:
                adapter._enqueue_text_event(changed)
            except Conflict:
                pass
            else:
                raise AssertionError('changed replay was accepted')
            assert changed._gateway_accepted is False
            # Actual SQLite readonly failure, not a mocked persistence result.
            inbox.close()
            inbox.db = sqlite3.connect('file:' + str(Path(directory) / (name + '.db')) + '?mode=ro',
                uri=True, isolation_level=None)
            inbox.db.row_factory = sqlite3.Row
            failed = event()
            failed.message_id = '12'
            try:
                adapter._enqueue_text_event(failed)
            except sqlite3.OperationalError as error:
                assert error.sqlite_errorcode == sqlite3.SQLITE_READONLY
            else:
                raise AssertionError('failed durable commit was deferred or accepted')
            assert failed._gateway_accepted is False
            inbox.close()
            inbox = RelayInbox(Path(directory) / (name + '.db'), Redactor())
            async def deferred(_value):
                return True
            try:
                adapter.set_durable_message_handler(deferred)
            except TypeError:
                pass
            else:
                raise AssertionError('async durable handler accepted')
            adapter.set_durable_message_handler(lambda value: deferred(value))
            try:
                await adapter.handle_message(event())
            except TypeError:
                pass
            else:
                raise AssertionError('deferred admission receipt accepted')
            adapter.set_durable_message_handler(admit)
            # No arbitrary plugin handler factories or action handlers may run.
            from hermes_cli import plugins
            from hermes_cli.plugins_manifest import parse_manifest_file
            assert parse_manifest_file(unknown_plugin / 'plugin.yaml', unknown_plugin, 'user', '') is not None
            assert os.environ['HERMES_SAFE_MODE'] == '1'
            manager = plugins.PluginManager(scope_key=str(home))
            manager.discover_and_load(force=True)
            assert not manager._plugins and not (unknown_plugin / 'UNEXPECTED_IMPORT').exists()
            previous = plugins.get_plugin_manager
            def forbidden():
                raise AssertionError('native transport attempted arbitrary plugin discovery')
            plugins.get_plugin_manager = forbidden
            try:
                adapter._wire_plugin_handlers(object())
                adapter.rewire_plugin_handlers()
                adapter._register_plugin_action_handlers()
            finally:
                plugins.get_plugin_manager = previous
            adapter.set_authorization_check(lambda user, chat_type=None, chat_id=None, **kwargs:
                native_authorization_prefilter(policy, name, user, chat_id, **kwargs))
            if name == 'telegram':
                old = os.environ.get('GATEWAY_ALLOW_ALL_USERS')
                os.environ['GATEWAY_ALLOW_ALL_USERS'] = 'true'
                try:
                    assert adapter._is_callback_user_authorized('42', chat_id='42', chat_type='dm') is True
                    assert adapter._is_callback_user_authorized('unknown', chat_id='42', chat_type='dm') is False
                    assert adapter._is_callback_user_authorized('42', chat_id='other', chat_type='dm') is False
                    assert adapter._is_callback_user_authorized('42', chat_id='42', chat_type='dm', thread_id='other') is False
                    from telegram import Update
                    def telegram_message(user):
                        return Update.de_json({'update_id': 1, 'message': {'message_id': 11, 'date': 1700000000,
                            'chat': {'id': 42, 'type': 'private', 'first_name': 'Fixture'},
                            'from': {'id': user, 'is_bot': False, 'first_name': 'Fixture'}, 'text': 'fixture'}}, bot=None).effective_message
                    assert adapter._is_user_authorized_from_message(telegram_message(42)) is True
                    assert adapter._is_user_authorized_from_message(telegram_message(43)) is False
                    policy.bindings.clear()
                    assert adapter._is_callback_user_authorized('42', chat_id='42', chat_type='dm') is False
                    assert adapter._is_user_authorized_from_message(telegram_message(42)) is False
                finally:
                    if old is None:
                        os.environ.pop('GATEWAY_ALLOW_ALL_USERS', None)
                    else:
                        os.environ['GATEWAY_ALLOW_ALL_USERS'] = old
            else:
                assert adapter._is_sender_authorized('42', chat_id='42') is False
            inbox.close()
            reopened = RelayInbox(Path(directory) / (name + '.db'), Redactor())
            assert reopened.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
            reopened.close()
            assert not adapter.is_connected
            results.append(name)
    with tempfile.TemporaryDirectory(prefix='haos-native-ingress-') as directory:
        asyncio.run(run(directory))
    result = {'actual_native_adapter_dispatch_cases': results, 'synchronous_durable_admission_and_reopen': True,
        'native_background_and_debounce_baseline_verified': True,
        'no_background_or_debounce_mission_dispatch': True, 'exact_sender_and_native_prefilter_revocation': True,
        'unknown_native_plugin_discovery_disabled': True, 'storage_failure_not_accepted': True, 'actual_readonly_sqlite_and_changed_replay_refused': True,
        'transport_connected_or_external_delivery_tested': False,
        'native_source_sha256': [{'module': name, 'sha256': hashlib.sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()} for name in
            ('gateway.platforms.base', 'plugins.platforms.telegram.adapter', 'plugins.platforms.discord.adapter')],
        'source_sha256': {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), root / 'haos/gateway_ingress.py',
            root / 'haos/gateway_runtime.py', root / 'haos/gateway.py', root / 'haos/gateway_relay.py')}}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
