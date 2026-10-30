#!/usr/bin/env node
// Actual prepared SDK mapping + bounded native attachment stream. RPC frames
// are a local fixture; no project, Photon connection or external message.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import crypto from "node:crypto";
import assert from "node:assert/strict";
import { readBinary } from "./photon_bounded_stream.mjs";

const root = process.argv[2];
const output = process.argv[3];
if (!root || !output) throw new Error("prepared sidecar and receipt path required");
const sdk = path.join(root, "node_modules/@spectrum-ts/imessage/dist/index.js");
const data = await fs.readFile(sdk, "utf8");
if (!data.includes('Symbol.for("hermes.photon.sdk.transport")')) throw new Error("prepared native SDK required");
// Export internal functions from an ephemeral copy, preserving all actual
// dependency imports. Production package exports are unchanged.
const fixtureModule = path.join(path.dirname(sdk), `haos-fixture-${crypto.randomUUID()}.mjs`);
const cases = [];
let rpc = 0;
const hooks = Symbol.for("hermes.photon.sdk.transport");
try {
  await fs.writeFile(fixtureModule, data + "\nexport {toMessageItem,toPollItem,toGroupItem};\n", { flag: "wx" });
  const native = await import(pathToFileURL(fixtureModule));
  const now = new Date();
  const message = {
    guid: crypto.randomUUID(), isFromMe: false, chatGuids: ["any;-;+15550100001"],
    sender: { address: "+15550100001", service: "iMessage" },
    content: { text: "fixture native text", attachments: [] }, dateCreated: now,
  };
  const event = { type: "message.received", sequence: 1, occurredAt: now,
    chatGuid: message.chatGuids[0], message };
  const client = { attachments: { downloadStream() { rpc++; throw new Error("unexpected native download"); } },
    messages: { async get() { rpc++; throw new Error("unexpected quoted-message read"); } } };
  globalThis[hooks] = { admitEvent: async () => false, disableAutomaticContactSharing: true, avoidReplyHydration: true };
  const denied = await native.toMessageItem(client, event, "shared", "1", () => { rpc++; });
  assert.deepEqual(denied.values, []);
  assert.equal(rpc, 0);
  cases.push("native_sdk_refuses_before_mapping_or_automatic_contact_callback");
  const card = { ...event, message: { ...message, content: { text: "", attachments: [
    { guid: crypto.randomUUID(), fileName: "private.vcf", mimeType: "text/vcard", totalBytes: 3, uti: "public.vcard" },
  ] } } };
  assert.deepEqual((await native.toMessageItem(client, card, "shared", "2")).values, []);
  assert.equal(rpc, 0);
  cases.push("native_vcard_download_is_refused_before_eager_sdk_conversion");
  assert.deepEqual((await native.toPollItem(client, {}, { type: "poll.changed" }, "shared", "3")).values, []);
  assert.deepEqual((await native.toGroupItem(client, { type: "group.changed" }, "shared", "4")).values, []);
  assert.equal(rpc, 0);
  cases.push("native_poll_and_group_hydration_refused_before_rpc");
  globalThis[hooks].admitEvent = async () => { const err = new Error("fixture custody unavailable"); err.retryable = true; throw err; };
  await assert.rejects(native.toMessageItem(client, event, "shared", "5"), /custody unavailable/);
  cases.push("failed_independent_custody_cannot_be_interpreted_as_admission");
  globalThis[hooks].admitEvent = async () => true;
  const accepted = await native.toMessageItem(client, event, "shared", "6");
  assert.equal(accepted.values[0].content.text, "fixture native text");
  assert.equal(accepted.values[0].sender.id, message.sender.address);
  assert.equal(accepted.values[0].space.id, event.chatGuid);
  assert.equal(rpc, 0);
  cases.push("approved_text_uses_actual_native_message_and_sender_codec");
  const reply = { ...event, message: { ...message, replyTargetGuid: crypto.randomUUID() } };
  const resolved = (await native.toMessageItem(client, reply, "shared", "7")).values[0];
  assert.equal(resolved.content.type, "reply");
  assert.equal(resolved.content.content.text, "fixture native text");
  assert.equal(resolved.content.target.id, reply.message.replyTargetGuid);
  assert.equal(rpc, 0);
  cases.push("actual_native_reply_keeps_target_id_without_quoted_message_hydration");

  let closed = 0, unsafeReads = 0;
  client.attachments.downloadStream = () => ({
    async *[Symbol.asyncIterator]() {
      yield { type: "header" };
      yield { type: "primaryChunk", data: new Uint8Array([1, 2]) };
      yield { type: "primaryChunk", data: new Uint8Array([3]) };
    }, async close() { closed++; },
  });
  const attachment = { guid: crypto.randomUUID(), fileName: "fixture.bin", mimeType: "application/octet-stream", totalBytes: 3, uti: "public.data" };
  const media = { ...event, message: { ...message, content: { text: "", attachments: [attachment] } } };
  const binary = (await native.toMessageItem(client, media, "shared", "8")).values[0].content;
  binary.read = () => { unsafeReads++; throw new Error("unbounded read is forbidden"); };
  assert.deepEqual(await readBinary(binary, 8, async () => true), Buffer.from([1, 2, 3]));
  assert.equal(closed, 1);
  assert.equal(unsafeReads, 0);
  cases.push("actual_native_attachment_stream_obeys_bound_and_closes_native_rpc");
  await assert.rejects(readBinary({ ...binary, size: 2 }, 8, async () => true), /size exceeded/);
  assert.equal(closed, 2);
  cases.push("lying_native_size_refused_and_rpc_closed");
  await assert.rejects(readBinary({ ...binary, size: 4 }, 8, async () => true), /truncated/);
  cases.push("truncated_native_attachment_is_not_a_successful_marker");
  let checks = 0;
  await assert.rejects(readBinary(binary, 8, async () => ++checks < 3), /withdrawn/);
  cases.push("authority_rechecked_between_native_chunks_and_withdrawal_cancels_rpc");
  let cancelled = 0;
  const stalled = { size: 1, stream: async () => new ReadableStream({
    pull: () => new Promise(() => {}), cancel() { cancelled++; },
  }) };
  await assert.rejects(readBinary(stalled, 8, async () => true, { timeoutMs: 30 }), /deadline/);
  assert.equal(cancelled, 1);
  cases.push("hung_native_stream_is_cancelled_at_total_deadline");
  let opened = 0;
  await assert.rejects(readBinary({ size: 9, stream() { opened++; } }, 8, async () => true), /size/);
  assert.equal(opened, 0);
  cases.push("oversize_metadata_refused_before_stream_open");
  globalThis[hooks] = {};
  await assert.rejects(native.toMessageItem(client, event, "shared", "9"), /invalid Photon SDK/);
  cases.push("incomplete_sdk_embedding_fails_closed");
  const result = { schema: 1, passed: cases.length, cases, actual_spectrum_version: "12.7.0",
    prepared_sdk_sha256: crypto.createHash("sha256").update(data).digest("hex"),
    native_rpc_frames: "local fixture", external_network: false, live_delivery_verified: false };
  await fs.writeFile(output, JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify(result));
} finally {
  delete globalThis[hooks];
  await fs.unlink(fixtureModule).catch(() => {});
}
