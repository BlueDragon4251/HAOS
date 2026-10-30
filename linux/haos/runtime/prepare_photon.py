#!/usr/bin/env python3
"""Build-only Photon transport extension for the exact Hermes/Spectrum snapshot.

No dependency installation or source repair occurs in the gateway service.
Every input is checked before either source is changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


INPUTS = {
    '../adapter.py': '7dcedacead3b762166acbb0309e372d9eedf81b28efa7adce692122130775a68',
    'index.mjs': 'f00d51e138790f6a32822f9c137610d9fc9454b3355a49e645dcd13d37a3529e',
    'package.json': '46d0f09d403e8d67261e23d5114dda13654179234ff748959923b8806c186cca',
    'package-lock.json': '2368d0b886d149c69dfb1fb2201ed7868bd751de2a88467b7848f2649241a313',
    'send-format.mjs': '827c6c0b3a7fd3b731365ecd17bb52d65b05c9a53e67795922ec2ebb79de58fe',
    'stream-staleness.mjs': 'fc77b20e29c8b759b1f45ec4b34d115b37859966b277e2583b1ae0fe8c73e141',
    'patch-spectrum-mixed-attachments.mjs': '0d1ed02316cc8ddb3fbcf985c1a5c511361bf03609c7d5ae21d594f5510c68b7',
    'node_modules/@spectrum-ts/imessage/dist/index.js': '2f7e13c432ad4e84f96b76eb3d59062d70d3d7e46737a7e15198a47ecda6ef24',
    'node_modules/@spectrum-ts/core/dist/authoring.js': 'f96d907578eb44bb74b51203f4b3f2bb70d44364f5cef819b05b9899a9be6852',
}


def replace_once(text, anchor, replacement):
    if text.count(anchor) != 1:
        raise ValueError('pinned Photon transport anchor changed')
    return text.replace(anchor, replacement, 1)


def transformed(sidecar, sdk, core):
    declaration = '''// Optional trusted embedding transport. Never resolved from an incoming message.
const hermesTransport = globalThis[Symbol.for("hermes.photon.transport")];
if (hermesTransport !== undefined && (!hermesTransport ||
    ["admitInbound", "custodyInbound", "readBinary", "authorizeRequest", "authorizeBody", "listen"]
      .some((key) => typeof hermesTransport[key] !== "function"))) {
  throw new Error("incomplete Photon embedding transport");
}
'''
    sidecar = replace_once(sidecar, 'const projectId = process.env.PHOTON_PROJECT_ID;',
                           declaration + '\nconst projectId = process.env.PHOTON_PROJECT_ID;')
    sidecar = replace_once(sidecar, '  options: { flattenGroups: true },',
        '  options: { flattenGroups: hermesTransport ? false : true },')
    # Inbound native SDK mapping has its own earlier gate (below). This second
    # check binds the resolved immutable source and current owner publication.
    anchor = '        rememberInboundSpace(space, message);'
    sidecar = replace_once(sidecar, anchor,
        '        if (hermesTransport && await hermesTransport.admitInbound(space, message) !== true) continue;\n' + anchor)
    anchor = '        await deliver(JSON.stringify(event));'
    sidecar = replace_once(sidecar, anchor,
        '        if (hermesTransport && await hermesTransport.custodyInbound(event) !== true) continue;\n' + anchor)
    sidecar = replace_once(sidecar, '      const buf = await content.read();',
        '      const buf = hermesTransport ? await hermesTransport.readBinary(content, MAX_INLINE_ATTACHMENT_BYTES) : await content.read();')
    # Native reply bodies were previously reduced to an unknown marker. Keep
    # the actual current body and immutable target ID, without quoted content.
    anchor = '  if (content.type === "text") {'
    sidecar = replace_once(sidecar, anchor, '''  if (content.type === "reply") {
    return { type: "reply", targetMessageId: content.target?.id ?? null,
      content: await normalizeContent(content.content) };
  }
''' + anchor)
    anchor = '  // Long-lived inbound NDJSON stream.'
    sidecar = replace_once(sidecar, anchor,
        '  if (hermesTransport && await hermesTransport.authorizeRequest(req) !== true) return unauthorized(res);\n' + anchor)
    anchor = '    const body = await readBody(req);'
    sidecar = replace_once(sidecar, anchor, anchor + '\n    if (hermesTransport && await hermesTransport.authorizeBody(req, body) !== true) return unauthorized(res);')
    anchor = '''server.listen(port, bind, () => {
  console.error(`photon-sidecar: listening on ${bind}:${port}`);
});'''
    sidecar = replace_once(sidecar, anchor,
        'if (hermesTransport) hermesTransport.listen(server);\nelse ' + anchor)
    sidecar = replace_once(sidecar, '  spectrumText,', '  spectrumText,\n  spectrumReply,')
    sidecar = replace_once(sidecar, '    text: spectrumText,', '    text: spectrumText,\n    reply: spectrumReply,')
    # A trusted reply capability already names the retained parent. The actual
    # SDK builder can target that ID without reading quoted message contents.
    anchor = '''      const result = await space.send(builder);
      return ok(res, { messageId: result?.id || null });
    }
    if (req.url === "/send-richlink")'''
    sidecar = replace_once(sidecar, anchor, '''      const outbound = hermesTransport
        ? spectrumReply(builder, { id: body.replyTo, content: { type: "text", text: "" }, space })
        : builder;
      let result;
      try { result = await space.send(outbound); }
      catch (error) {
        if (hermesTransport?.writeFailed) await hermesTransport.writeFailed(error);
        if (hermesTransport) throw new Error("Photon native write failed");
        throw error;
      }
      return ok(res, { messageId: result?.id || null });
    }
    if (req.url === "/send-richlink")''')
    # SDK space.get is a pure exact-reference constructor. The upstream DM
    # creation fallback can issue an unnecessary chat-creation mutation on a
    # dedicated line after restart, before the reviewed message write.
    sidecar = replace_once(sidecar, '  const im = imessage(app);\n  const phoneTarget = phoneTargetFromSpaceId(spaceId);', '''  const im = imessage(app);
  if (hermesTransport) return await im.space.get(spaceId);
  const phoneTarget = phoneTargetFromSpaceId(spaceId);''')
    # Earliest mapping gates: vCards, reply targets, reactions, poll and group
    # hydration can perform RPCs before a Message reaches the sidecar.
    for signature in [
        'const toMessageItem = async (client, event, phone, cursor, onInbound) => {',
        'const toPollItem = async (client, pollCache, event, phone, cursor) => {',
        'const toGroupItem = async (client, event, phone, cursor) => {',
    ]:
        sdk = replace_once(sdk, signature, signature + '''
	const embedding = globalThis[Symbol.for("hermes.photon.sdk.transport")];
	if (embedding !== undefined) {
		if (!embedding || typeof embedding.admitEvent !== "function") throw new Error("invalid Photon SDK embedding transport");
		if (await embedding.admitEvent(event, phone, cursor) !== true) return { cursor, id: `embedding-refused:${cursor}`, values: [] };
	}''')
    anchor = '\t\tconst tracker = staticShareEnabled || profileSyncGate ? getContactShareTracker(entry.client) : void 0;'
    sdk = replace_once(sdk, anchor,
        '\t\tconst tracker = !globalThis[Symbol.for("hermes.photon.sdk.transport")]?.disableAutomaticContactSharing && (staticShareEnabled || profileSyncGate) ? getContactShareTracker(entry.client) : void 0;')
    anchor = 'const resolveReplyTarget = async (client, base, targetGuid, currentGuid, options) => {'
    sdk = replace_once(sdk, anchor, anchor + '\n\tif (globalThis[Symbol.for("hermes.photon.sdk.transport")]?.avoidReplyHydration === true) return stubReplyTarget(base, targetGuid);')
    sdk, count = re.subn(r'(?m)^(\t+)retry: true,$',
        r'\1channelOptions: globalThis[Symbol.for("hermes.photon.sdk.transport")]?.disableAutomaticRetries === true ? { "grpc.enable_retries": 0 } : void 0,\n'
        r'\1retry: globalThis[Symbol.for("hermes.photon.sdk.transport")]?.disableAutomaticRetries !== true,', sdk)
    if count != 3: raise ValueError('pinned Photon automatic RPC retry constructors changed')
    anchor = '\tlet tokenData = await cloud.issueImessageTokens(projectId, projectSecret);'
    sdk = replace_once(sdk, anchor, '''\tconst selectTokenData = async (data) => {
\t\tconst embedding = globalThis[Symbol.for("hermes.photon.sdk.transport")];
\t\treturn embedding?.selectTokenData ? await embedding.selectTokenData(data) : data;
\t};
\tlet tokenData = await selectTokenData(await cloud.issueImessageTokens(projectId, projectSecret));''')
    sdk = replace_once(sdk, '\t\t\ttokenData = await cloud.issueImessageTokens(projectId, projectSecret);',
        '\t\t\ttokenData = await selectTokenData(await cloud.issueImessageTokens(projectId, projectSecret));')
    anchor = 'const messageStream = (client, phone, onInbound, recover) => resumableOrderedStream({\n'
    sdk = replace_once(sdk, anchor, anchor + '''	initialCursor: globalThis[Symbol.for("hermes.photon.sdk.transport")]?.initialCursor,
	onCursor: globalThis[Symbol.for("hermes.photon.sdk.transport")]?.commitCursor,
	onCursorRejected: globalThis[Symbol.for("hermes.photon.sdk.transport")]?.cursorRejected,
	onFailure: globalThis[Symbol.for("hermes.photon.sdk.transport")]?.streamFailure,
''')
    core = replace_once(core, '\tlet lastCursor;\n', '\tlet lastCursor = options.initialCursor;\n')
    core = replace_once(core, '\tconst advanceCursor = (cursor, clearDelivered) => {', '\tconst advanceCursor = async (cursor, clearDelivered) => {')
    core = replace_once(core, '\t\tlastCursor = cursor;\n', '\t\tif (options.onCursor) await options.onCursor(cursor);\n\t\tlastCursor = cursor;\n')
    core = replace_once(core, '\t\tadvanceCursor(item.cursor, clearOnCursorAdvance);', '\t\tawait advanceCursor(item.cursor, clearOnCursorAdvance);')
    core = replace_once(core, '\tconst handleFailure = (error, phase) => {', '\tconst handleFailure = async (error, phase) => {\n\t\tif (options.onFailure) await options.onFailure(error instanceof CursorRejectedError ? error.cause : error, phase);')
    core = replace_once(core, '\t\t\tlastCursor = void 0;\n', '''			if (options.onCursorRejected) {
				await options.onCursorRejected(lastCursor, error.cause);
				throw error; // Trusted embedding requires inspected recovery, never a silent live gap.
			}
			lastCursor = void 0;
''')
    core = replace_once(core, '\t\t\t\tconst delayMs = handleFailure(error, phase);', '\t\t\t\tconst delayMs = await handleFailure(error, phase);')
    return sidecar, sdk, core


def adapter_extension(text):
    text = replace_once(text, 'import asyncio\n', 'import asyncio\nfrom contextlib import contextmanager\nfrom contextvars import ContextVar\n')
    anchor = 'def _cache_inbound_attachment(content: Dict[str, Any], name: str, mime: str, *,\n'
    addition = '''_ATTACHMENT_CACHE = ContextVar("hermes_photon_attachment_cache", default=None)


@contextmanager
def attachment_cache(callback):
    """Scoped private cache transport; native content/event codecs remain here."""
    if not callable(callback):
        raise TypeError("attachment cache callback required")
    token = _ATTACHMENT_CACHE.set(callback)
    try:
        yield
    finally:
        _ATTACHMENT_CACHE.reset(token)


'''
    text = replace_once(text, anchor, addition + anchor)
    anchor = '    if not content.get("data"):\n        return None\n'
    return replace_once(text, anchor, '''    cache = _ATTACHMENT_CACHE.get()
    if cache is not None:
        return cache(content, name, mime, force_audio=force_audio)
''' + anchor)


def prepare(root, *, check_only=False):
    root = Path(root)
    data = {}
    for name, expected in INPUTS.items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('regular pinned Photon build input required: ' + name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Photon build input changed: ' + name)
        data[name] = raw.decode('utf-8')
    names = ['index.mjs', 'node_modules/@spectrum-ts/imessage/dist/index.js', 'node_modules/@spectrum-ts/core/dist/authoring.js', '../adapter.py']
    prepared = (*transformed(*(data[name] for name in names[:3])), adapter_extension(data['../adapter.py']))
    result = {'schema': 1, 'hermes_commit': 'f97608f178d1ffeca59860195ab7da295f7c8e5f',
        'spectrum_version': '12.7.0', 'inputs': [{'path': name, 'sha256': value} for name, value in INPUTS.items()],
        'prepared': [{'path': name, 'sha256': hashlib.sha256(value.encode()).hexdigest()} for name, value in zip(names, prepared)]}
    if not check_only:
        for name, value in zip(names, prepared):
            (root / name).write_text(value, encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sidecar', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    result = prepare(args.sidecar, check_only=args.check)
    if args.receipt:
        args.receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
