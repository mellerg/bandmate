import * as Tone from 'tone';
import { AudioCapture } from './AudioCapture';
import { WebSocketClient } from './WebSocketClient';
import { PreBufferScheduler } from './PreBufferScheduler';
import { BandPlayer } from './BandPlayer';
import type { ServerMessage, NoteEvent, KpiMetrics } from './WebSocketClient';

// ── Config ───────────────────────────────────────────────────────────────────
const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = import.meta.env.VITE_WS_URL ?? `${wsProtocol}//${location.host}/ws`;
const LISTEN_DURATION_MS = 4000;
const DRAIN_INTERVAL_MS = 100;

// ── DOM ───────────────────────────────────────────────────────────────────────
const startBtn = document.getElementById('startBtn') as HTMLButtonElement;
const stopBtn = document.getElementById('stopBtn') as HTMLButtonElement;
const phaseEl = document.getElementById('phaseIndicator') as HTMLDivElement;
const chordEl = document.getElementById('chordDisplay') as HTMLDivElement;
const keyEl = document.getElementById('keyDisplay') as HTMLDivElement;
const bpmEl = document.getElementById('bpmDisplay') as HTMLDivElement;
const genreEl = document.getElementById('genreDisplay') as HTMLDivElement;
const bandPanelEl = document.getElementById('bandPanel') as HTMLDivElement;
const canvas = document.getElementById('waveform') as HTMLCanvasElement;
const logEl = document.getElementById('log') as HTMLDivElement;
const genreBtns = document.querySelectorAll<HTMLButtonElement>('.genre-btn');

// KPI DOM refs
const kpiBufJoin     = document.getElementById('kpiBufJoin')!;
const kpiBufJoinBar  = document.getElementById('kpiBufJoinBar')!;
const kpiDynResp     = document.getElementById('kpiDynResp')!;
const kpiDynRespBar  = document.getElementById('kpiDynRespBar')!;
const kpiPitchConf   = document.getElementById('kpiPitchConf')!;
const kpiPitchConfBar= document.getElementById('kpiPitchConfBar')!;
const kpiBpmStab     = document.getElementById('kpiBpmStab')!;
const kpiBpmStabBar  = document.getElementById('kpiBpmStabBar')!;
const kpiMusic       = document.getElementById('kpiMusic')!;
const kpiMusicBar    = document.getElementById('kpiMusicBar')!;

const ctx = canvas.getContext('2d')!;

// ── State ─────────────────────────────────────────────────────────────────────
let selectedGenre = 'blues';
let phase: 'idle' | 'listening' | 'pregenerating' | 'jamming' = 'idle';
let drainTimer: ReturnType<typeof setInterval> | null = null;
let batchOffset = 0; // seconds: where the next server batch starts

// Client-side KPI timing
let firstAudioSentAt = 0; // performance.now() when first PCM chunk was sent

const capture = new AudioCapture();
const wsClient = new WebSocketClient(WS_URL);
const scheduler = new PreBufferScheduler();
let player: BandPlayer | null = null;

// ── KPI helpers ───────────────────────────────────────────────────────────────
type KpiColor = 'green' | 'orange' | 'red';

function setKpiCard(
  valueEl: HTMLElement,
  barEl: HTMLElement,
  cardEl: HTMLElement | null,
  text: string,
  fillPct: number,   // 0–100
  color: KpiColor,
) {
  valueEl.textContent = text;
  valueEl.className = `kpi-card-value ${color}`;
  barEl.style.width = `${Math.min(100, Math.max(0, fillPct))}%`;
  barEl.className = `kpi-bar-fill ${color}`;
  if (cardEl) {
    cardEl.classList.toggle('pass', color === 'green');
    cardEl.classList.toggle('fail', color === 'red');
  }
}

function resetKpiCards() {
  for (const [val, bar] of [
    [kpiBufJoin, kpiBufJoinBar],
    [kpiDynResp, kpiDynRespBar],
    [kpiPitchConf, kpiPitchConfBar],
    [kpiBpmStab, kpiBpmStabBar],
    [kpiMusic, kpiMusicBar],
  ] as [HTMLElement, HTMLElement][]) {
    val.textContent = '—';
    val.className = 'kpi-card-value';
    bar.style.width = '0%';
    bar.className = 'kpi-bar-fill';
  }
  for (const id of ['kpi-bufJoin','kpi-dynResp','kpi-pitchConf','kpi-bpmStab','kpi-music']) {
    document.getElementById(id)?.classList.remove('pass', 'fail');
  }
}

