#!/usr/bin/env python3
"""Build-only Photon transport extension for the exact Hermes/Spectrum snapshot.

No dependency installation or source repair occurs in the gateway service.
Every input is checked before either source is changed.
"""
import argparse
import hashlib
import json
from pathlib import Path


INPUTS = {
    'index.mjs': 'f00d51e138790f6a32822f9c137610d9fc9454b3355a49e645dcd13d37a3529e',
    'package.json': '46d0f09d403e8d67261e23d5114dda13654179234ff748959923b8806c186cca',
    'package-lock.json': '2368d0b886d149c69dfb1fb2201ed7868bd751de2a88467b7848f2649241a313',
    'node_modules/@spectrum-ts/imessage/dist/index.js': '2f7e13c432ad4e84f96b76eb3d59062d70d3d7e46737a7e15198a47ecda6ef24',
}


def replace_once(text, anchor, replacement):
    if text.count(anchor) != 1:
        raise ValueError('pinned Photon transport anchor changed')
    return text.replace(anchor, replacement, 1)


def transformed(sidecar, sdk):
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
    return sidecar, sdk


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
    names = ['index.mjs', 'node_modules/@spectrum-ts/imessage/dist/index.js']
    prepared = transformed(*(data[name] for name in names))
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
