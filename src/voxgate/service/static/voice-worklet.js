/* ============================================================================
   voice-worklet.js — AudioWorklet processor for the VoxGate Pipecat client
   ----------------------------------------------------------------------------
   Captures the microphone (Float32, at the AudioContext's sample rate) and
   resamples each channel to 16 kHz mono int16 LE PCM — the format pipecat's
   Groq Whisper STT expects — posting accumulated chunks to the main thread as
   Int16Array payloads ready to wrap in a `Frame.audio` protobuf message.
   ========================================================================== */

class VoiceResamplerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;      // Whisper expects 16 kHz mono PCM
    this.inbuf = new Float32Array(0); // pending source samples
    this.offset = 0;              // fractional source-sample cursor
    this.accuf = new Float32Array(0); // pending resampled float samples
    this.chunkSamples = 1600;     // 100 ms @16k -> 3200 bytes per posted chunk
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || ch.length === 0) return true;

    // Append new source samples.
    const n = this.inbuf.length + ch.length;
    const buf = new Float32Array(n);
    buf.set(this.inbuf);
    buf.set(ch, this.inbuf.length);
    this.inbuf = buf;

    // Linear-interpolate into the target rate.
    const ratio = sampleRate / this.targetRate;
    const outLen = Math.floor((this.inbuf.length - this.offset) / ratio);
    if (outLen > 0) {
      const res = new Float32Array(outLen);

      for (let j = 0; j < outLen; j++) {
        const fpos = this.offset + j * ratio;
        const i0 = Math.floor(fpos);
        const i1 = Math.min(i0 + 1, this.inbuf.length - 1);
        const frac = fpos - i0;
        res[j] = this.inbuf[i0] * (1 - frac) + this.inbuf[i1] * frac;
      }
      // Consume the portion of source used.
      const consumed = Math.floor(this.offset + outLen * ratio);
      const remain = this.inbuf.length - consumed;
      this.inbuf = remain > 0 ? this.inbuf.slice(consumed) : new Float32Array(0);
      this.offset = (this.offset + outLen * ratio) - consumed;

      // Accumulate resampled floats, emit when a full chunk is ready.
      const accLen = this.accuf.length + res.length;
      const acc = new Float32Array(accLen);
      acc.set(this.accuf);
      acc.set(res, this.accuf.length);
      this.accuf = acc;

      while (this.accuf.length >= this.chunkSamples) {
        const pcm = new Int16Array(this.chunkSamples);
        for (let k = 0; k < this.chunkSamples; k++) {
          const s = this.accuf[k];
          const clamp = s < -1 ? -1 : s > 1 ? 1 : s;
          pcm[k] = clamp < 0 ? clamp * 0x8000 : clamp * 0x7fff;
        }
        this.port.postMessage(pcm);
        this.accuf = this.accuf.slice(this.chunkSamples);
      }
    }

    return true;
  }
}

registerProcessor("voice-resampler", VoiceResamplerProcessor);