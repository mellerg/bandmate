import * as Tone from 'tone';
import type { NoteEvent } from './WebSocketClient';

// Salamander Grand Piano samples — real recorded piano notes, interpolated by Tone.js.
// Hosted by the Tone.js project: https://tonejs.github.io/audio/salamander/
// Using a subset (every 3–4 semitones) for fast loading, covering the C3–C6 range we need.
const SALAMANDER_BASE = 'https://tonejs.github.io/audio/salamander/';
const SALAMANDER_URLS: Record<string, string> = {
  A3: 'A3.mp3', C4: 'C4.mp3', 'D#4': 'Ds4.mp3', 'F#4': 'Fs4.mp3',
  A4: 'A4.mp3', C5: 'C5.mp3', 'D#5': 'Ds5.mp3', 'F#5': 'Fs5.mp3',
  A5: 'A5.mp3', C6: 'C6.mp3',
};

export class BandPlayer {
  private kickSynth: Tone.MembraneSynth;
  private snareSynth: Tone.NoiseSynth;
  private hatSynth: Tone.MetalSynth;
  private bassSynth: Tone.MonoSynth;
  private keysSampler: Tone.Sampler;
  private keysReverb: Tone.Reverb;
  private isReady = false;

  constructor() {
    // ── Kick ────────────────────────────────────────────────────────────
    this.kickSynth = new Tone.MembraneSynth({
      pitchDecay: 0.08,
      octaves: 8,
      envelope: { attack: 0.001, decay: 0.4, sustain: 0, release: 0.1 },
    });
    this.kickSynth.volume.value = -2;
    this.kickSynth.toDestination();

    // ── Snare: white-noise burst ─────────────────────────────────────────
    this.snareSynth = new Tone.NoiseSynth({
      noise: { type: 'white' },
      envelope: { attack: 0.001, decay: 0.15, sustain: 0, release: 0.05 },
    });
    this.snareSynth.volume.value = -8;
    this.snareSynth.toDestination();

    // ── Hi-hat: metallic ring ────────────────────────────────────────────
    this.hatSynth = new Tone.MetalSynth({
      envelope: { attack: 0.001, decay: 0.05, release: 0.01 },
      harmonicity: 5.1,
      modulationIndex: 32,
      resonance: 4000,
      octaves: 1.5,
    });
    this.hatSynth.frequency.value = 400;
    this.hatSynth.volume.value = -14;
    this.hatSynth.toDestination();

    // ── Bass: warm electric feel ─────────────────────────────────────────
    this.bassSynth = new Tone.MonoSynth({
      oscillator: { type: 'sawtooth' },
      envelope: { attack: 0.01, decay: 0.2, sustain: 0.7, release: 0.3 },
      filterEnvelope: {
        attack: 0.01, decay: 0.25, sustain: 0.35, release: 0.3,
        baseFrequency: 180, octaves: 2.5,
      },
    });
    this.bassSynth.volume.value = -4;
    this.bassSynth.toDestination();

    // ── Keys: Salamander Grand Piano samples ─────────────────────────────
    // Real recorded piano notes — sounds immediately musical.
    // Tone.js interpolates between reference samples for notes not in the set.
    this.keysReverb = new Tone.Reverb({ decay: 1.8, wet: 0.25 }).toDestination();
    this.keysSampler = new Tone.Sampler({
      urls: SALAMANDER_URLS,
      release: 1.2,
      baseUrl: SALAMANDER_BASE,
    }).connect(this.keysReverb);
  }

  async init(): Promise<void> {
    await Tone.start();
    await Tone.loaded();   // wait for all piano samples to finish downloading
    this.isReady = true;
  }

  scheduleNote(event: NoteEvent, absoluteTime: number): void {
    if (!this.isReady) return;

    const delay = Math.max(0, absoluteTime - Tone.now());
    const toneTime = `+${delay}`;

    switch (event.instrument) {
      case 'drums':
        if (event.note === 'kick') {
          this.kickSynth.triggerAttackRelease('C1', event.duration, toneTime, event.velocity);
        } else if (event.note === 'snare') {
          this.snareSynth.triggerAttackRelease(event.duration, toneTime, event.velocity);
        } else {
          this.hatSynth.triggerAttackRelease(event.duration, toneTime, event.velocity);
        }
        break;
      case 'bass':
        this.bassSynth.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
        break;
      case 'keys':
        this.keysSampler.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
        break;
    }
  }

  dispose(): void {
    this.kickSynth.dispose();
    this.snareSynth.dispose();
    this.hatSynth.dispose();
    this.bassSynth.dispose();
    this.keysSampler.dispose();
    this.keysReverb.dispose();
    this.isReady = false;
  }
}
