import * as Tone from 'tone';
import type { NoteEvent } from './WebSocketClient';

// ── Sample CDNs ───────────────────────────────────────────────────────────────
// Salamander Grand Piano — real recorded Steinway, hosted by Tone.js project
const PIANO_BASE = 'https://tonejs.github.io/audio/salamander/';
const PIANO_URLS: Record<string, string> = {
  A3: 'A3.mp3', C4: 'C4.mp3', 'D#4': 'Ds4.mp3', 'F#4': 'Fs4.mp3',
  A4: 'A4.mp3', C5: 'C5.mp3', 'D#5': 'Ds5.mp3', 'F#5': 'Fs5.mp3',
  A5: 'A5.mp3', C6: 'C6.mp3',
};

// Electric Bass (finger-style) — nbrosowsky/tonejs-instruments on GitHub Pages
// Covers E1–A#3, which spans the octave 2 range the conductor uses.
const BASS_BASE = 'https://nbrosowsky.github.io/tonejs-instruments/samples/bass-electric/';
const BASS_URLS: Record<string, string> = {
  'A#1': 'As1.mp3', 'C#2': 'Cs2.mp3', E2: 'E2.mp3', G2: 'G2.mp3',
  'A#2': 'As2.mp3', 'C#3': 'Cs3.mp3', E3: 'E3.mp3', G3: 'G3.mp3',
};

// ── BandPlayer ────────────────────────────────────────────────────────────────

export class BandPlayer {
  // Drums — synth-modelled (808/909 style: acceptable in blues & rock)
  private kickSynth: Tone.MembraneSynth;
  private snareSynth: Tone.NoiseSynth;
  private snareFilter: Tone.Filter;      // bandpass gives snare its "crack"
  private hatSynth: Tone.MetalSynth;

  // Bass & keys — real recorded samples
  private bassSampler: Tone.Sampler;
  private keysSampler: Tone.Sampler;
  private keysReverb: Tone.Reverb;

  private isReady = false;

  constructor() {
    // ── Kick: punchy sub-thump (808 style) ──────────────────────────────
    this.kickSynth = new Tone.MembraneSynth({
      pitchDecay: 0.06,
      octaves: 7,
      envelope: { attack: 0.001, decay: 0.38, sustain: 0, release: 0.1 },
    });
    this.kickSynth.volume.value = -2;
    this.kickSynth.toDestination();

    // ── Snare: filtered white noise — bandpass gives the "crack" ────────
    // The filter centres around the frequency where real snare wires resonate.
    this.snareFilter = new Tone.Filter({ frequency: 2200, type: 'bandpass', Q: 0.7 });
    this.snareFilter.toDestination();
    this.snareSynth = new Tone.NoiseSynth({
      noise: { type: 'white' },
      envelope: { attack: 0.001, decay: 0.18, sustain: 0.01, release: 0.08 },
    });
    this.snareSynth.volume.value = -5;
    this.snareSynth.connect(this.snareFilter);

    // ── Hi-hat: tight metallic ring (closed hat) ─────────────────────────
    this.hatSynth = new Tone.MetalSynth({
      envelope: { attack: 0.001, decay: 0.04, release: 0.01 },
      harmonicity: 5.1,
      modulationIndex: 32,
      resonance: 4000,
      octaves: 1.5,
    });
    this.hatSynth.frequency.value = 400;
    this.hatSynth.volume.value = -16;
    this.hatSynth.toDestination();

    // ── Electric bass: real finger-plucked samples ───────────────────────
    // Tone.js Sampler interpolates pitch between reference samples, so notes
    // like C2, A2, E2 will all sound like a real plucked bass guitar string.
    this.bassSampler = new Tone.Sampler({
      urls: BASS_URLS,
      release: 0.8,
      baseUrl: BASS_BASE,
    });
    this.bassSampler.volume.value = -2;
    this.bassSampler.toDestination();

    // ── Grand piano: Salamander recorded samples ─────────────────────────
    this.keysReverb = new Tone.Reverb({ decay: 1.8, wet: 0.25 }).toDestination();
    this.keysSampler = new Tone.Sampler({
      urls: PIANO_URLS,
      release: 1.2,
      baseUrl: PIANO_BASE,
    }).connect(this.keysReverb);
  }

  async init(): Promise<void> {
    await Tone.start();
    await Tone.loaded();   // wait for bass + piano samples (parallel download)
    this.isReady = true;
  }

  scheduleNote(event: NoteEvent, absoluteTime: number): void {
    if (!this.isReady) return;

    const toneTime = `+${Math.max(0, absoluteTime - Tone.now())}`;

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
        this.bassSampler.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
        break;
      case 'keys':
        this.keysSampler.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
        break;
    }
  }

  dispose(): void {
    this.kickSynth.dispose();
    this.snareSynth.dispose();
    this.snareFilter.dispose();
    this.hatSynth.dispose();
    this.bassSampler.dispose();
    this.keysSampler.dispose();
    this.keysReverb.dispose();
    this.isReady = false;
  }
}
