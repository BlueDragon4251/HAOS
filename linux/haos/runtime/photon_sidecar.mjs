#!/usr/bin/env node
// Fixed HAOS embedding for the actual prepared Hermes Photon sidecar.
// No module/host/program path is read from owner input or an incoming message.
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { readBinary } from "./photon_bounded_stream.mjs";
import { boundedCloud, nativeFailure, selectTokenData } from "./photon_cloud.mjs";

// Bind lifetime before any network/SDK initialization. The write end belongs
// only to the supervising Python process; it is never passed to another child.
process.stdin.resume();
process.stdin.on("end", () => process.kill(process.pid, "SIGKILL"));
process.stdin.on("error", () => process.kill(process.pid, "SIGKILL"));

const uid = process.getuid(), gid = process.getgid();
const account = fs.readFileSync("/etc/passwd", "utf8").split("\n")
  .map((line) => line.split(":" )).find((row) => row[0] === "haos-gateway");
const status = fs.readFileSync("/proc/self/status", "utf8");
if (!account || uid === 0 || uid !== Number(account[2]) || gid !== Number(account[3]) ||
    process.getgroups().some((group) => group !== gid) || !/^NoNewPrivs:\s+1$/m.test(status)) {
  throw new Error("unprivileged hardened HAOS gateway identity required");
}
// The Unix socket exists before the listen callback executes. Create it with
// private permissions immediately so the supervisor never observes a public
// transient mode and correctly refuses startup.
process.umask(0o077);
const control = process.env.HAOS_PHOTON_CONTROL_SOCKET;
const policy = process.env.HAOS_PHOTON_POLICY_SOCKET;
const token = process.env.PHOTON_SIDECAR_TOKEN;
if (!/^[a-f0-9]{64}$/.test(token || "")) throw new Error("private Photon launch token required");
function directory(file) {
  if (typeof file !== "string" || !path.isAbsolute(file) || Buffer.byteLength(file) > 100 ||
      path.resolve(file) !== file || fs.realpathSync(path.dirname(file)) !== path.dirname(file)) {
    throw new Error("canonical private Photon socket path required");
  }
  const info = fs.lstatSync(path.dirname(file));
  if (!info.isDirectory() || info.uid !== uid || (info.mode & 0o077)) throw new Error("private Photon socket parent required");
}
directory(control); directory(policy);
const peer = fs.lstatSync(policy);
if (!peer.isSocket() || peer.uid !== uid || (peer.mode & 0o077) || peer.nlink !== 1) throw new Error("private Photon policy socket required");
if (fs.existsSync(control)) throw new Error("Photon control path already exists");

function rpc(route, data) {
  const encoded = Buffer.from(JSON.stringify(data));
  if (encoded.length > 24 * 1024 * 1024 + 4096) return Promise.reject(new Error("Photon control request too large"));
  return new Promise((resolve, reject) => {
    let timer, settled = false;
    const fail = () => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      const error = new Error("private Photon authority or custody unavailable");
      error.retryable = true;
      reject(error);
    };
    const request = http.request({ socketPath: policy, path: route, method: "POST", agent: false,
      headers: { "Content-Type": "application/json", "Content-Length": encoded.length,
        "X-Hermes-Sidecar-Token": token } }, (response) => {
      const chunks = []; let length = 0;
      response.on("data", (chunk) => {
        length += chunk.length;
        if (length > 4096) { response.destroy(); request.destroy(); fail(); }
        else chunks.push(chunk);
      });
      response.on("error", fail);
      response.on("end", () => {
        if (settled) return;
        if (response.statusCode !== 200) return fail();
        try {
          const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          if (!value || typeof value.approved !== "boolean") return fail();
          settled = true; clearTimeout(timer); resolve(value);
        } catch { fail(); }
      });
    });
    request.on("error", fail);
    timer = setTimeout(() => { request.destroy(); fail(); }, 10000);
    request.end(encoded);
  });
}

const sources = new Map();
let active = null;
const resume = await rpc("/resume", {});
if (resume.approved !== true || !/^(0|[1-9][0-9]{0,15})$/.test(resume.cursor || "") ||
    !Number.isSafeInteger(Number(resume.cursor))) throw new Error("durable Photon resume cursor required");
const report = async (value) => {
  if ((await rpc("/native-status", value)).approved !== true) throw new Error("Photon native status unavailable");
};
globalThis.fetch = boundedCloud({ origin: "https://spectrum.photon.codes", project: process.env.PHOTON_PROJECT_ID,
  request: globalThis.fetch.bind(globalThis), report, current: async () => {
    if ((await rpc("/lease", {})).approved !== true) throw new Error("Photon authority or retry budget refused");
  } });
