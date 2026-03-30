/**
 * AudioWorklet processor — runs on the dedicated audio thread.
 * Accumulates 128-sample blocks until reaching chunkSize, then
 * transfers the buffer to the main thread via postMessage.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(2048);
    this._offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    const samples = input[0]; // mono channel, 128 samples
    let i = 0;
    while (i < samples.length) {
      const space = this._buffer.length - this._offset;
      const toCopy = Math.min(space, samples.length - i);
      this._buffer.set(samples.subarray(i, i + toCopy), this._offset);
      this._offset += toCopy;
      i += toCopy;

      if (this._offset === this._buffer.length) {
        // Transfer ownership of the buffer (zero-copy) then allocate fresh
        this.port.postMessage(this._buffer.buffer, [this._buffer.buffer]);
        this._buffer = new Float32Array(2048);
        this._offset = 0;
      }
    }
    return true; // keep processor alive
  }
}

registerProcessor('pcm-processor', PCMProcessor);
