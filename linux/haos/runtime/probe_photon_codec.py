#!/usr/bin/env python3
"""Actual prepared Spectrum → sidecar → Hermes codecs and HAOS custody.

Only the SDK's remote RPC frames and the final controller callback are fixture
substitutions. No cloud connection, message send, inference or UID claim.
"""
import asyncio
import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid
import wave


async def run(upstream, sidecar, output):
    sys.path.insert(0, str(upstream)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    assert (upstream / '.herald-os-upstream-sha').read_text().strip() == 'f97608f178d1ffeca59860195ab7da295f7c8e5f'
    from PIL import Image
    from haos.gateway_photon import PreparedPhotonPolicy, scope, checked_policy
    from haos.gateway_photon_custody import Originals
    from haos.gateway_photon_codec import install, decode, dispatch, media_scope
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_photon_ingress import capture_stored, dispatch_stored, recover, on_line
    from haos.gateway_relay import RelayInbox
    from haos.gateway_media_relay import event_media
    from haos.gateway_raw import NativeInbox
    from haos.gateway import Conflict, digest
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    from haos.gateway_matrix_profile import scope as native_scope
    cases = []
    with tempfile.TemporaryDirectory(prefix='haos-photon-codec-') as directory:
        root = Path(directory); root.chmod(0o700)
        account = {'project_id': 'fixture-project', 'project_secret': secrets.token_urlsafe(32), 'phone': 'shared', 'services': ['iMessage']}
        image = io.BytesIO(); Image.new('RGB', (2, 2), 'blue').save(image, format='PNG'); png = image.getvalue()
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000); stream.writeframes(b'\0\0' * 3200)
        wav = audio.getvalue()
        pcm = b'\0\0' * 3200
        caf = b'caff' + struct.pack('>HH', 1, 0) + b'desc' + struct.pack('>q', 32) + struct.pack('>d4sIIIII', 16000.0, b'lpcm', 2, 2, 1, 1, 16) + b'data' + struct.pack('>q', 4 + len(pcm)) + struct.pack('>I', 0) + pcm
        specs = []
        stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        for index, kind in enumerate(['text', 'reply', 'image', 'mixed-image', 'group-thread', 'voice', 'document',
                'audio-file', 'caf-alias', 'mixed-unicode', 'mixed-no-marker', 'mixed-adjacent-markers', 'multi-file',
                'restart-text', 'parent-receipt-lost', 'virtual-message', 'virtual-attachment', 'dedicated-chat']):
            chat = 'any;+;chatFixture' if kind == 'group-thread' else 'iMessage;-;+15550100001' if kind == 'dedicated-chat' else 'any;-;+15550100001'
            target = str(uuid.uuid4()) if kind in {'reply', 'group-thread'} else ''
            binding = {'id': 'binding-' + str(index), 'connector': 'phone', 'identity': 'owner', 'sender': '+15550100001',
                'chat': chat, 'thread': target, 'scope': scope(account), 'capabilities': ['create', 'read'],
                'generation': secrets.token_hex(32), 'since': int(time.time() * 1000) - 10000,
                'allow_media': True, 'allow_voice': True, 'allow_video': True}
            attachments = []; frames = {}
            text_cases = {'text', 'reply', 'group-thread', 'restart-text', 'parent-receipt-lost', 'virtual-message', 'dedicated-chat'}
            text = 'fixture native text' if kind in text_cases else 'caption \ufffc suffix' if kind == 'mixed-image' else ''
            if kind == 'mixed-unicode': text = '\ufeff\u0085caption \ufffc suffix\u0085\ufeff'
            elif kind == 'mixed-no-marker': text = 'caption after attachment'
            elif kind == 'mixed-adjacent-markers': text = 'left\ufffc\ufffcright'
            if kind not in text_cases:
                data = caf if kind == 'caf-alias' else wav if kind in {'voice', 'audio-file'} else b'fixture document bytes' if kind == 'document' else png
                aid = str(uuid.uuid4()); mime = 'audio/wav' if kind in {'voice', 'audio-file'} else 'application/octet-stream' if kind in {'document', 'caf-alias'} else 'image/png'
                if kind == 'virtual-attachment': aid = 'spc-' + aid
                name = 'fixture.caf' if kind == 'caf-alias' else 'fixture.wav' if kind in {'voice', 'audio-file'} else 'fixture.bin' if kind == 'document' else 'fixture.png'
                attachments = [{'guid': aid, 'fileName': name, 'mimeType': mime, 'totalBytes': len(data), 'uti': 'public.data'}]
                frames[aid] = base64.b64encode(data).decode()
                if kind == 'multi-file':
                    duplicate = str(uuid.uuid4()); attachments.append({**attachments[0], 'guid': duplicate}); frames[duplicate] = frames[aid]
            message = {'guid': str(uuid.uuid4()), 'isFromMe': False, 'dateCreated': stamp, 'chatGuids': [chat],
                'sender': {'address': binding['sender'], 'service': 'iMessage'}, 'content': {'text': text, 'attachments': attachments}}
            if kind == 'virtual-message': message['guid'] = 'spc-' + message['guid']
            if kind in {'voice', 'caf-alias'}: message['isAudioMessage'] = True
            if target: message.update(replyTargetGuid=target, threadOriginatorGuid=target)
            source = {'phone': 'shared', 'cursor': str(index + 1), 'event': {'type': 'message.received', 'sequence': index + 1,
                'occurredAt': stamp, 'chatGuid': chat, 'message': message}}
            specs.append({'kind': kind, 'source': source, 'frames': frames, 'binding': binding})
        inputs = root / 'native-input.json'; projected = root / 'native-output.json'
        inputs.write_text(json.dumps([{'source': item['source'], 'frames': item['frames']} for item in specs]))
        subprocess.run([shutil.which('node'), str(Path(__file__).with_name('probe_photon_sdk_codec.mjs')), str(sidecar), str(inputs), str(projected)],
            check=True, capture_output=True, text=True, timeout=30)
        outputs = json.loads(projected.read_text())['fixtures']
        # Fixture-only generated inputs, not account credentials. Preserve a
        # failed codec's exact case without copying any real owner material.
        output.with_suffix('.fixture-inputs.json').write_text(json.dumps({'specs': specs, 'projections': outputs}))
        for spec, projection in zip(specs, outputs, strict=True):
            profile = root / spec['kind']; profile.mkdir(mode=0o700)
            policy = PreparedPhotonPolicy({'version': 1, 'connectors': [{'id': 'phone', 'platform': 'photon'}], 'bindings': [spec['binding']]})
            current = lambda: checked_policy(policy)
            redactor = Redactor([account['project_secret']]); inbox = NativeInbox(profile / 'inbox.db', redactor)
            originals = Originals(profile / 'originals.db', redactor, current)
            relay = RelayInbox(profile / 'relay.db', redactor)
            try:
                raw = json.dumps(spec['source']).encode(); identity = originals.retain(policy, 'phone', account, raw)
                originals.decode(identity, policy, 'phone', account, json.dumps(projection['event']).encode())
                home = profile / 'home'; home.mkdir(mode=0o700)
                environment = {'HERMES_SAFE_MODE': '1', 'PHOTON_PROJECT_ID': account['project_id'], 'PHOTON_PROJECT_SECRET': account['project_secret'],
                    'PHOTON_REQUIRE_MENTION': 'false', 'PHOTON_REACTIONS': 'false', 'PHOTON_MARKDOWN': 'false'}
                with native_scope(home, environment):
                    from gateway.config import PlatformConfig
                    from plugins.platforms.photon.adapter import PhotonAdapter
                    adapter = durable_adapter(PhotonAdapter(PlatformConfig(enabled=True, extra={'require_mention': False})))
                adapter._haos_native = SimpleNamespace(connector='phone', policy=current, inbox=inbox)
                adapter._haos_photon_check = current; adapter._haos_photon_value = account; adapter._haos_photon_originals = originals
                install(adapter); calls = []
                lose_receipt = [spec['kind'] == 'parent-receipt-lost']
                def handler(event):
                    envelope = adapter_envelope(event, 'photon')
                    relay.admit(current(), 'phone', envelope, media=event_media(event, 'photon'))
                    calls.append(envelope)
                    if lose_receipt[0]:
                        lose_receipt[0] = False
                        raise ConnectionError('fixture parent receipt lost after actual relay commit')
                    return True
                adapter.set_durable_message_handler(handler)
                event, row, proof = await decode(adapter, identity)
                assert not calls
                with media_scope(event): envelope = adapter_envelope(event, 'photon')
                assert {**envelope, 'text': ''} == proof['envelope']
                if spec['frames']:
                    assert event.media_urls and all(url.startswith('haos-media:') for url in event.media_urls)
                    assert projection['closed_native_streams'] == len(spec['frames'])
                if spec['kind'] not in {'restart-text', 'parent-receipt-lost'}:
                    with dispatch(adapter, event, {'envelope': envelope}, proof): adapter._haos_admit(event)
                    assert calls == [envelope] and event._gateway_accepted is True
                try: adapter._haos_admit(event)
                except PermissionError: pass
                else: raise AssertionError('native event escaped exact source context')
                if spec['kind'] == 'restart-text':
                    # No native inbox row or parent receipt exists at the crash
                    # point. Reopen the actual three databases and reconstruct
                    # a fresh native adapter without another SDK/NDJSON event.
                    assert inbox.db.execute('SELECT COUNT(*) FROM native_inbox').fetchone()[0] == 0
                    assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 0
                    inbox.close(); originals.close(); relay.close()
                    inbox = NativeInbox(profile / 'inbox.db', redactor); originals = Originals(profile / 'originals.db', redactor, current)
                    relay = RelayInbox(profile / 'relay.db', redactor)
                    with native_scope(home, environment):
                        adapter = durable_adapter(PhotonAdapter(PlatformConfig(enabled=True, extra={'require_mention': False})))
                    adapter._haos_native = SimpleNamespace(connector='phone', policy=current, inbox=inbox)
                    adapter._haos_photon_check = current; adapter._haos_photon_value = account; adapter._haos_photon_originals = originals
                    install(adapter); adapter.set_durable_message_handler(handler)
                    assert await recover(adapter) is True
                else:
                    native_key = await capture_stored(adapter, identity)
                    if spec['kind'] == 'parent-receipt-lost':
                        try: await dispatch_stored(adapter, native_key)
                        except ConnectionError: pass
                        else: raise AssertionError('lost actual durable relay receipt was hidden')
                        assert originals.load(identity, policy, 'phone', account)[0]['admitted_receipt'] == ''
                        assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
                        await asyncio.sleep(2.1)  # Actual native retry deadline; no mocked clock or extra skip.
                    assert await dispatch_stored(adapter, native_key) is True
                assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
                parent_key = relay.db.execute('SELECT id FROM inbox').fetchone()[0]
                assert originals.load(identity, policy, 'phone', account)[0]['admitted_receipt'] == parent_key
                assert await on_line(adapter, json.dumps(projection['event'])) is False
                assert relay.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0] == 1
                replay, _, _ = await decode(adapter, identity)
                with media_scope(replay): assert adapter_envelope(replay, 'photon') == envelope
                if spec['frames']:
                    from haos.gateway_media_relay import MediaCache
                    cache = MediaCache(inbox); ids = [url.removeprefix('haos-media:') for url in event.media_urls]
                    cache.transferred(ids)
                    replay, _, _ = await decode(adapter, identity)
                    assert replay.media_urls == event.media_urls
                    assert all(inbox.db.execute('SELECT data FROM native_media_cache WHERE id=?', (item,)).fetchone()[0] is None for item in ids)
                cases.append(spec['kind'] + '_actual_Spectrum_sidecar_Hermes_codec_and_retained_replay')
            finally:
                originals.close(); inbox.close(); relay.close()
    result = {'schema': 1, 'passed': len(cases), 'cases': cases,
        'scope': 'actual prepared Spectrum mapper, sidecar normalizeEvent/normalizeContent, PhotonAdapter native dispatch, independent policy, FULL original/native/media/RelayInbox custody and restart',
        'substitutions': ['SDK remote RPC frames', 'final handler invokes actual RelayInbox without a controller connection'], 'external_messages_sent': False,
        'controller_inference_verified': False, 'local_STT_verified': False, 'kernel_UID_verified_by_this_probe': False}
    output.write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result))


if __name__ == '__main__':
    asyncio.run(run(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()))
