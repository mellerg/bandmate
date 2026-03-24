import * as Tone from 'tone';
import type { NoteEvent } from './WebSocketClient';

// ── Sample sources ────────────────────────────────────────────────────────────
// Drum samples — bundled in /public/drums/ (served by Vite / the backend)
const DRUMS_BASE = '/drums/';

// Salamander Grand Piano — real recorded Steinway, hosted by Tone.js project
const PIANO_BASE = 'https://tonejs.github.io/audio/salamander/';
const PIANO_URLS: Record<string, string> = {
  A3: 'A3.mp3', C4: 'C4.mp3', 'D#4': 'Ds4.mp3', 'F#4': 'Fs4.mp3',
  A4: 'A4.mp3', C5: 'C5.mp3', 'D#5': 'Ds5.mp3', 'F#5': 'Fs5.mp3',
  A5: 'A5.mp3', C6: 'C6.mp3',
};

// Electric Bass (finger-style) — nbrosowsky/tonejs-instruments on GitHub Pages
const BASS_BASE = 'https://nbrosowsky.github.io/tonejs-instruments/samples/bass-electric/';
const BASS_URLS: Record<string, string> = {
  'A#1': 'As1.mp3', 'C#2': 'Cs2.mp3', E2: 'E2.mp3', G2: 'G2.mp3',
  'A#2': 'As2.mp3', 'C#3': 'Cs3.mp3', E3: 'E3.mp3', G3: 'G3.mp3',
};

// ── BandPlayer ────────────────────────────────────────────────────────────────

export class BandPlayer {
  // Drums — real recorded samples
  private kickSampler: Tone.Sampler;
  private snareSampler: Tone.Sampler;
  private hatSampler: Tone.Sampler;

  // Bass & keys — real recorded samples
  private bassSampler: Tone.Sampler;
  private keysSampler: Tone.Sampler;
  private keysReverb: Tone.Reverb;

  private isReady = false;

  constructor() {
    // ── Drums: real recorded samples ────────────────────────────────────
    // Each sample is mapped to A3 so Tone.js plays it at original pitch.
    this.kickSampler = new Tone.Sampler({ urls: { A3: 'Kick.mp3' }, baseUrl: DRUMS_BASE });
    this.kickSampler.volume.value = 0;
    this.kickSampler.toDestination();

    this.snareSampler = new Tone.Sampler({ urls: { A3: 'Snare.mp3' }, baseUrl: DRUMS_BASE });
    this.snareSampler.volume.value = -2;
    this.snareSampler.toDestination();

    this.hatSampler = new Tone.Sampler({ urls: { A3: 'Hihat.mp3' }, baseUrl: DRUMS_BASE });
    this.hatSampler.volume.value = -6;
    this.hatSampler.toDestination();

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
          this.kickSampler.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
        } else if (event.note === 'snare') {
          this.snareSampler.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
        } else {
          this.hatSampler.triggerAttackRelease('A3', event.duration, toneTime, event.velocity);
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
    this.kickSampler.dispose();
    this.snareSampler.dispose();
    this.hatSampler.dispose();
    this.bassSampler.dispose();
    this.keysSampler.dispose();
    this.keysReverb.dispose();
    this.isReady = false;
  }
}
