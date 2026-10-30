#!/usr/bin/env node
// Actual prepared Spectrum mapper and Hermes sidecar codecs, with local RPC
// frame substitution. Does not initialize Spectrum or contact any project.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import crypto from "node:crypto";
import { readBinary } from "./photon_bounded_stream.mjs";

const [root, input, output] = process.argv.slice(2);
if (!root || !input || !output) throw new Error("prepared sidecar, fixture input and output required");
const filename = path.join(root, "node_modules/@spectrum-ts/imessage/dist/index.js");
const sdk = await fs.readFile(filename, "utf8");
if (!sdk.includes('Symbol.for("hermes.photon.sdk.transport")')) throw new Error("prepared native SDK required");
const sidecar = await fs.readFile(path.join(root, "index.mjs"), "utf8");
function between(start, end) {
  if (sidecar.split(start).length !== 2 || sidecar.split(end).length !== 2) throw new Error("pinned native codec anchors changed");
  return sidecar.slice(sidecar.indexOf(start), sidecar.indexOf(end));
}
// Execute the actual named codec declarations only. Importing the entire
// sidecar would initialize a credentialed Spectrum connection, which this
// explicit no-network component fixture must not do.
const functions = between("async function normalizeBinaryContent(", "// The iMessage SDK exposes") +
  between("async function normalizeEvent(", "function inboundStreamErrorMessage(");
const native = new Function("hermesTransport", "MAX_INLINE_ATTACHMENT_BYTES", "Buffer", functions + "\nreturn {normalizeEvent};")(
  { readBinary: (content, cap) => readBinary(content, cap, async () => true) }, 8 * 1024 * 1024, Buffer);
const fixtureModule = path.join(path.dirname(filename), `haos-fixture-${crypto.randomUUID()}.mjs`);
const hooks = Symbol.for("hermes.photon.sdk.transport");
try {
  await fs.writeFile(fixtureModule, sdk + "\nexport {toMessageItem};\n", { flag: "wx" });
  const { toMessageItem } = await import(pathToFileURL(fixtureModule));
  globalThis[hooks] = { admitEvent: async () => true, disableAutomaticContactSharing: true, avoidReplyHydration: true };
  const fixtures = JSON.parse(await fs.readFile(input, "utf8"));
  if (!Array.isArray(fixtures) || fixtures.length > 16) throw new Error("bounded explicit codec fixtures required");
  const results = [];
  for (const fixture of fixtures) {
    const event = fixture.source.event;
    event.occurredAt = new Date(event.occurredAt);
    event.message.dateCreated = new Date(event.message.dateCreated);
    let closed = 0;
    const client = { attachments: { downloadStream(guid) {
      const encoded = fixture.frames?.[guid];
      if (typeof encoded !== "string") throw new Error("unapproved fixture attachment RPC");
      const bytes = Buffer.from(encoded, "base64");
      return { async *[Symbol.asyncIterator]() {
        yield { type: "header" };
        yield { type: "primaryChunk", data: bytes.subarray(0, 2) };
        if (bytes.length > 2) yield { type: "primaryChunk", data: bytes.subarray(2) };
      }, async close() { closed++; } };
    } }, messages: { async get() { throw new Error("unexpected quote hydration"); } } };
    const result = await toMessageItem(client, event, fixture.source.phone, fixture.source.cursor);
    if (result.values.length !== 1) throw new Error("one native source required");
    const message = result.values[0];
    const projected = await native.normalizeEvent({ ...message.space, __platform: "iMessage" }, message);
    if (!projected) throw new Error("native sidecar returned no source");
    results.push({ event: projected, closed_native_streams: closed });
  }
  await fs.writeFile(output, JSON.stringify({ schema: 1, fixtures: results, external_network: false }, null, 2) + "\n");
} finally {
  delete globalThis[hooks];
  await fs.unlink(fixtureModule).catch(() => {});
}
