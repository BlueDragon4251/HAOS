#!/usr/bin/env node
// Loopback-only real TLS/HTTP and protobuf/gRPC peers for the actual SDK.
import fs from "node:fs";
import path from "node:path";
import https from "node:https";
import net from "node:net";
import { createRequire } from "node:module";

const config = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const require = createRequire(path.join(config.sidecar, "package.json"));
const grpc = require("@grpc/grpc-js");
const loader = require("@grpc/proto-loader");
const proto = path.join(config.sidecar, "node_modules/@photon-ai/advanced-imessage/proto");
const definitions = loader.loadSync(["message_service.proto", "event_service.proto", "poll_service.proto", "group_service.proto"].map(
  (name) => path.join(proto, "photon/imessage/v1", name)), {
  includeDirs: [proto], keepCase: false, longs: Number, enums: String, defaults: true, oneofs: true,
});
const services = grpc.loadPackageDefinition(definitions).photon.imessage.v1;
const counts = { http: {}, grpc: {}, refused_auth: 0, emitted: 0, cancelled: {}, timer_ticks: 0, writes: [], transport_resets: 0 };
function publish(file, value) {
  fs.writeFileSync(file + ".tmp", JSON.stringify(value));
  fs.renameSync(file + ".tmp", file);
}
const save = () => publish(config.counts, counts);
const count = (kind, name) => { counts[kind][name] = (counts[kind][name] || 0) + 1; save(); };
const tls = { key: fs.readFileSync(config.key), cert: fs.readFileSync(config.cert) };
const basic = "Basic " + Buffer.from(config.project_id + ":" + config.project_secret).toString("base64");
const http = https.createServer(tls, (request, response) => {
  count("http", request.method + " " + request.url);
  const base = "/projects/" + config.project_id;
  if (request.url !== base + "/platforms/" && request.headers.authorization !== basic) {
    counts.refused_auth++; save(); response.writeHead(401); return response.end();
  }
  let data;
  const scenario = config.scenario || "normal";
  const tokenRoute = request.method === "POST" && request.url === base + "/imessage/tokens";
  const tokenRequests = counts.http["POST " + base + "/imessage/tokens"] || 0;
  const status = scenario === "http401" ? 401 : scenario === "http403" ? 403 : scenario === "http429" ? 429 :
    scenario === "refresh401" && tokenRequests > 1 ? 401 : scenario === "refresh429" && tokenRequests > 1 ? 429 : null;
  if (tokenRoute && status) {
    response.writeHead(status, { "Content-Type": "application/json", "Retry-After": "90" });
    return response.end(JSON.stringify({ message: "fixture diagnostic " + config.native_token }));
  }
  if (request.method === "GET" && request.url === base + "/") data = { id: config.project_id, profile: { imessageSynced: false } };
  else if (tokenRoute) data = scenario === "wrong-line" ? { type: "dedicated", auth: { fixture: config.native_token }, numbers: { fixture: "+15550100009" }, expiresIn: 3600 } :
    scenario === "dedicated" ? { type: "dedicated", auth: { fixture: config.native_token, unapproved: config.native_token },
      numbers: { fixture: "+15550100002", unapproved: "+15550100009" }, expiresIn: 3600 } :
    { type: "shared", token: config.native_token, expiresIn: scenario.startsWith("refresh") ? 1 : 3600 };
  else if (request.method === "GET" && request.url === base + "/platforms/") data = {};
  else { response.writeHead(404); return response.end(); }
  response.writeHead(200, { "Content-Type": "application/json" }); response.end(JSON.stringify({ succeed: true, data }));
});
await new Promise((resolve) => http.listen(0, "127.0.0.1", resolve));
const server = new grpc.Server({ "grpc.max_receive_message_length": 8 * 1024 * 1024 });
const calls = new Set(); const timers = new Set();
const proxySockets = new Set(); let proxy = null;
function authenticated(call, method) {
  count("grpc", method);
  if (call.metadata.get("authorization")[0] !== "Bearer " + config.native_token) {
    counts.refused_auth++; save(); call.destroy({ code: grpc.status.UNAUTHENTICATED, details: "fixture bearer refused" }); return false;
  }
  return true;
}
function live(call, method, messages) {
  if (!authenticated(call, method)) return;
  calls.add(call); let sent = false;
  const timer = setInterval(() => {
    counts.timer_ticks++; save();
    if (!sent && fs.existsSync(config.emit)) {
      sent = true;
      if (messages && ["grpc401", "grpc429"].includes(config.scenario)) {
        call.emit("error", { code: config.scenario === "grpc401" ? grpc.status.UNAUTHENTICATED : grpc.status.RESOURCE_EXHAUSTED,
          details: "fixture native refusal " + config.native_token });
        return;
      }
      if (messages) for (const frame of config.frames) { call.write(frame); counts.emitted++; }
      save();
    }
  }, 20);
  timers.add(timer);
  call.on("cancelled", () => { counts.cancelled[method] = (counts.cancelled[method] || 0) + 1; save(); clearInterval(timer); timers.delete(timer); calls.delete(call); });
}
const unknown = (name) => (call, callback) => {
  count("grpc", name);
  const error = { code: grpc.status.UNIMPLEMENTED, details: "unreviewed fixture method" };
  if (callback) callback(error); else call.destroy(error);
};
function methods(definition, reviewed) {
  return Object.fromEntries(Object.keys(definition.service).map((name) =>
    [name, reviewed[name[0].toLowerCase() + name.slice(1)] || unknown(name)]));
}
server.addService(services.MessageService.service, methods(services.MessageService, {
  subscribeMessageEvents: (call) => live(call, "SubscribeMessageEvents", true),
  sendTextMessage(call, callback) {
    if (!authenticated(call, "SendTextMessage")) return;
    const body = call.request;
    if (body.chatGuid !== config.reply_chat || body.text !== "approved native reply" ||
        body.replyTo?.messageGuid !== config.reply_source || body.enableLinkPreview === true ||
        body.enableDataDetection === true || body.formatting?.length) {
      return callback({ code: grpc.status.INVALID_ARGUMENT, details: "fixture wire contract changed" });
    }
    counts.writes.push({ chat: body.chatGuid, reply_to: body.replyTo.messageGuid }); save();
    if (config.scenario === "reply-reset" && counts.writes.length === 1) {
      counts.transport_resets++; save();
      // Drop real TLS connections after the actual request reached this peer.
      // Keep the real gRPC service and TCP proxy listening: an automatic resend
      // could reconnect successfully and would be counted as a second write.
      for (const socket of proxySockets) socket.destroy();
      return;
    }
    if (config.scenario === "reply-withdraw") {
      fs.writeFileSync(config.write_observed, "write reached actual gRPC peer"); return;
    }
    if (config.scenario === "reply-disconnect") {
      return callback({ code: grpc.status.UNAVAILABLE, details: "fixture receipt lost after native write" });
    }
    callback(null, { message: { guid: config.reply_receipt, content: { text: body.text },
      chatGuids: [body.chatGuid], isFromMe: true, dateCreated: { seconds: Math.floor(Date.now() / 1000), nanos: 0 } } });
  },
}));
server.addService(services.PollService.service, methods(services.PollService, {
  subscribePollEvents: (call) => live(call, "SubscribePollEvents", false),
}));
server.addService(services.GroupService.service, methods(services.GroupService, {
  subscribeGroupEvents: (call) => live(call, "SubscribeGroupEvents", false),
}));
server.addService(services.EventService.service, methods(services.EventService, {
  catchUpEvents(call) {
    if (!authenticated(call, "CatchUpEvents")) return;
    call.write({ complete: { headSequence: 0 } }); call.end();
  },
}));
const port = await new Promise((resolve, reject) => server.bindAsync("127.0.0.1:0",
  grpc.ServerCredentials.createSsl(null, [{ private_key: tls.key, cert_chain: tls.cert }], false),
  (error, port) => error ? reject(error) : resolve(port)));
let exposedPort = port;
if (config.scenario === "reply-reset") {
  proxy = net.createServer((front) => {
    const back = net.connect(port, "127.0.0.1");
    for (const socket of [front, back]) {
      proxySockets.add(socket); socket.on("error", () => { front.destroy(); back.destroy(); });
      socket.on("close", () => proxySockets.delete(socket));
    }
    front.pipe(back); back.pipe(front);
  });
  await new Promise((resolve) => proxy.listen(0, "127.0.0.1", resolve));
  exposedPort = proxy.address().port;
}
save();
publish(config.ready, { cloud: "https://127.0.0.1:" + http.address().port, grpc: "127.0.0.1:" + exposedPort });
async function stop() {
  for (const timer of timers) clearInterval(timer);
  for (const call of calls) call.end();
  for (const socket of proxySockets) socket.destroy();
  proxy?.close();
  server.forceShutdown(); http.close();
}
process.on("SIGTERM", stop); process.on("SIGINT", stop);
