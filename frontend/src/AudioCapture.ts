export class AudioCapture {
  private audioContext: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private analyser: AnalyserNode | null = null;

  public onAudioChunk: ((pcmData: Float32Array) => void) | null = null;
  public onWaveformData: ((data: Uint8Array) => void) | null = null;

  readonly sampleRate = 22050;
  readonly chunkSize = 2048;

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: this.sampleRate,
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });

    this.audioContext = new AudioContext({ sampleRate: this.sampleRate });
    this.source = this.audioContext.createMediaStreamSource(this.stream);

    // Analyser for waveform visualization
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.source.connect(this.analyser);

    // ScriptProcessor for raw PCM extraction.
    // Route through a silent gain node — the processor must be in the audio
    // graph to fire onaudioprocess, but mic audio must NOT reach the speakers.
    const silentGain = this.audioContext.createGain();
    silentGain.gain.value = 0;
    silentGain.connect(this.audioContext.destination);

    this.processor = this.audioContext.createScriptProcessor(this.chunkSize, 1, 1);
    this.source.connect(this.processor);
    this.processor.connect(silentGain);

    this.processor.onaudioprocess = (e) => {
      const inputData = e.inputBuffer.getChannelData(0);
      if (this.onAudioChunk) {
        this.onAudioChunk(new Float32Array(inputData));
      }
    };

    // Waveform loop
    const waveformData = new Uint8Array(this.analyser.frequencyBinCount);
    const tick = () => {
      if (!this.analyser) return;
      this.analyser.getByteTimeDomainData(waveformData);
      if (this.onWaveformData) this.onWaveformData(waveformData);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  stop(): void {
    this.processor?.disconnect();
    this.source?.disconnect();
    this.analyser?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.audioContext?.close();
    this.processor = null;
    this.source = null;
    this.analyser = null;
    this.stream = null;
    this.audioContext = null;
  }
}