function updateKpiFromAnalysis(pitchConf: number, bpmStab: number) {
  // Pitch confidence: pass >85%, warn >70%, fail <70%
  const confPct = pitchConf * 100;
  const confColor: KpiColor = confPct >= 85 ? 'green' : confPct >= 70 ? 'orange' : 'red';
  setKpiCard(kpiPitchConf, kpiPitchConfBar, document.getElementById('kpi-pitchConf'),
    `${confPct.toFixed(0)}%`, confPct, confColor);

  // BPM stability: pass <5, warn <15, fail >=15 (inverted bar: 0 std = full)
  const stabFill = Math.max(0, 100 - bpmStab * 5);
  const stabColor: KpiColor = bpmStab < 5 ? 'green' : bpmStab < 15 ? 'orange' : 'red';
  setKpiCard(kpiBpmStab, kpiBpmStabBar, document.getElementById('kpi-bpmStab'),
    `±${bpmStab.toFixed(1)}`, stabFill, stabColor);
}

function updateKpiFromServer(metrics: KpiMetrics) {
  // Musicality: pass >80%, warn >60%
  const mPct = metrics.musicality_score;
  const mColor: KpiColor = mPct >= 80 ? 'green' : mPct >= 60 ? 'orange' : 'red';
  setKpiCard(kpiMusic, kpiMusicBar, document.getElementById('kpi-music'),
    `${mPct.toFixed(0)}%`, mPct, mColor);

  // Buffer join (emitted once on first batch)
  if (metrics.buffer_join_ms !== undefined) {
    const joinMs = metrics.buffer_join_ms;
    const joinColor: KpiColor = joinMs <= 5000 ? 'green' : joinMs <= 8000 ? 'orange' : 'red';
    const joinFill = Math.max(0, 100 - joinMs / 120);
    setKpiCard(kpiBufJoin, kpiBufJoinBar, document.getElementById('kpi-bufJoin'),
      `${(joinMs / 1000).toFixed(1)}s`, joinFill, joinColor);
  }

  // Dynamic response (emitted when a change was detected)
  if (metrics.dynamic_response_ms !== undefined) {
    const dynMs = metrics.dynamic_response_ms;
    const dynColor: KpiColor = dynMs <= 6000 ? 'green' : dynMs <= 10000 ? 'orange' : 'red';
    const dynFill = Math.max(0, 100 - dynMs / 100);
    setKpiCard(kpiDynResp, kpiDynRespBar, document.getElementById('kpi-dynResp'),
      `${(dynMs / 1000).toFixed(1)}s`, dynFill, dynColor);
  }
}

// ── Logging ───────────────────────────────────────────────────────────────────
function log(msg: string, level: 'info' | 'success' | 'warn' = 'info') {
  const el = document.createElement('div');
  el.className = `log-entry ${level}`;
  el.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  logEl.appendChild(el);
  logEl.scrollTop = logEl.scrollHeight;
}

// ── Phase transitions ─────────────────────────────────────────────────────────
function setPhase(p: typeof phase) {
  phase = p;
  phaseEl.className = 'phase-indicator ' + (p === 'idle' ? '' : p);
  const labels: Record<typeof phase, string> = {
    idle: 'Ready',
    listening: '🎵 Listening to you...',
    pregenerating: '⚡ Band is tuning in...',
    jamming: '🎸 Jamming!',
  };
  phaseEl.textContent = labels[p];
}

// ── Waveform visualizer ───────────────────────────────────────────────────────
function drawWaveform(data: Uint8Array) {
  const W = canvas.width;
  const H = canvas.height;
  ctx.fillStyle = '#14141e';
  ctx.fillRect(0, 0, W, H);

  ctx.lineWidth = 2;
  ctx.strokeStyle = phase === 'jamming' ? '#10b981' : phase === 'listening' ? '#f59e0b' : '#7c6fcd';
  ctx.beginPath();

  const sliceWidth = W / data.length;
  let x = 0;
  for (let i = 0; i < data.length; i++) {
    const v = data[i] / 128.0;
    const y = (v * H) / 2;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    x += sliceWidth;
  }
  ctx.lineTo(W, H / 2);
  ctx.stroke();
}

