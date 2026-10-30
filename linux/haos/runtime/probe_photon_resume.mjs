#!/usr/bin/env node
// Actual Spectrum resumableOrderedStream/Repeater with local live/catch-up
// iterators. Separate SQLite tests cover real durable writes and reopen.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [root, output] = process.argv.slice(2);
if (!root || !output) throw new Error("prepared sidecar and receipt required");
const filename = path.join(root, "node_modules/@spectrum-ts/core/dist/authoring.js");
const code = await fs.readFile(filename, "utf8");
if (!code.includes("let lastCursor = options.initialCursor")) throw new Error("prepared actual Spectrum stream required");
const { resumableOrderedStream } = await import(pathToFileURL(filename));
const cases = [];
function queue(events = []) {
  let stopped = false, wake;
  const source = {
    [Symbol.asyncIterator]() { return this; },
    async next() {
      if (stopped) return { done: true };
      if (events.length) return { value: events.shift(), done: false };
      return await new Promise((resolve) => { wake = resolve; });
    },
    async close() { stopped = true; wake?.({ done: true }); },
    async return() { await this.close(); return { done: true }; },
  };
  return source;
}
async function until(predicate) {
  const end = Date.now() + 3000;
  while (!predicate()) {
    if (Date.now() >= end) throw new Error("native stream fixture condition did not settle");
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
}
const item = (number) => ({ id: `event-${number}`, cursor: String(number), values: [`value-${number}`] });
const timings = { initialRetryDelayMs: 1, maxRetryDelayMs: 2, jitter: () => 0 };

{
  const starts = [], missed = [], commits = [], processed = [];
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const live = queue([6]);
  const stream = resumableOrderedStream({ ...timings, label: "fixture-resume", initialCursor: "4",
    subscribeLive(cursor) { starts.push(cursor); return live; },
    async *fetchMissed(cursor) { missed.push(cursor); yield 5; },
    async processMissed(value) { processed.push(value); return item(value); },
    async processLive(value) { processed.push(value); return item(value); },
    async onCursor(cursor) { commits.push([cursor, "started"]); if (cursor === "5") await held; commits.push([cursor, "durable"]); },
  });
  const iterator = stream[Symbol.asyncIterator]();
  try {
    assert.equal((await iterator.next()).value, "value-5");
    const next = iterator.next();
    await until(() => commits.length === 1);
    assert.deepEqual(commits, [["5", "started"]]);
    assert.deepEqual(processed, [5]);
    release(); assert.equal((await next).value, "value-6");
    const pending = iterator.next();
    await until(() => commits.length === 4);
    assert.deepEqual(starts, ["4"]); assert.deepEqual(missed, ["4"]);
    assert.deepEqual(commits, [["5", "started"], ["5", "durable"], ["6", "started"], ["6", "durable"]]);
    await stream.close(); await pending;
    cases.push("actual_native_restart_uses_saved_cursor_and_catches_up_before_buffered_live_events");
    cases.push("actual_native_cursor_waits_for_durable_callback_before_processing_later_events");
  } finally { release(); await stream.close(); }
}

{
  const starts = [], missed = [], commits = [];
  let fail = true;
  const stream = resumableOrderedStream({ ...timings, label: "fixture-cursor-write-failure", initialCursor: "4",
    subscribeLive(cursor) { starts.push(cursor); return queue(); },
    async *fetchMissed(cursor) { missed.push(cursor); yield 5; },
    async processMissed(value) { return item(value); }, async processLive(value) { return item(value); },
    async onCursor(cursor) { if (fail) { fail = false; throw new Error("fixture durable cursor refusal"); } commits.push(cursor); },
  });
  const iterator = stream[Symbol.asyncIterator]();
  try {
    assert.equal((await iterator.next()).value, "value-5");
    assert.equal((await iterator.next()).value, "value-5");
    const pending = iterator.next(); await until(() => commits.includes("5"));
    assert.deepEqual(starts.slice(0, 2), ["4", "4"]); assert.deepEqual(missed.slice(0, 2), ["4", "4"]);
    await stream.close(); await pending;
    cases.push("actual_native_failed_cursor_write_retries_from_previous_resume_point");
  } finally { await stream.close(); }
}

{
  const starts = [], gaps = [], failures = [];
  const stream = resumableOrderedStream({ ...timings, label: "fixture-rejected-cursor", initialCursor: "4",
    subscribeLive(cursor) { starts.push(cursor); return queue(); },
    async *fetchMissed() { throw new RangeError("fixture server rejected cursor"); },
    async processMissed(value) { return item(value); }, async processLive(value) { return item(value); },
    isCursorRejectedError(error) { return error instanceof RangeError; },
    async onCursorRejected(cursor) { gaps.push(cursor); },
    async onFailure(error, phase) { failures.push([error instanceof RangeError, phase]); },
  });
  try {
    await assert.rejects(stream[Symbol.asyncIterator]().next(), /Server rejected resume cursor/);
    assert.deepEqual(gaps, ["4"]); assert.deepEqual(starts, ["4"]);
    assert.deepEqual(failures, [[true, "catch-up"]]);
    cases.push("actual_native_cursor_rejection_requires_embedding_recovery_and_never_falls_back_to_live");
    cases.push("actual_native_failure_callback_observes_typed_cause_without_changing_cursor");
  } finally { await stream.close(); }
}

{
  const starts = [];
  const stream = resumableOrderedStream({ ...timings, label: "fixture-native-default",
    subscribeLive(cursor) { starts.push(cursor); return queue([1]); },
    async *fetchMissed() { throw new Error("default native path unexpectedly requested history"); },
    async processMissed(value) { return item(value); }, async processLive(value) { return item(value); },
  });
  try {
    assert.equal((await stream[Symbol.asyncIterator]().next()).value, "value-1");
    assert.deepEqual(starts, [undefined]);
    cases.push("native_nonembedded_default_does_not_acquire_an_invented_cursor");
  } finally { await stream.close(); }
}

const result = { schema: 1, passed: cases.length, cases,
  scope: "actual prepared Spectrum resumableOrderedStream and Repeater", substitutions: ["live and catch-up transport iterators", "durable cursor callback"],
  external_network: false, live_Photon_verified: false, SQLite_verified_by_this_probe: false };
await fs.writeFile(output, JSON.stringify(result, null, 2) + "\n");
console.log(JSON.stringify(result));
