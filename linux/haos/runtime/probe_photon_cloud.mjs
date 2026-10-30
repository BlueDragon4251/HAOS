#!/usr/bin/env node
// Contract boundaries around the native SDK cloud fetch; actual SDK wire is
// checked separately by the TLS/gRPC profile probe.
import assert from "node:assert/strict";
import fs from "node:fs";
import { boundedCloud, nativeFailure, selectTokenData } from "./photon_cloud.mjs";
const cases = [], project = "fixture-project", origin = "https://spectrum.photon.codes";
const auth = { headers: { Authorization: "Basic Zml4dHVyZTpmaXh0dXJl" } };
let calls = 0, reports = [], active = true;
let reply = () => new Response('{"succeed":true,"data":{}}', { status: 200 });
const cloud = boundedCloud({ origin, project, request: async (url, init) => {
  calls++; assert.equal(init.redirect, "error"); assert.ok(init.signal instanceof AbortSignal); return reply();
}, report: async (value) => reports.push(value), current: async () => { if (!active) throw new Error("withdrawn"); } });
assert.deepEqual(await (await cloud(origin + "/projects/" + project + "/", auth)).json(), { succeed: true, data: {} });
cases.push("native_JSON_preserved_with_redirects_refused_and_abort_bound");
for (const [url, init] of [["https://other.invalid/projects/fixture-project/", auth],
  [origin + "/projects/fixture-project/?token=untrusted", auth], [origin + "/projects/another/", auth],
  [origin + "/projects/fixture-project/", { ...auth, method: "PATCH" }],
  [origin + "/projects/fixture-project/", { ...auth, body: "untrusted" }], [origin + "/projects/fixture-project/", {}]]) {
  const before = calls; await assert.rejects(cloud(url, init)); assert.equal(calls, before);
}
cases.push("unknown_host_project_query_method_body_and_missing_auth_refused_before_fetch");
for (const status of [401, 403]) {
  reply = () => new Response("fixture secret-shaped diagnostic must not pass", { status });
  await assert.rejects(cloud(origin + "/projects/fixture-project/", auth), /authentication refused/);
  assert.deepEqual(reports.at(-1), { state: "authentication-refused", retry_after: 0 });
}
cases.push("HTTP_401_and_403_finite_terminal_status_without_response_body");
reply = () => new Response("ignored", { status: 429, headers: { "Retry-After": "99999999" } });
await assert.rejects(cloud(origin + "/projects/fixture-project/", auth), /rate limited/);
assert.deepEqual(reports.at(-1), { state: "rate-limited", retry_after: 86400 });
cases.push("HTTP_429_persists_bounded_account_budget");
for (const advertised of [false, true]) {
  reply = () => new Response("x".repeat(65537), { status: 200, headers: advertised ? { "Content-Length": "65537" } : {} });
  await assert.rejects(cloud(origin + "/projects/fixture-project/", auth), /exceeds bound/);
}
cases.push("advertised_and_actual_cloud_response_size_capped");
active = false; const before = calls;
await assert.rejects(cloud(origin + "/projects/fixture-project/", auth)); assert.equal(calls, before);
cases.push("current_authority_required_before_cloud_fetch");
for (const code of [7, 16]) assert.deepEqual(nativeFailure({ grpcCode: code }), { state: "authentication-refused", retry_after: 0 });
assert.deepEqual(nativeFailure({ grpcCode: 8 }), { state: "rate-limited", retry_after: 60 });
assert.deepEqual(nativeFailure({ grpcCode: 14 }), { state: "transport-unavailable", retry_after: 2 });
cases.push("actual_native_typed_gRPC_codes_use_finite_auth_rate_transport_status");
const token = "fixture-native-token-123456", data = { type: "dedicated", expiresIn: 3600,
  auth: { approved: token, other: token }, numbers: { approved: "+15550100001", other: "+15550100009" } };
assert.deepEqual(selectTokenData(data, "+15550100001").auth, { approved: token });
assert.deepEqual(Object.keys(data.auth), ["approved", "other"]);
for (const value of ["shared", "+15550100002"]) assert.throws(() => selectTokenData(data, value));
assert.throws(() => selectTokenData({ ...data, numbers: { approved: "+15550100001", other: "+15550100001" } }, "+15550100001"));
assert.throws(() => selectTokenData({ ...data, auth: { "evil/host": token }, numbers: { "evil/host": "+15550100001" } }, "+15550100001"));
cases.push("dedicated_token_catalogue_selects_only_one_exact_approved_line_and_safe_host_label");
const receipt = { passed: cases.length, cases, scope: "embedding cloud boundary contract; fixture fetch responses", live_Photon_verified: false };
if (process.argv[2]) fs.writeFileSync(process.argv[2], JSON.stringify(receipt, null, 2) + "\n");
console.log(JSON.stringify(receipt));
