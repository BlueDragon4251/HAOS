#!/usr/bin/env python3
"""Real native Telegram SDK sends must not replay ambiguity or change owner thread."""
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

from probe_http_provider_matrix import serving


def main():
    root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))
    from haos.gateway_runtime import build_adapter,delivery_metadata
    from haos.gateway import GatewayPolicy, GatewayEngine
    from haos.store import MissionStore
    from telegram.ext import Application
    from plugins.platforms.telegram.update_admission import TelegramApplication
    policy = GatewayPolicy({'version': 1, 'connectors': [{'id': 'bot', 'platform': 'telegram'}], 'bindings': [
        {'id': 'paired', 'connector': 'bot', 'sender': '42', 'chat': '-10042', 'scope': '', 'thread': '7',
         'identity': 'principal', 'capabilities': ['create', 'read']}]})
    state = {'case': '', 'sends': []}; failures, results = [], []
    class BotAPI(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            try:
                form = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                method = self.path.rsplit('/', 1)[-1].lower()
                status = 200
                if method == 'getme':
                    body = {'ok': True, 'result': {'id': 123456, 'is_bot': True, 'username': 'fixture_bot', 'first_name': 'Fixture'}}
                elif method == 'sendmessage':
                    state['sends'].append(form)
                    case = state['case']
                    if case in {'revoke-between-chunks','revoke-before-format-fallback'} and len(state['sends'])==1:
                        policy.bindings['paired']['generation']='b'*64
                    if case == 'read-disconnect':
                        self.close_connection = True; return
                    if case == 'server-parser-error':
                        status=500; body={'ok': False, 'error_code': 500, 'description': 'parse upstream failed'}
                    elif case=='redirect-307':
                        status=307;body={'ok':False,'error_code':307,'description':'fixture redirect'}
                    elif case == 'missing-thread':
                        status=400; body={'ok': False, 'error_code': 400, 'description': 'Bad Request: message thread not found'}
                    elif case == 'rate-limit':
                        status=429; body={'ok': False, 'error_code': 429, 'description': 'Too Many Requests', 'parameters': {'retry_after': 120}}
                    elif case == 'forbidden':
                        status=403; body={'ok': False, 'error_code': 403, 'description': 'Forbidden: bot blocked'}
                    elif case == 'malformed-receipt': body={'ok': True, 'result': {}}
                    elif case in {'parse-rejected','revoke-before-format-fallback'} and len(state['sends']) == 1:
                        status=400; body={'ok': False, 'error_code': 400, 'description': "Bad Request: can't parse entities"}
                    else:
                        body={'ok': True, 'result': {'message_id': (0 if case=='invalid-id' else 55), 'date': 1700000000,
                            'chat': {'id': -10042, 'type': 'supergroup', 'title': 'Fixture'}, 'text': 'fixture'}}
                else: raise AssertionError('unexpected native operation: ' + method)
                wire=json.dumps(body).encode(); self.send_response(status); self.send_header('Content-Type','application/json')
                if status==307:self.send_header('Location','/leak')
                self.send_header('Content-Length',str(len(wire))); self.end_headers(); self.wfile.write(wire)
            except BaseException as error:
                failures.append(type(error).__name__); raise
    async def exercise(directory, port, server):
        old_home=os.environ.get('HERMES_HOME'); os.environ['HERMES_HOME']=str(Path(directory)/'hermes')
        try:
            for case, expected in [('read-disconnect','uncertain'), ('server-parser-error','uncertain'), ('missing-thread','failed'), ('rate-limit','pending'),
                    ('forbidden','failed'), ('malformed-receipt','uncertain'), ('invalid-id','uncertain'), ('parse-rejected','delivered'), ('success','delivered'),
                    ('forged-binding','failed'),('missing-binding','failed'),('policy-unavailable','failed'),('no-read-grant','failed'),
                    ('revoke-between-chunks','uncertain'),('revoke-before-format-fallback','failed'),('redirect-307','uncertain'),('connect-refused','pending')]:
                state.update(case=case,sends=[])
                if case=='no-read-grant':policy.bindings['paired']['capabilities']=['create']
                store=MissionStore(Path(directory)/(case+'.db')); engine=GatewayEngine(store)
                await engine.receive(policy,'bot',{'platform':'telegram','sender':'42','chat':'-10042','scope':'','thread':'7',
                    'message_id':'101','is_bot':False,'text':'fixture mission'},None)
                delivery=engine.next_delivery(policy)
                adapter=build_adapter('telegram',{'token':'123456:'+'x'*35})
                def current():
                    if state['case']=='policy-unavailable':raise PermissionError('fixture owner policy unavailable')
                    return policy
                adapter._haos_native=SimpleNamespace(connector='bot',policy=current)
                app=(Application.builder().token(adapter.config.token).base_url(f'http://127.0.0.1:{port}/bot')
                    .application_class(TelegramApplication,{'adapter':adapter}).build())
                adapter._app=app;adapter._bot=app.bot
                try:
                    await app.initialize(); adapter._mark_connected()
                    if case=='connect-refused':
                        server.shutdown(); server.server_close()
                    metadata=delivery_metadata(delivery,'telegram')
                    if case=='forged-binding':metadata['haos_binding']['binding_digest']='0'*64
                    if case=='missing-binding':metadata.pop('haos_binding')
                    receipt=await adapter.send(delivery['chat'],'r'*9000 if case=='revoke-between-chunks' else delivery['content'],
                        reply_to=delivery['reply_to'],metadata=metadata)
                    assert len(state['sends']) == (2 if case=='parse-rejected' else 0 if case in {'connect-refused','forged-binding','missing-binding','policy-unavailable','no-read-grant'} else 1), (case,len(state['sends']),'native send escaped current owner authority or repeated ambiguity')
                    assert all(row.get('message_thread_id')==['7'] and row['chat_id']==['-10042'] for row in state['sends']), 'native send escaped the owner thread'
                    from haos.gateway_delivery import delivery_result
                    result=delivery_result(receipt)
                    if case.startswith('revoke-'):policy.bindings['paired'].pop('generation')
                    engine.acknowledge(policy,delivery['id'],{**result,'attempt':delivery['attempt']})
                    assert store.db.execute('SELECT state FROM gateway_outbox').fetchone()[0]==expected
                    store.close();store=MissionStore(Path(directory)/(case+'.db'));engine=GatewayEngine(store)
                    if expected=='pending':
                        retry=engine.next_delivery(policy,time.time()+121)
                        assert retry['id']==delivery['id'] and retry['attempt']==2
                    else: assert engine.next_delivery(policy,time.time()+121) is None
                    assert not failures
                    results.append({'case':case,'http_send_attempts':len(state['sends']),'durable_state':expected})
                finally:
                    await app.shutdown(); store.close()
                    if case=='no-read-grant':policy.bindings['paired']['capabilities']=['create','read']
        finally:
            if old_home is None: os.environ.pop('HERMES_HOME',None)
            else: os.environ['HERMES_HOME']=old_home
    with tempfile.TemporaryDirectory() as directory:
        server=ThreadingHTTPServer(('127.0.0.1',0),BotAPI)
        with serving(server) as port:
            asyncio.run(exercise(directory,port,server))
    assert not failures
    receipt={'actual_native_telegram_send_cases':results,'actual_sdk_and_sqlite_reopen':True,'no_thread_downgrade_or_ambiguous_replay':True,
        'external_messages_sent':False,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),root/'haos/gateway_telegram.py',root/'haos/gateway_delivery.py',root/'haos/gateway_ingress.py',root/'haos/gateway_runtime.py')}}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
