export class AudioCapture {
  private audioContext: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private analyser: AnalyserNode | null = null;

  public onAudioChunk: ((pcmData: Float32Array) => void) | null = null;
  public onWaveformData: ((data: Uint8Array) => void) | null = null;

  readonly sampleRate = 22050;

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

    // Analyser for waveform visualization (unchanged)
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.source.connect(this.analyser);

    // AudioWorkletNode replaces the deprecated ScriptProcessorNode.
    // The worklet runs on a dedicated audio thread — no main-thread jitter.
    await this.audioContext.audioWorklet.addModule('/audio-processor.js');
    this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm-processor');

    this.workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      if (this.onAudioChunk) {
        this.onAudioChunk(new Float32Array(e.data));
      }
    };

    // Connect source → worklet. The worklet output is silent (not connected
    // to destination) so mic audio never plays back through speakers.
    this.source.connect(this.workletNode);

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
    this.workletNode?.disconnect();
    this.source?.disconnect();
    this.analyser?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.audioContext?.close();
    this.workletNode = null;
    this.source = null;
    this.analyser = null;
    this.stream = null;
    this.audioContext = null;
  }
}
