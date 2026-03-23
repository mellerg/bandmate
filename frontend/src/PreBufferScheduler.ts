import type { NoteEvent } from './WebSocketClient';

export class PreBufferScheduler {
  private queue: NoteEvent[] = [];
  private bufferAheadSeconds = 4;

  // audioContext.currentTime when playback started
  private startTime: number = 0;
  private isRunning = false;

  public onSchedule: ((event: NoteEvent, absoluteTime: number) => void) | null = null;

  start(audioContextCurrentTime: number): void {
    this.startTime = audioContextCurrentTime;
    this.isRunning = true;
  }

  stop(): void {
    this.isRunning = false;
    this.queue = [];
  }

  // Called when server sends a batch of note events
  // serverBatchOffset: seconds from "now" when this chunk starts playing
  enqueue(notes: NoteEvent[], serverBatchOffset: number): void {
    const absoluteBase = this.startTime + serverBatchOffset;
    for (const note of notes) {
      const absoluteTime = absoluteBase + note.time;
      this.queue.push({ ...note, time: absoluteTime });
    }
    this.queue.sort((a, b) => a.time - b.time);
  }

  // Drain events that are due within the next bufferAheadSeconds
  drainDue(audioContextCurrentTime: number): NoteEvent[] {
    const horizon = audioContextCurrentTime + this.bufferAheadSeconds;
    const due: NoteEvent[] = [];
    while (this.queue.length > 0 && this.queue[0].time <= horizon) {
      due.push(this.queue.shift()!);
    }
    return due;
  }

  get queueLength(): number {
    return this.queue.length;
  }
}
