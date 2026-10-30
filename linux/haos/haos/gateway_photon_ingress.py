"""Retained native Photon projections → durable HAOS relay, including restart."""
import json

from .gateway import Conflict, digest
from .gateway_dingtalk_admission import finite
from .gateway_line_ingress import _object
from .gateway_photon import message_id, scope
from .gateway_photon_codec import decode, dispatch, media_scope
from .gateway_photon_custody import MAX_NORMALIZED


async def capture_stored(adapter, identity):
    adapter._haos_photon_check(); native = adapter._haos_native
    event, original, proof = await decode(adapter, identity)
    from .gateway_runtime import adapter_envelope
    with media_scope(event): envelope = adapter_envelope(event, 'photon')
    if {**envelope, 'text': ''} != proof['envelope'] or not 1 <= len(event.text.strip()) <= 32000:
        raise Conflict('Photon source has no exact bounded actionable projection')
    source_key = native.inbox.key(native.connector, envelope)
    db = native.inbox.db
    db.execute('''CREATE TABLE IF NOT EXISTS photon_native_projection(
        source_key TEXT PRIMARY KEY,raw_id TEXT NOT NULL,raw_sha256 TEXT NOT NULL,
        normalized_sha256 TEXT NOT NULL,binding_digest TEXT NOT NULL,credential_scope TEXT NOT NULL,
        envelope_sha256 TEXT NOT NULL)''')
    values = (source_key, identity, original['raw_sha256'], original['normalized_sha256'], proof['binding_digest'],
        proof['credential_scope'], digest(envelope))
    prior = db.execute('SELECT * FROM photon_native_projection WHERE source_key=?', (source_key,)).fetchone()
    if prior is None: db.execute('INSERT INTO photon_native_projection VALUES(?,?,?,?,?,?,?)', values)
    elif tuple(prior) != values: raise Conflict('Photon native projection differs from first source custody')
    adapter._haos_photon_check(); policy = native.policy(); policy.current_binding(proof)
    key = native.inbox.admit(policy, native.connector, envelope, {'raw_id': identity}, received_at=proof['received_at'])
    if key != source_key: raise Conflict('Photon native source key changed')
    return key


async def dispatch_stored(adapter, key):
    native = adapter._haos_native
    async with adapter._haos_photon_decode_lock:
        adapter._haos_photon_check(); row = native.inbox.claim(key, native.policy())
        if row is None: return False
        try:
            if not isinstance(row['payload'], dict) or set(row['payload']) != {'raw_id'}:
                raise Conflict('exact Photon original reference required')
            identity = row['payload']['raw_id']; event, original, proof = await decode(adapter, identity)
            from .gateway_runtime import adapter_envelope
            with media_scope(event): envelope = adapter_envelope(event, 'photon')
            projected = native.inbox.db.execute('SELECT * FROM photon_native_projection WHERE source_key=?', (key,)).fetchone()
            if (projected is None or projected['raw_id'] != identity or projected['raw_sha256'] != original['raw_sha256']
                    or projected['normalized_sha256'] != original['normalized_sha256'] or projected['credential_scope'] != proof['credential_scope']
                    or projected['binding_digest'] != row['binding_digest'] or projected['envelope_sha256'] != digest(envelope)
                    or row['envelope'] != envelope):
                raise Conflict('Photon source differs from its first durable parent projection')
            with dispatch(adapter, event, row, proof): adapter._haos_admit(event)
            adapter._haos_photon_check(); policy = native.policy(); policy.current_binding(proof)
            if event._gateway_accepted is not True: raise Conflict('Photon parent has no durable custody receipt')
            parent = digest([native.connector, *(envelope[k] for k in ['scope', 'chat', 'thread', 'message_id'])])
            adapter._haos_photon_originals.admitted(identity, parent, policy, native.connector, adapter._haos_photon_value)
            native.inbox.complete(key, True)
            return True
        except BaseException:
            native.inbox.retry(key)
            raise


async def on_line(adapter, line):
    adapter._haos_photon_check(); native = adapter._haos_native
    if not isinstance(line, str): raise Conflict('bounded Photon NDJSON source required')
    try:
        raw = line.encode('utf-8')
        if not 1 <= len(raw) <= MAX_NORMALIZED: raise ValueError
        data = json.loads(raw, object_pairs_hook=_object, parse_constant=finite)
        mid = message_id(data.get('messageId'))
    except (ValueError, TypeError, AttributeError, RecursionError, UnicodeError):
        raise Conflict('invalid bounded Photon native projection') from None
    identity = digest([native.connector, scope(adapter._haos_photon_value), mid])
    original, _ = adapter._haos_photon_originals.load(identity, native.policy(), native.connector, adapter._haos_photon_value)
    if not original['normalized'] or json.loads(original['normalized']) != data:
        raise Conflict('Photon NDJSON source has no matching durable native custody')
    key = await capture_stored(adapter, identity)
    return await dispatch_stored(adapter, key)


async def recover(adapter):
    """A crash after normalized custody must not require a fresh SDK event."""
    adapter._haos_photon_check(); native = adapter._haos_native
    value = adapter._haos_photon_value
    rows = adapter._haos_photon_originals.db.execute('''SELECT id FROM photon_originals
        WHERE connector=? AND account_scope=? AND length(normalized)>0 AND admitted_receipt=''
        ORDER BY created_at LIMIT 16''', (native.connector, scope(value))).fetchall()
    for row in rows:
        adapter._haos_photon_check()
        await capture_stored(adapter, row['id'])
    due = native.inbox.due(native.connector)
    if due is not None: return await dispatch_stored(adapter, due)
    return False
