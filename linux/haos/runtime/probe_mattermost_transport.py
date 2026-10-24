#!/usr/bin/env python3
"""Actual pinned Mattermost formatting and aiohttp POST boundary, loopback only."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from aiohttp import ClientSession, web
    from gateway.config import PlatformConfig
    from plugins.platforms.mattermost.adapter import MattermostAdapter
    from haos.gateway_mattermost import install_api, install_post_builder, send_native

    async def exercise():
        chat, thread, receipt = 'c' * 26, 't' * 26, 'p' * 26
        state = {'status': 201, 'wrong': False, 'calls': [], 'leaked': 0}
        async def endpoint(request):
            state['calls'].append((request.method, request.path))
            assert request.headers['Authorization'] == 'Bearer ' + 'x' * 26
            if request.path.endswith('users/me'):
                return web.json_response({'id': 'b' * 26})
            assert request.path == '/api/v4/posts' and request.method == 'POST'
            body = await request.json()
            assert body['channel_id'] == chat and body.get('root_id', '') == state.get('thread', '')
            assert body['props'] == {'disable_mentions': True} and not body.get('file_ids')
            if state.get('reject_second') and len(state['calls']) == state['reject_second']:
                return web.json_response({'message':'denied'},status=403)
            if state.get('body') is not None:
                return web.Response(body=state['body'], content_type='application/json')
            if state['status'] == 302:
                return web.Response(status=302, headers={'Location': '/leak'})
            if state['status'] != 201:
                return web.json_response({'message': 'invalid root_id missing post'}, status=state['status'])
            return web.json_response({'id': receipt, 'channel_id': 'z'*26 if state['wrong'] else chat,
                                     'root_id': body.get('root_id', '')}, status=201)
        async def leak(request):
            state['leaked'] += 1
            raise AssertionError('native credential-bearing redirect must never be followed')
        app = web.Application(); app.router.add_route('*', '/api/v4/{tail:.*}', endpoint)
        app.router.add_route('*', '/leak', leak)
        runner = web.AppRunner(app); await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
        port = site._server.sockets[0].getsockname()[1]
        adapter = MattermostAdapter(PlatformConfig(enabled=True, token='x'*26,
            extra={'url': 'https://owner.invalid', 'reply_mode': 'thread'}))
        # Only this fixture substitutes the owner HTTPS origin with loopback.
        adapter._base_url = f'http://127.0.0.1:{port}'
        install_post_builder(install_api(adapter, lambda path: path == 'users/me'))
        cases = []
        try:
            async with ClientSession(trust_env=False) as session:
                adapter._session = session
                assert (await adapter._api_get('users/me'))['id'] == 'b'*26
                cases.append('actual_native_authenticated_read')
                for path in ('files/abc', '../users/me', 'users/me?token=x', 'channels/'+'c'*26):
                    before = len(state['calls'])
                    try: await adapter._api_get(path)
                    except PermissionError: pass
                    else: raise AssertionError('read must be refused')
                    assert len(state['calls']) == before
                cases.append('unapproved_reads_refused_before_http')
                try: await adapter._api_post('posts', {'channel_id': chat, 'message': 'no authority'})
                except PermissionError: pass
                else: raise AssertionError('ambient POST authority')
                cases.append('writes_require_private_send_context')
                for exact in ('', thread):
                    state['thread'] = exact
                    result, observed = await send_native(adapter, MattermostAdapter.send, chat, 'actual native text', exact)
                    assert result.success and result.message_id == receipt
                    assert observed['receipts'] == [receipt] and not observed['ambiguous']
                    cases.append('exact_native_thread' if exact else 'exact_native_flat')
                for status in (400, 401, 403, 404, 429, 500, 302):
                    state['status'] = status; before = len(state['calls'])
                    result, observed = await send_native(adapter, MattermostAdapter.send, chat, 'native refusal', thread)
                    assert not result.success and observed['statuses'] == [status]
                    assert len(state['calls']) == before+1 and state['leaked'] == 0
                    cases.append('native_single_post_status_' + str(status))
                state['status'] = 201; state['wrong'] = True
                result, observed = await send_native(adapter, MattermostAdapter.send, chat, 'wrong receipt', thread)
                assert not result.success and observed['ambiguous'] and not observed['receipts']
                cases.append('wrong_route_success_receipt_uncertain')
                state['wrong'] = False; before = len(state['calls'])
                result, observed = await send_native(adapter, MattermostAdapter.send, chat, 'a'*4100, thread)
                assert result.success and len(state['calls']) == before+2 and len(observed['receipts']) == 2
                cases.append('actual_native_multichunk_preserves_exact_route')
                state['reject_second'] = len(state['calls'])+2
                result, observed = await send_native(adapter, MattermostAdapter.send, chat, 'b'*4100, thread)
                assert not result.success and observed['statuses'] == [201,403]
                assert len(observed['receipts']) == 1 and observed['ambiguous']
                state.pop('reject_second')
                cases.append('partial_native_delivery_keeps_uncertainty')
                other = MattermostAdapter(adapter.config)
                other._base_url = adapter._base_url; other._session = session
                install_post_builder(install_api(other, lambda path: False))
                async def cross_instance(_adapter, *args, **kwargs):
                    return await MattermostAdapter.send(other, chat, 'cross-instance post')
                before = len(state['calls'])
                try: await send_native(adapter, cross_instance, chat, 'forged context', thread)
                except PermissionError: pass
                else: raise AssertionError('send context must be bound to its private adapter')
                assert len(state['calls']) == before
                cases.append('different_adapter_cannot_borrow_send_context')
                for name, body in [('malformed_json', b'{'), ('oversized_json', b' '*(1024*1024+1))]:
                    state['body'] = body
                    result, observed = await send_native(adapter, MattermostAdapter.send, chat, 'bounded response', thread)
                    assert not result.success and observed['ambiguous'] and not observed['receipts']
                    cases.append(name + '_uncertain')
        finally:
            await runner.cleanup()
        return cases

    with tempfile.TemporaryDirectory() as directory:
        os.environ['HERMES_HOME'] = directory
        cases = asyncio.run(exercise())
    result=json.dumps({'cases': cases, 'passed': len(cases), 'external_connections': False,
                      'public_gateway_enabled': False}, indent=2)+'\n'
    if len(sys.argv)>2: Path(sys.argv[2]).write_text(result)
    else: print(result,end='')


if __name__ == '__main__': main()
