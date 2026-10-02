// AudioWorklet that forwards mono microphone frames to the main thread. Served as a static asset
// (not bundled) because the shell's CSP allows scripts from 'self' only, not blob: URLs.
// Frames are posted at ~20 ms granularity (context sample rate); resampling happens in the page.
class HermesCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    // Fixed frame size; the buffer is transferred on post, so the length must not be re-read from it.
    this.frameLength = Math.max(128, Math.round(sampleRate / 50))
    this.chunk = new Float32Array(this.frameLength)
    this.filled = 0
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]

    if (!channel) {
      return true
    }

    let offset = 0

    while (offset < channel.length) {
      const room = this.chunk.length - this.filled
      const take = Math.min(room, channel.length - offset)
      this.chunk.set(channel.subarray(offset, offset + take), this.filled)
      this.filled += take
      offset += take

      if (this.filled === this.frameLength) {
        const frame = this.chunk
        this.chunk = new Float32Array(this.frameLength)
        this.filled = 0
        this.port.postMessage(frame, [frame.buffer])
      }
    }

    return true
  }
}

registerProcessor('hermes-capture', HermesCaptureProcessor)
