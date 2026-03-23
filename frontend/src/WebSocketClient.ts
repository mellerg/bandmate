export interface AnalysisResult {
  pitch: number;
  key: string;
  bpm: number;
  energy: number;
  pitch_confidence: number; // 0–1, aubio per-frame average
  bpm_stability: number;    // std dev in BPM — lower is better
}

export interface NoteEvent {
  type: 'note';
  instrument: 'drums' | 'bass' | 'keys';
  note: string;
  duration: string;
  time: number; // offset in seconds from now
  velocity: number;
}

/** KPI metrics emitted by the server with each notes batch */
export interface KpiMetrics {
  musicality_score: number;     // 0–100 — % of pitched notes in-scale
  buffer_join_ms?: number;      // ms from first audio → first notes (first batch only)
  dynamic_response_ms?: number; // ms from last significant change → this batch
}

export interface ServerMessage {
  type: 'analysis' | 'notes' | 'status' | 'kpi';
  analysis?: AnalysisResult;
  notes?: NoteEvent[];
  message?: string;
  metrics?: KpiMetrics;
}

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;

  public onMessage: ((msg: ServerMessage) => void) | null = null;
  public onConnected: (() => void) | null = null;
  public onDisconnected: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = () => {
        this.onConnected?.();
        resolve();
      };

      this.ws.onerror = (err) => reject(err);

      this.ws.onclose = () => {
        this.onDisconnected?.();
      };

      this.ws.onmessage = (event) => {
        try {
          const msg: ServerMessage = JSON.parse(event.data);
          this.onMessage?.(msg);
        } catch {
          console.warn('Failed to parse server message');
        }
      };
    });
  }

  sendAudio(pcmData: Float32Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(pcmData.buffer);
    }
  }

  sendGenre(genre: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'genre', genre }));
    }
  }

  /** Sent after the listen phase — tells the server to start generating. */
  sendStartGeneration(genre: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'start_generation', genre }));
    }
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
  }
}
