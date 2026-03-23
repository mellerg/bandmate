import * as Tone from 'tone';
import type { NoteEvent } from './WebSocketClient';

export class BandPlayer {
  private kickSynth: Tone.MembraneSynth;
  private snareSynth: Tone.NoiseSynth;
  private hatSynth: Tone.MetalSynth;
  private bassSynth: Tone.MonoSynth;
  private keysSynth: Tone.PolySynth;
  private reverb: Tone.Reverb;
  private isReady = false;

  constructor() {
    // Kick: pitched membrane decay
    this.kickSynth = new Tone.MembraneSynth({
      pitchDecay: 0.08,
      octaves: 8,
      envelope: { attack: 0.001, decay: 0.4, sustain: 0, release: 0.1 },
    });
    this.kickSynth.volume.value = -2;

    // Snare: noise burst with tight envelope
    this.snareSynth = new Tone.NoiseSynth({
      noise: { type: 'white' },
      envelope: { attack: 0.001, decay: 0.15, sustain: 0, release: 0.05 },
    });
    this.snareSynth.volume.value = -8;

    // Hi-hat: metallic short burst
    this.hatSynth = new Tone.MetalSynth({
      envelope: { attack: 0.001, decay: 0.05, release: 0.01 },
      harmonicity: 5.1,
      modulationIndex: 32,
      resonance: 4000,
      octaves: 1.5,
    });
    this.hatSynth.frequency.value = 400;
    this.hatSynth.volume.value = -14;

    // Bass: warm sine-triangle with filter
    this.bassSynth = new Tone.MonoSynth({
      oscillator: { type: 'fatsawtooth', count: 2, spread: 20 },
      envelope: { attack: 0.02, decay: 0.15, sustain: 0.7, release: 0.4 },
      filterEnvelope: {
        attack: 0.02, decay: 0.3, sustain: 0.4, release: 0.4,
        baseFrequency: 200, octaves: 2.5,
      },
    });
    this.bassSynth.volume.value = -4;

    // Keys: warm pad with reverb
    this.reverb = new Tone.Reverb({ decay: 1.5, wet: 0.3 }).toDestination();
    this.keysSynth = new Tone.PolySynth(Tone.Synth, {
      oscillator: { type: 'triangle' },
      envelope: { attack: 0.08, decay: 0.3, sustain: 0.5, release: 1.2 },
    });
    this.keysSynth.volume.value = -10;

    // Routing
    this.kickSynth.toDestination();
    this.snareSynth.toDestination();
    this.hatSynth.toDestination();
    this.bassSynth.toDestination();
    this.keysSynth.connect(this.reverb);
  }

  async init(): Promise<void> {
    await Tone.start();
    await this.reverb.ready;
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
          // hat
          this.hatSynth.triggerAttackRelease(event.duration, toneTime, event.velocity);
        }
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
    this.kickSynth.dispose();
    this.snareSynth.dispose();
    this.hatSynth.dispose();
    this.bassSynth.dispose();
    this.keysSynth.dispose();
    this.reverb.dispose();
    this.isReady = false;
  }
}