globalThis[Symbol.for("hermes.photon.sdk.transport")] = Object.freeze({
  disableAutomaticContactSharing: true,
  disableAutomaticRetries: true,
  avoidReplyHydration: true,
  initialCursor: resume.cursor,
  async selectTokenData(data) {
    try { return selectTokenData(data, process.env.HAOS_PHOTON_PHONE); }
    catch {
      await report({ state: "identity-refused", retry_after: 0 });
      throw new Error("approved Photon account line unavailable");
    }
  },
  async streamFailure(error) {
    await report(nativeFailure(error));
    // The supervisor applies the persistent account budget before another
    // process may reconnect. Do not let the SDK race an immediate retry.
    throw new Error("Photon native stream needs supervised recovery");
  },
  async commitCursor(cursor) {
    if ((await rpc("/cursor", { cursor })).approved !== true) {
      const error = new Error("Photon resume custody unavailable"); error.retryable = true; throw error;
    }
  },
  async cursorRejected(cursor) {
    await rpc("/gap", { cursor });
    throw new Error("Photon resume cursor needs inspected owner recovery");
  },
  async admitEvent(event, phone, cursor) {
    // Bound prefetch bookkeeping as well as persistent custody. An RPC/storage
    // error is retryable, not an SDK mapping failure that may discard an event.
    if (sources.size >= 128 && !sources.has(event?.message?.guid)) {
      const error = new Error("Photon source prefetch capacity reached"); error.retryable = true; throw error;
    }
    const result = await rpc("/admit", { event, phone, cursor });
    if (result.approved !== true) return false;
    if (!/^[a-f0-9]{64}$/.test(result.source || "") || !event?.message?.guid) throw new Error("invalid Photon retained source");
    sources.set(event.message.guid, result.source);
    await report({ state: "upstream-observed", retry_after: 0 });
    return true;
  },
});

globalThis[Symbol.for("hermes.photon.transport")] = Object.freeze({
  async admitInbound(space, message) {
    active = null;
    const source = sources.get(message?.id);
    if (!source) return false;
    const result = await rpc("/current", { source });
    const envelope = result.envelope;
    if (result.approved !== true || !envelope || envelope.message_id !== message.id ||
        envelope.sender !== message.sender?.id || envelope.chat !== space?.id) return false;
    active = { source, id: message.id };
    return true;
  },
  async custodyInbound(event) {
    if (!active || active.id !== event?.messageId) return false;
    const result = await rpc("/custody", { source: active.source, event });
    if (result.approved !== true) return false;
    sources.delete(event.messageId); active = null;
    return true;
  },
  async readBinary(content, cap) {
    if (!active) throw new Error("no approved Photon source for attachment");
    const source = active.source;
    return await readBinary(content, Math.min(cap, 8 * 1024 * 1024),
      async () => (await rpc("/current", { source })).approved === true);
  },
  async authorizeRequest(request) {
    if (!((request.method === "GET" && request.url === "/inbound") ||
          (request.method === "POST" && ["/healthz", "/shutdown", "/send"].includes(request.url)))) return false;
    return (await rpc("/lease", {})).approved === true;
  },
  async authorizeBody(request, body) {
    // Root durably consumes the exact source/recipient/body capability before
    // the actual SDK may issue its one reviewed text-reply RPC.
    return request.url === "/send" && (await rpc("/output", body)).approved === true;
  },
  async writeFailed(error) { await report(nativeFailure(error)); },
  listen(server) {
    directory(control);
    server.listen(control, () => { fs.chmodSync(control, 0o600); });
  },
});

// These side effects are never silently enabled by an inherited environment.
process.env.PHOTON_TELEMETRY = "false";
process.env.PHOTON_READ_RECEIPTS = "false";
process.env.PHOTON_STREAM_SILENCE_PROBE_MS = "0";
process.env.PHOTON_MAX_INLINE_ATTACHMENT_BYTES = String(8 * 1024 * 1024);
process.env.PHOTON_SIDECAR_WATCH_STDIN = "1";
let checking = false;
const monitor = setInterval(async () => {
  if (checking) return;
  checking = true;
  try {
    if ((await rpc("/lease", {})).approved !== true) process.kill(process.pid, "SIGTERM");
  } catch { process.kill(process.pid, "SIGTERM"); }
  finally { checking = false; }
}, 500);
monitor.unref();
await import("/usr/lib/haos/hermes/plugins/platforms/photon/sidecar/index.mjs");
