// Reads the actual Spectrum Attachment.stream(), never Attachment.read().
// The caller supplies fresh independent authority checks, not SDK allowlists.
export async function readBinary(content, cap, current, { timeoutMs = 30000 } = {}) {
  if (!content || typeof content.stream !== "function" ||
      typeof current !== "function" || !Number.isSafeInteger(cap) ||
      cap < 1 || cap > 8 * 1024 * 1024 || !Number.isSafeInteger(timeoutMs) ||
      timeoutMs < 1 || timeoutMs > 30000) {
    throw new Error("bounded Photon attachment stream required");
  }
  if (!Number.isSafeInteger(content.size) || content.size < 1 || content.size > cap) {
    throw new Error("invalid Photon attachment size");
  }
  let reader, timer, expired = false;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      expired = true;
      if (reader) void reader.cancel().catch(() => {});
      reject(new Error("Photon attachment deadline exceeded"));
    }, timeoutMs);
  });
  const bounded = (operation) => Promise.race([Promise.resolve().then(operation), deadline]);
  const check = async () => {
    if (await bounded(current) !== true) throw new Error("Photon attachment authority withdrawn");
  };
  try {
    await check();
    const opening = Promise.resolve().then(() => content.stream());
    // A stream that completes opening after the deadline must also be closed.
    void opening.then((stream) => {
      if (expired && stream && typeof stream.cancel === "function") void stream.cancel().catch(() => {});
    }, () => {});
    const stream = await bounded(() => opening);
    if (!stream || typeof stream.getReader !== "function") throw new Error("native byte stream required");
    reader = stream.getReader();
    const chunks = [];
    let total = 0;
    for (;;) {
      await check();
      const { done, value } = await bounded(() => reader.read());
      if (done) break;
      if (!(value instanceof Uint8Array) || value.byteLength < 1) throw new Error("invalid Photon attachment chunk");
      total += value.byteLength;
      if (total > cap || total > content.size) throw new Error("Photon attachment size exceeded");
      chunks.push(Buffer.from(value));
    }
    await check();
    if (total !== content.size) throw new Error("truncated Photon attachment");
    return Buffer.concat(chunks, total);
  } finally {
    clearTimeout(timer);
    // Cancellation may itself hang on a broken remote stream. Do not hold the
    // private gateway process indefinitely while its supervisor withdraws it.
    if (reader) void reader.cancel().catch(() => {});
  }
}
