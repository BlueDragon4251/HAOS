#!/usr/bin/env python3
"""Actual SDK callback/ACK plus FULL SQLite custody; socket authentication separate."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    from dingtalk_stream import ChatbotMessage, Credential, DingTalkStreamClient
    from dingtalk_stream.frames import SystemMessage
    from haos.gateway import Conflict, digest
    from haos.gateway_dingtalk import PreparedDingTalkPolicy, scope
    from haos.gateway_dingtalk_admission import Refused
    from haos.gateway_dingtalk_cache import RawEvents
    from haos.gateway_dingtalk_frames import install
    from haos.gateway_raw import NativeInbox
    from haos.redaction import Redactor
    value = {'client_id': 'ding_private_fixture_app', 'client_secret': 'private-dingtalk-custody-fixture',
             'corp_id': 'ding_fixture_corporation', 'robot_code': 'ding_fixture_robot'}
    grant = {'id': 'owner', 'connector': 'dingtalk', 'sender': '$:LWCP_v1:$opaque-owner',
             'chat': 'cidExactConversation/+=', 'scope': scope(value), 'thread': '',
             'identity': 'personal', 'capabilities': ['create', 'read'], 'generation': 'a' * 64,
             'since': 1, 'require_mention': True}
    config = {'version': 1, 'connectors': [{'id': 'dingtalk', 'platform': 'dingtalk'}], 'bindings': [grant]}
    policy = lambda: PreparedDingTalkPolicy(config)
    now = int(time.time() * 1000)
    body = {'msgId': 'nativeMessage-123', 'createAt': now - 1000, 'senderId': grant['sender'],
            'conversationId': grant['chat'], 'conversationType': '1', 'chatbotCorpId': value['corp_id'],
            'senderCorpId': value['corp_id'], 'robotCode': value['robot_code'], 'msgtype': 'text',
            'text': {'content': 'Durably approved native goal.'},
            'sessionWebhook': 'https://oapi.dingtalk.com/robot/sendBySession?session=private-original-session',
            'sessionWebhookExpiredTime': now + 7200000}
    cases = []

    async def exercise(directory):
        redactor = Redactor(); live = [True]; fail = [False]; acks = []
        def current():
            if not live[0]:
                raise PermissionError('fixture publication withdrawn')
        raw_path = directory / 'raw.sqlite'; inbox_path = directory / 'inbox.sqlite'
        originals = RawEvents(raw_path, redactor, current)
        inbox = NativeInbox(inbox_path, redactor)
        async def capture(raw):
            item = originals.capture(policy(), 'dingtalk', value, raw)
            if fail[0]:
                raise OSError('fixture crash window before input commit')
            result = inbox.admit(policy(), 'dingtalk', item['envelope'], {'raw_id': item['id']},
                                 received_at=item['received_at'])
            assert result == item['source_key']
            return result
        class Socket:
            async def send(self, raw):
                # Independent connections prove both commits are visible before
                # the actual SDK ACK codec reaches the socket seam.
                import sqlite3
                with sqlite3.connect(raw_path) as conn:
                    raw_count = conn.execute('SELECT COUNT(*) FROM dingtalk_raw_events').fetchone()[0]
                with sqlite3.connect(inbox_path) as conn:
                    assert conn.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == raw_count
                assert raw_count in {1, 2}
                acks.append(json.loads(raw))
        client = DingTalkStreamClient(Credential(value['client_id'], value['client_secret']))
        install(client, capture, current); client.websocket = Socket()
        def frame(data=body, **changes):
            item = {'specVersion': '1.0', 'type': 'CALLBACK', 'headers': {
                'messageId': 'opaque-callback-id', 'topic': ChatbotMessage.TOPIC,
                'contentType': 'application/json', 'time': str(now)},
                'data': json.dumps(data, ensure_ascii=False)}
            item.update(changes)
            return json.dumps(item, ensure_ascii=False).encode()
        for store in [originals.store, inbox]:
            assert store.db.execute('PRAGMA synchronous').fetchone()[0] == 2
        await client.route_message(frame())
        assert len(acks) == 1 and acks[-1]['code'] == 200
        assert acks[-1]['headers']['messageId'] == 'opaque-callback-id'
        assert json.loads(acks[-1]['data']) == {'response': 'OK'}
        cases.append('actual_native_callback_ACK_codec_only_after_FULL_original_and_input_commits_visible_to_separate_connections')
        await client.route_message(frame()); assert len(acks) == 2
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == 1
        cases.append('actual_native_callback_replay_ACK_preserves_one_durable_input')
        receipt = originals.db.execute('SELECT id FROM dingtalk_raw_events').fetchone()[0]
        original = originals.get(policy(), 'dingtalk', value, receipt)
        assert original['raw'] == json.dumps(body, ensure_ascii=False).encode()
        originals.close(); inbox.close()
        originals = RawEvents(raw_path, redactor, current); inbox = NativeInbox(inbox_path, redactor)
        assert originals.get(policy(), 'dingtalk', value, receipt) == original
        assert inbox.due('dingtalk') == original['source_key']
        cases.append('reopen_preserves_exact_private_session_bearing_original_and_pending_input')
        refreshed = {**body, 'sessionWebhook': body['sessionWebhook'] + '-refreshed',
                     'sessionWebhookExpiredTime': now + 7300000}
        await client.route_message(frame(refreshed))
        assert originals.get(policy(), 'dingtalk', value, receipt) == original
        cases.append('replay_refreshed_session_capability_cannot_replace_first_retained_reply_route')
        for label, change in [('body', {'text': {'content': 'Changed goal.'}}),
                              ('timestamp', {'createAt': now - 2000})]:
            before = len(acks)
            try:
                await client.route_message(frame({**body, **change}))
            except Conflict:
                pass
            else:
                raise AssertionError('immutable input changed')
            assert len(acks) == before
            cases.append('conflicting_' + label + '_replay_never_ACKed_or_replaces_original')
        for label, data in [('unknown_sender', {**body, 'senderId': 'unapproved-owner'}),
                            ('wrong_corporation', {**body, 'senderCorpId': 'unapproved_corp'}),
                            ('robot', {**body, 'senderIsRobot': True})]:
            before = len(acks)
            try:
                await client.route_message(frame(data))
            except Refused:
                pass
            else:
                raise AssertionError('unapproved callback ACKed')
            assert len(acks) == before
            cases.append(label + '_no_ACK_reaction_plugin_or_input')
        before = len(acks); fail[0] = True
        second = {**body, 'msgId': 'second-native-message'}
        try:
            await client.route_message(frame(second))
        except OSError:
            pass
        else:
            raise AssertionError('failed input commit ACKed')
        assert len(acks) == before; fail[0] = False
        assert originals.db.execute('SELECT COUNT(*) FROM dingtalk_raw_events').fetchone()[0] == 2
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == 1
        await client.route_message(frame(second)); assert len(acks) == before + 1
        assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == 2
        cases.append('original_committed_input_failure_gets_no_ACK_and_replay_recovers_same_input')
        before = len(acks); live[0] = False
        try:
            await client.route_message(frame())
        except PermissionError:
            pass
        else:
            raise AssertionError('withdrawn publication ACKed')
        assert len(acks) == before
        try:
            originals.get(policy(), 'dingtalk', value, receipt)
        except PermissionError:
            pass
        else:
            raise AssertionError('withdrawn publication read original')
        live[0] = True
        cases.append('withdrawn_publication_refuses_ACK_and_private_original_read')
        for changes in ({'type': 'EVENT'}, {'specVersion': '2.0'}, {'data': '{"duplicate":1,"duplicate":2}'},
                        {'data': '{"nonfinite":NaN}'}):
            try:
                await client.route_message(frame(**changes))
            except Refused:
                pass
            else:
                raise AssertionError('unsupported native frame routed')
            assert len(acks) == before
        cases.append('wildcard_EVENT_unreviewed_version_duplicate_keys_nonfinite_payload_no_ACK')
        for invalid_receipt in (None, False, True, 'volatile-ack', {'accepted': True}):
            guarded = DingTalkStreamClient(Credential(value['client_id'], value['client_secret']))
            install(guarded, lambda _raw: invalid_receipt, current); guarded.websocket = Socket()
            try:
                await guarded.route_message(frame())
            except PermissionError:
                pass
            else:
                raise AssertionError('ambiguous durable receipt produced an ACK')
            assert len(acks) == before
        cases.append('actual_native_ACK_requires_exact_durable_receipt_not_boolean_or_volatile_success')
        entered = asyncio.Event(); release = asyncio.Event()
        async def held(_raw):
            entered.set(); await release.wait(); return 'a' * 64
        guarded = DingTalkStreamClient(Credential(value['client_id'], value['client_secret']))
        install(guarded, held, current); guarded.websocket = Socket()
        task = asyncio.create_task(guarded.route_message(frame()))
        await asyncio.wait_for(entered.wait(), 1)
        try:
            await guarded.route_message(frame())
        except Refused as error:
            assert error.reason == 'concurrent-frame'
        else:
            raise AssertionError('concurrent frame admitted outside backpressure')
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(acks) == before
        cases.append('actual_native_route_backpressure_and_capture_cancellation_leave_no_ACK')
        originals.db.execute('UPDATE dingtalk_raw_events SET data=?', (b'{}',))
        try:
            originals.get(policy(), 'dingtalk', value, receipt)
        except Conflict:
            pass
        else:
            raise AssertionError('damaged original accepted')
        cases.append('damaged_retained_original_refused_before_native_decode')
        originals.close(); inbox.close()
    with tempfile.TemporaryDirectory(prefix='haos-dingtalk-custody-') as td:
        asyncio.run(exercise(Path(td)))
    result = {'cases': cases, 'scope': 'Local real SDK and SQLite custody; socket, current-publication callback and IDs are fixtures.',
              'external_messages_or_installed_acceptance': False}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__':
    main()
