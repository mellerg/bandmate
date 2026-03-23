import * as Tone from 'tone';
import type { NoteEvent } from './WebSocketClient';

// Instrument note mappings for sampler
// In a real build, these point to actual WAV files in /public/samples/
// For the POC we use Tone.js synths as fallbacks

export class BandPlayer {
  private drumSynth: Tone.MembraneSynth;
  private bassSynth: Tone.MonoSynth;
  private keysSynth: Tone.PolySynth;
  private isReady = false;

  constructor() {
    this.drumSynth = new Tone.MembraneSynth({
      pitchDecay: 0.05,
      octaves: 6,
      envelope: { attack: 0.001, decay: 0.3, sustain: 0, release: 0.1 },
    }).toDestination();

    this.bassSynth = new Tone.MonoSynth({
      oscillator: { type: 'triangle' },
      envelope: { attack: 0.02, decay: 0.1, sustain: 0.8, release: 0.5 },
      filterEnvelope: { attack: 0.02, decay: 0.2, sustain: 0.5, release: 0.5, baseFrequency: 300, octaves: 2 },
    }).toDestination();

    this.keysSynth = new Tone.PolySynth(Tone.Synth, {
      oscillator: { type: 'sawtooth' },
      envelope: { attack: 0.05, decay: 0.2, sustain: 0.6, release: 1 },
    }).toDestination();

    this.keysSynth.set({ volume: -8 });
    this.bassSynth.set({ volume: -6 });
    this.drumSynth.set({ volume: -4 });
  }

  async init(): Promise<void> {
    await Tone.start();
    this.isReady = true;
  }

  scheduleNote(event: NoteEvent, absoluteTime: number): void {
    if (!this.isReady) return;

    const toneTime = `+${Math.max(0, absoluteTime - Tone.now())}`;

    switch (event.instrument) {
      case 'drums':
        this.drumSynth.triggerAttackRelease(
          event.note === 'kick' ? 'C1' : event.note === 'snare' ? 'E1' : 'A2',
          event.duration,
          toneTime,
          event.velocity
        );
        break;
      case 'bass':
        this.bassSynth.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
        break;
      case 'keys':
        this.keysSynth.triggerAttackRelease([event.note], event.duration, toneTime, event.velocity);
        break;
    }
  }

  dispose(): void {
    this.drumSynth.dispose();
    this.bassSynth.dispose();
    this.keysSynth.dispose();
    this.isReady = false;
  }
}
