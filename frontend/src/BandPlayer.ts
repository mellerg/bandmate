import * as Tone from 'tone';
import type { NoteEvent } from './WebSocketClient';

const DRUMS_BASE = '/drums/';

export class BandPlayer {
  // All instruments are null until init() creates them after Tone.start()
  private kickSampler: Tone.Sampler | null = null;
  private snareSampler: Tone.Sampler | null = null;
  private hatSampler: Tone.Sampler | null = null;
  private bassSynth: Tone.MonoSynth | null = null;
  private keysSynth: Tone.PolySynth<Tone.Synth> | null = null;
  private keysReverb: Tone.Reverb | null = null;

  private isReady = false;

  // Empty constructor — no Tone.js calls here.
  // Chrome blocks AudioContext before user gesture; constructing any Tone.js
  // node (Sampler, Synth, Reverb) before Tone.start() causes EncodingErrors.
  constructor() {}

  async init(): Promise<void> {
    // 1. Resume/unlock the AudioContext with the active user-gesture token.
    await Tone.start();

    // 2. Now that the context is running, create all audio nodes.
    this.kickSampler = new Tone.Sampler({ urls: { A3: 'Kick.mp3' }, baseUrl: DRUMS_BASE });
    this.kickSampler.volume.value = 2;
    this.kickSampler.toDestination();

    this.snareSampler = new Tone.Sampler({ urls: { A3: 'Snare.mp3' }, baseUrl: DRUMS_BASE });
    this.snareSampler.volume.value = 0;
    this.snareSampler.toDestination();

    this.hatSampler = new Tone.Sampler({ urls: { A3: 'Hihat.mp3' }, baseUrl: DRUMS_BASE });
    this.hatSampler.volume.value = -6;
    this.hatSampler.toDestination();

    this.bassSynth = new Tone.MonoSynth({
      oscillator: { type: 'sawtooth' },
      envelope: { attack: 0.01, decay: 0.3, sustain: 0.3, release: 0.6 },
      filterEnvelope: {
        attack: 0.01, decay: 0.2, sustain: 0.3, release: 0.6,
        baseFrequency: 120, octaves: 2.5,
      },
    });
    this.bassSynth.volume.value = -4;
    this.bassSynth.toDestination();

    this.keysReverb = new Tone.Reverb({ decay: 1.5, wet: 0.3 }).toDestination();
    this.keysSynth = new Tone.PolySynth(Tone.Synth, {
      oscillator: { type: 'triangle' },
      envelope: { attack: 0.04, decay: 0.3, sustain: 0.4, release: 1.2 },
    });
    this.keysSynth.volume.value = -8;
    this.keysSynth.connect(this.keysReverb);

    // 3. Wait for drum samples to finish downloading and decoding.
    try {
      await Tone.loaded();
    } catch (e) {
      console.warn('[BandPlayer] Sample load error (synths will still work):', e);
    }

    this.isReady = true;
    console.log('[BandPlayer] Ready');
  }

  scheduleNote(event: NoteEvent, absoluteTime: number): void {
    if (!this.isReady) return;

    const delay = Math.max(0, absoluteTime - Tone.now());
    const toneTime = `+${delay}`;

    try {
      switch (event.instrument) {
        case 'drums':
          if (event.note === 'kick') {
            this.kickSampler?.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
          } else if (event.note === 'snare') {
            this.snareSampler?.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
          } else {
            this.hatSampler?.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
          }
          break;
        case 'bass':
          this.bassSynth?.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
          break;
        case 'keys':
          this.keysSynth?.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
          break;
      }
    } catch (err) {
      console.warn('[BandPlayer] scheduleNote error:', err);
    }
  }

  dispose(): void {
    this.kickSampler?.dispose();
    this.snareSampler?.dispose();
    this.hatSampler?.dispose();
    this.bassSynth?.dispose();
    this.keysSynth?.dispose();
    this.keysReverb?.dispose();
    this.isReady = false;
  }
}
