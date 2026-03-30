import * as Tone from 'tone';
import type { NoteEvent } from './WebSocketClient';

// ── Native drum loader (bypasses Tone.js Sampler pipeline) ───────────────────
// Tone.Sampler's internal fetch+decodeAudioData chain fails silently on some
// servers/Content-Types. Using native Web Audio API gives full error visibility
// and reliable decoding after AudioContext is unlocked.

interface DrumBuffers {
  kick: AudioBuffer | null;
  snare: AudioBuffer | null;
  hat: AudioBuffer | null;
}

const DRUM_GAIN: Record<keyof DrumBuffers, number> = {
  kick: 1.2,
  snare: 1.0,
  hat: 0.5,
};

async function loadDrumBuffers(ctx: AudioContext): Promise<DrumBuffers> {
  const files: Record<keyof DrumBuffers, string> = {
    kick:  '/drums/Kick.mp3',
    snare: '/drums/Snare.mp3',
    hat:   '/drums/Hihat.mp3',
  };
  const result: DrumBuffers = { kick: null, snare: null, hat: null };
  await Promise.all(
    (Object.entries(files) as [keyof DrumBuffers, string][]).map(async ([name, url]) => {
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const arr = await resp.arrayBuffer();
        result[name] = await ctx.decodeAudioData(arr);
        console.log(`[BandPlayer] Loaded drum: ${name}`);
      } catch (e) {
        console.warn(`[BandPlayer] Failed to load drum sample "${name}":`, e);
      }
    }),
  );
  return result;
}

function playDrumBuffer(
  ctx: AudioContext,
  buffer: AudioBuffer,
  absoluteTime: number,
  velocity: number,
  gainDb: number,
): void {
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  const gain = ctx.createGain();
  gain.gain.value = velocity * Math.pow(10, gainDb / 20);
  src.connect(gain);
  gain.connect(ctx.destination);
  src.start(Math.max(ctx.currentTime, absoluteTime));
}

// ── BandPlayer ────────────────────────────────────────────────────────────────

export class BandPlayer {
  private drums: DrumBuffers = { kick: null, snare: null, hat: null };
  private nativeCtx: AudioContext | null = null;

  private bassSynth: Tone.MonoSynth | null = null;
  private keysSynth: Tone.PolySynth<Tone.Synth> | null = null;
  private keysReverb: Tone.Reverb | null = null;

  private isReady = false;

  constructor() {}

  async init(): Promise<void> {
    // Unlock AudioContext via user gesture before creating any audio nodes
    await Tone.start();

    // Grab the underlying AudioContext Tone.js uses — shared with our drum player
    this.nativeCtx = Tone.getContext().rawContext as AudioContext;

    // Load drum samples via native Web Audio (no Tone.js Sampler involved)
    this.drums = await loadDrumBuffers(this.nativeCtx);

    // Bass synth — sawtooth with filter envelope for plucky character
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

    // Keys synth — triangle with reverb for soft piano-like tone
    this.keysReverb = new Tone.Reverb({ decay: 1.5, wet: 0.3 }).toDestination();
    this.keysSynth = new Tone.PolySynth(Tone.Synth, {
      oscillator: { type: 'triangle' },
      envelope: { attack: 0.04, decay: 0.3, sustain: 0.4, release: 1.2 },
    });
    this.keysSynth.volume.value = -8;
    this.keysSynth.connect(this.keysReverb);

    this.isReady = true;
    const loaded = Object.values(this.drums).filter(Boolean).length;
    console.log(`[BandPlayer] Ready — ${loaded}/3 drum samples loaded`);
  }

  scheduleNote(event: NoteEvent, absoluteTime: number): void {
    if (!this.isReady) return;

    try {
      if (event.instrument === 'drums') {
        const ctx = this.nativeCtx!;
        const key = event.note === 'kick' ? 'kick'
                  : event.note === 'snare' ? 'snare' : 'hat';
        const buf = this.drums[key];
        if (buf) {
          playDrumBuffer(ctx, buf, absoluteTime, event.velocity, DRUM_GAIN[key]);
        }
        return;
      }

      const delay = Math.max(0, absoluteTime - Tone.now());
      const toneTime = `+${delay}`;
      if (event.instrument === 'bass') {
        this.bassSynth?.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
      } else if (event.instrument === 'keys') {
        this.keysSynth?.triggerAttackRelease(event.note, event.duration, toneTime, event.velocity);
      }
    } catch (err) {
      console.warn('[BandPlayer] scheduleNote error:', err);
    }
  }

  dispose(): void {
    this.bassSynth?.dispose();
    this.keysSynth?.dispose();
    this.keysReverb?.dispose();
    this.drums = { kick: null, snare: null, hat: null };
    this.nativeCtx = null;
    this.isReady = false;
  }
}
