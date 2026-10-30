// Fixed embedding boundary around the native SDK's small cloud control calls.
// No account URL, redirect, inherited proxy or response body reaches the agent.
export function nativeFailure(error) {
  const code = error?.grpcCode;
  if (code === 16 || code === 7) return { state: "authentication-refused", retry_after: 0 };
  if (code === 8) return { state: "rate-limited", retry_after: 60 };
  return { state: "transport-unavailable", retry_after: 2 };
}

export function selectTokenData(data, phone) {
  if (!data || !Number.isFinite(data.expiresIn) || data.expiresIn <= 0 || data.expiresIn > 604800) {
    throw new Error("bounded native Photon token lifetime required");
  }
  const validToken = (token) => typeof token === "string" && /^[\x21-\x7e]{16,8192}$/.test(token);
  if (phone === "shared") {
    if (data.type !== "shared" || !validToken(data.token)) throw new Error("approved shared Photon identity required");
    return data;
  }
  if (!/^\+[1-9][0-9]{6,14}$/.test(phone || "") || data.type !== "dedicated" ||
      !data.auth || typeof data.auth !== "object" || Array.isArray(data.auth) ||
      !data.numbers || typeof data.numbers !== "object" || Array.isArray(data.numbers)) {
    throw new Error("approved dedicated Photon identity required");
  }
  const entries = Object.entries(data.auth);
  if (entries.length > 64) throw new Error("bounded Photon line catalogue required");
  const selected = entries.filter(([id]) => data.numbers[id] === phone);
  if (selected.length !== 1 || !/^[A-Za-z0-9-]{1,63}$/.test(selected[0][0]) || !validToken(selected[0][1])) {
    throw new Error("one exact approved Photon line required");
  }
  const [id, token] = selected[0];
  return { ...data, auth: { [id]: token }, numbers: { [id]: phone } };
}

export function boundedCloud({ origin, project, request, report, current, deadlineMs = 15000 }) {
  const base = new URL(origin);
  if (base.protocol !== "https:" || base.pathname !== "/" || base.username || base.password || base.search || base.hash ||
      typeof project !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(project) ||
      ![request, report, current].every((fn) => typeof fn === "function")) throw new Error("fixed Photon cloud boundary required");
  const routes = new Map([["GET /projects/" + project + "/", true],
    ["POST /projects/" + project + "/imessage/tokens", true], ["GET /projects/" + project + "/platforms/", false]]);
  return async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input?.url);
    const method = init.method || "GET";
    const authenticated = routes.get(method + " " + url.pathname);
    if (url.origin !== base.origin || url.username || url.password || url.search || url.hash || authenticated === undefined || init.body != null) {
      throw new Error("unreviewed Photon cloud operation refused");
    }
    const headers = new Headers(init.headers);
    if (authenticated && !/^Basic [A-Za-z0-9+/]+=*$/.test(headers.get("authorization") || "")) {
      throw new Error("native Photon project authorization required");
    }
    await current();
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), deadlineMs); timer.unref?.();
    let response;
    try {
      response = await request(url.href, { ...init, redirect: "error", signal: abort.signal });
      if (response.status === 401 || response.status === 403) {
        await report({ state: "authentication-refused", retry_after: 0 });
        throw new Error("Photon project authentication refused");
      }
      if (response.status === 429) {
        const retry = response.headers.get("retry-after");
        const delay = /^\d{1,8}$/.test(retry || "") ? Number(retry) :
          retry && Number.isFinite(Date.parse(retry)) ? Math.ceil((Date.parse(retry) - Date.now()) / 1000) : 60;
        await report({ state: "rate-limited", retry_after: Math.min(86400, Math.max(1, delay)) });
        throw new Error("Photon project rate limited");
      }
      if (response.status !== 200) throw new Error("Photon cloud response unavailable");
      const size = response.headers.get("content-length");
      if (size !== null && (!/^\d{1,8}$/.test(size) || Number(size) > 65536)) throw new Error("Photon cloud response exceeds bound");
      const reader = response.body?.getReader();
      if (!reader) throw new Error("Photon cloud JSON body required");
      const chunks = []; let length = 0;
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          length += value.byteLength;
          if (length > 65536) throw new Error("Photon cloud response exceeds bound");
          chunks.push(value);
        }
      } finally { reader.cancel().catch(() => {}); reader.releaseLock(); }
      await current();
      return new Response(Buffer.concat(chunks, length), { status: 200, headers: { "content-type": "application/json" } });
    } catch (error) {
      abort.abort();
      if (response?.body && !response.body.locked) response.body.cancel().catch(() => {});
      // Native bodies, issued tokens and arbitrary SDK diagnostics never cross
      // the private finite-status RPC. A terminal reason survives later errors.
      throw new Error(error?.message?.startsWith("Photon ") ? error.message : "Photon cloud transport unavailable");
    } finally { clearTimeout(timer); }
  };
}
