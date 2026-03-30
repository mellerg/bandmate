import * as Tone from 'tone';
import type { NoteEvent } from './WebSocketClient';

// Drum samples — bundled in /public/drums/ (served locally, always available)
const DRUMS_BASE = '/drums/';

export class BandPlayer {
  // Drums: real recorded samples (local — reliable)
  private kickSampler: Tone.Sampler;
  private snareSampler: Tone.Sampler;
  private hatSampler: Tone.Sampler;

  // Bass: synthesized (MonoSynth — no CDN dependency)
  private bassSynth: Tone.MonoSynth;

  // Keys: synthesized with reverb (PolySynth — no CDN dependency)
  private keysSynth: Tone.PolySynth<Tone.Synth>;
  private keysReverb: Tone.Reverb;

  private isReady = false;

  constructor() {
    // ── Drums: real recorded samples ────────────────────────────────────
    this.kickSampler = new Tone.Sampler({ urls: { A3: 'Kick.mp3' }, baseUrl: DRUMS_BASE });
    this.kickSampler.volume.value = 2;
    this.kickSampler.toDestination();

    this.snareSampler = new Tone.Sampler({ urls: { A3: 'Snare.mp3' }, baseUrl: DRUMS_BASE });
    this.snareSampler.volume.value = 0;
    this.snareSampler.toDestination();

    this.hatSampler = new Tone.Sampler({ urls: { A3: 'Hihat.mp3' }, baseUrl: DRUMS_BASE });
    this.hatSampler.volume.value = -6;
    this.hatSampler.toDestination();

    // ── Bass: synthesized — plucky sawtooth with filter envelope ─────────
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

    // ── Keys: polyphonic triangle with reverb — soft piano-like ─────────
    this.keysReverb = new Tone.Reverb({ decay: 1.5, wet: 0.3 }).toDestination();
    this.keysSynth = new Tone.PolySynth(Tone.Synth, {
      oscillator: { type: 'triangle' },
      envelope: { attack: 0.04, decay: 0.3, sustain: 0.4, release: 1.2 },
    });
    this.keysSynth.volume.value = -8;
    this.keysSynth.connect(this.keysReverb);
  }

  async init(): Promise<void> {
    // Tone.start() was already called before constructing this instance.
    // Just wait for drum sample files to finish downloading.
    await Tone.loaded();
    this.isReady = true;
    console.log('[BandPlayer] Ready — drums loaded, synths active');
  }

  scheduleNote(event: NoteEvent, absoluteTime: number): void {
    if (!this.isReady) return;

    const delay = Math.max(0, absoluteTime - Tone.now());
    const toneTime = `+${delay}`;

    try {
      switch (event.instrument) {
        case 'drums':
          if (event.note === 'kick') {
            this.kickSampler.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
          } else if (event.note === 'snare') {
            this.snareSampler.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
          } else {
            this.hatSampler.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
          }
          break;
        case 'bass':
          this.bassSynth.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
          break;
        case 'keys':
          this.keysSynth.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
          break;
      }
    } catch (err) {
      console.warn('[BandPlayer] scheduleNote error:', err);
    }
  }

  dispose(): void {
    this.kickSampler.dispose();
    this.snareSampler.dispose();
    this.hatSampler.dispose();
    this.bassSynth.dispose();
    this.keysSynth.dispose();
    this.keysReverb.dispose();
    this.isReady = false;
  }
}