// ── Server message handler ─────────────────────────────────────────────────────
function handleServerMessage(msg: ServerMessage) {
  if (msg.type === 'analysis' && msg.analysis) {
    const { key, bpm, pitch_confidence, bpm_stability, chord_root } = msg.analysis;
    chordEl.textContent = chord_root || '—';
    keyEl.textContent = key || '—';
    bpmEl.textContent = bpm > 0 ? Math.round(bpm).toString() : '—';
    genreEl.textContent = selectedGenre.charAt(0).toUpperCase() + selectedGenre.slice(1);

    // Update live pitch + BPM KPI cards
    updateKpiFromAnalysis(pitch_confidence, bpm_stability);
  }

  if (msg.type === 'notes' && msg.notes && msg.notes.length > 0) {
    const chunkDuration = msg.actual_duration ?? 4;
    if (phase === 'pregenerating') {
      setPhase('jamming');
      scheduler.start(Tone.now());
      batchOffset = 0;
      bandPanelEl.style.display = 'flex';
      log('Band joined! Jamming started.', 'success');
      startDrainLoop();
    }
    scheduler.enqueue(msg.notes, batchOffset);
    batchOffset += chunkDuration;
    log(`Queued ${msg.notes.length} events. Buffer: ${scheduler.queueLength} events`, 'info');
  }

  if (msg.type === 'kpi' && msg.metrics) {
    updateKpiFromServer(msg.metrics);
  }

  if (msg.type === 'status') {
    log(msg.message ?? '', 'info');
  }
}

// ── Drain loop — schedules due notes into Tone.js ────────────────────────────
function startDrainLoop() {
  drainTimer = setInterval(() => {
    const due = scheduler.drainDue(Tone.now());
    for (const event of due) {
      player?.scheduleNote(event as NoteEvent, event.time);
    }
  }, DRAIN_INTERVAL_MS);
}

function stopDrainLoop() {
  if (drainTimer) {
    clearInterval(drainTimer);
    drainTimer = null;
  }
}

// ── Start ─────────────────────────────────────────────────────────────────────
async function startSession() {
  startBtn.disabled = true;
  stopBtn.disabled = false;

  // BandPlayer.init() calls Tone.start() then constructs all audio nodes.
  // Creating nodes before Tone.start() causes EncodingErrors in Chrome.
  player = new BandPlayer();
  await player.init();

  wsClient.onMessage = handleServerMessage;
  wsClient.onConnected = () => log('Connected to Bandmate server', 'success');
  wsClient.onDisconnected = () => log('Disconnected from server', 'warn');

  try {
    await wsClient.connect();
  } catch {
    log('Cannot connect to server. Is the backend running?', 'warn');
    startBtn.disabled = false;
    stopBtn.disabled = true;
    return;
  }

  // Tell backend the starting genre (does NOT start the scheduler yet)
  wsClient.sendGenre(selectedGenre);

  // Phase 1: Listen
  setPhase('listening');
  log('Listening phase started (4 seconds)...', 'info');

  capture.onWaveformData = drawWaveform;
  capture.onAudioChunk = (pcm) => {
    if (firstAudioSentAt === 0) firstAudioSentAt = performance.now();
    wsClient.sendAudio(pcm);
  };

  await capture.start();

  // After listen window, request conductor to start generating
  setTimeout(() => {
    if (phase === 'listening') {
      setPhase('pregenerating');
      log('Asking band to tune in...', 'info');
      wsClient.sendStartGeneration(selectedGenre);
    }
  }, LISTEN_DURATION_MS);
}

// ── Stop ──────────────────────────────────────────────────────────────────────
function stopSession() {
  capture.stop();
  wsClient.disconnect();
  scheduler.stop();
  stopDrainLoop();
  player?.dispose();
  player = null;
  setPhase('idle');
  chordEl.textContent = '—';
  keyEl.textContent = '—';
  bpmEl.textContent = '—';
  genreEl.textContent = '—';
  bandPanelEl.style.display = 'none';
  firstAudioSentAt = 0;
  resetKpiCards();
  startBtn.disabled = false;
  stopBtn.disabled = true;
  log('Session stopped.', 'warn');
}

// ── Genre selector ────────────────────────────────────────────────────────────
genreBtns.forEach((btn) => {
  btn.addEventListener('click', () => {
    selectedGenre = btn.dataset.genre ?? 'blues';
    genreBtns.forEach((b) => b.classList.toggle('active', b === btn));
    wsClient.sendGenre(selectedGenre);
  });
});

// ── Buttons ───────────────────────────────────────────────────────────────────
startBtn.addEventListener('click', startSession);
stopBtn.addEventListener('click', stopSession);
