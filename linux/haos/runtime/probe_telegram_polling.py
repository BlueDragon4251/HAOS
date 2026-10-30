#!/usr/bin/env python3
"""Actual PTB polling offsets must follow native HAOS SQLite admission."""
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from urllib.parse import parse_qs

from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    from haos.gateway_runtime import build_adapter, adapter_envelope, native_authorization_prefilter
    from haos.gateway import GatewayPolicy
    from haos.gateway_relay import RelayInbox
    from haos.redaction import Redactor
    from telegram.ext import Application
    from plugins.platforms.telegram.update_admission import TelegramApplication
    held_mode = len(sys.argv) == 4 and sys.argv[3] == 'held'
    if len(sys.argv) == 4: assert held_mode
    policy = GatewayPolicy({'version': 1, 'connectors': [{'id': 'bot', 'platform': 'telegram'}], 'bindings': [
        {'id': 'paired', 'connector': 'bot', 'sender': '42', 'chat': '42', 'scope': '', 'thread': '',
         'identity': 'principal', 'capabilities': ['create', 'read']}]})
    state = {'offsets': [], 'acks': 0, 'local_failures': 0, 'stopping': False, 'cancelled_fixture_polls': 0}; failures = []
    updates = [{'update_id': uid, 'message': {'message_id': uid+100, 'date': 1700000000,
        'chat': {'id': 42, 'type': 'private', 'first_name': 'Fixture'},
        'from': {'id': sender, 'is_bot': False, 'first_name': 'Fixture'}, 'text': 'durable fixture'}}
        for uid, sender in ((11, 42), (12, 43))]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'relay.db'
        class BotAPI(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                try:
                    values = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                    method = self.path.rsplit('/', 1)[-1].lower()
                    if method == 'getme':
                        result = {'id': 123456, 'is_bot': True, 'username': 'fixture_bot', 'first_name': 'Fixture'}
                    elif method == 'deletewebhook':
                        assert values.get('drop_pending_updates', ['false']) == ['false'], 'pending updates discarded'
                        result = True
                    elif method == 'getupdates':
                        offset = int(values.get('offset', ['0'])[0]); state['offsets'].append(offset)
                        if offset >= 13:
                            with sqlite3.connect(path) as connection:
                                assert connection.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1, 'SDK confirmed before durable admission'
                            state['acks'] += 1; result = []
                            time.sleep(0.02)
                        else: result = updates
                    else:
                        raise AssertionError('unexpected native Bot API operation: ' + method)
                    body = json.dumps({'ok': True, 'result': result}).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body))); self.end_headers()
                    try: self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        if not state['stopping']: raise
                        state['cancelled_fixture_polls'] += 1
                except BaseException as error:
                    failures.append(type(error).__name__); raise
        async def run(port):
            old_home = os.environ.get('HERMES_HOME'); os.environ['HERMES_HOME'] = str(Path(directory)/'hermes')
            hermes = Path(os.environ['HERMES_HOME']); hermes.mkdir()
            legacy = hermes/'telegram_update_receipts_123456.json'
            old_receipts = json.dumps({'update_ids': {'11': time.time()}}).encode()
            legacy.write_bytes(old_receipts)
            inbox = RelayInbox(path, Redactor())
            if not held_mode:
                inbox.db.execute("CREATE TRIGGER fixture_disk_failure BEFORE INSERT ON inbox BEGIN SELECT RAISE(ABORT, 'fixture unavailable'); END")
            adapter = build_adapter('telegram', {'token': '123456:' + 'x'*35})
            adapter.set_authorization_check(lambda user_id, chat_type=None, chat_id=None, **kwargs:
                native_authorization_prefilter(policy, 'bot', user_id, chat_id, **kwargs))
            def receive(event):
                try: inbox.admit(policy, 'bot', adapter_envelope(event, 'telegram'))
                except sqlite3.DatabaseError:
                    state['local_failures'] += 1; raise
                return True
            adapter.set_durable_message_handler(receive)
            app = (Application.builder().token(adapter.config.token).base_url(f'http://127.0.0.1:{port}/bot')
                .application_class(TelegramApplication, {'adapter': adapter}).build())
            adapter._app = app; adapter._bot = app.bot; adapter._register_handlers(app)
            try:
                await app.initialize(); await app.start()
                if held_mode: adapter._mark_disconnected()
                else: adapter._mark_connected()
                # Exercise the real native conflict path's requested drop=True.
                # The HAOS hook must keep pending updates and use actual PTB.
                await adapter._start_polling_once(app, drop_pending_updates=True, error_callback=None, schedule_verifier=False)
                deadline = time.monotonic()+15
                def blocked():
                    return bool(adapter._held_inbound_events) if held_mode else state['local_failures'] == 1
                while not blocked() and time.monotonic() < deadline: await asyncio.sleep(0.01)
                assert blocked() and state['acks'] == 0
                assert all(value == 0 for value in state['offsets']), 'failed native dispatch already advanced polling offset'
                assert inbox.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 0
                if held_mode: adapter._mark_connected()
                else: inbox.db.execute('DROP TRIGGER fixture_disk_failure')
                while not state['acks'] and time.monotonic() < deadline: await asyncio.sleep(0.01)
                assert state['acks'] and not failures
                assert state['offsets'].count(0) >= 2, 'actual SDK did not retry the unconfirmed batch'
                row = inbox.db.execute('SELECT envelope FROM inbox').fetchone()
                assert json.loads(row[0])['sender'] == '42', 'unpaired sender reached durable admission'
            finally:
                state['stopping'] = True
                if app.updater.running: await app.updater.stop()
                if app.running: await app.stop()
                await app.shutdown()
                task = adapter._update_receipt_flush
                if task is not None: await task
                assert legacy.read_bytes() == old_receipts, 'old native receipts were overwritten'
                inbox.close()
                if old_home is None: os.environ.pop('HERMES_HOME', None)
                else: os.environ['HERMES_HOME'] = old_home
        with serving(ThreadingHTTPServer(('127.0.0.1', 0), BotAPI)) as port:
            asyncio.run(run(port))
    assert not failures, failures
    receipt = {'native_disconnect_holds_then_reconnects': held_mode, 'native_drop_pending_request_forced_false': True,
        'actual_ptb_getupdates_offsets': state['offsets'], 'real_sqlite_insert_failure_then_sdk_retry': state['local_failures'],
        'offset_advanced_only_after_independent_sqlite_reader_saw_commit': True, 'unknown_sender_not_admitted': True,
        'shutdown_cancelled_fixture_polls': state['cancelled_fixture_polls'],
        'actual_native_adapter_text_codec_and_application_handlers': True, 'external_telegram_connected': False, 'legacy_native_receipts_preserved_and_not_trusted_for_admission': True,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__), root/'haos/gateway_telegram.py', root/'haos/gateway_ingress.py', root/'haos/gateway_runtime.py')}}
    Path(sys.argv[2]).write_text(json.dumps(receipt, indent=2)+'\n'); print(json.dumps(receipt))


if __name__ == '__main__': main()
