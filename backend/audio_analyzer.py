import time
import numpy as np
import librosa
from music_theory import detect_chord, ScaleInferenceEngine

SAMPLE_RATE = 22050
HOP_SIZE = 512
WIN_SIZE = 2048
MIN_BPM_SAMPLES = SAMPLE_RATE * 3   # need ≥3 s for reliable beat tracking

# Minimum RMS to consider a chunk as "the user is playing"
_PLAYING_RMS_THRESHOLD = 0.005


class _BpmStabilizer:
    """
    Holds a 'stable BPM' that only re-syncs when a change > THRESHOLD BPM
    is sustained for > SUSTAIN_SECS seconds.
    """
    THRESHOLD = 10.0
    SUSTAIN_SECS = 5.0

    def __init__(self) -> None:
        self.stable_bpm: float = 100.0
        self._candidate: float | None = None
        self._candidate_since: float | None = None

    def set_initial(self, bpm: float) -> None:
        self.stable_bpm = round(bpm, 1)
        self._candidate = None
        self._candidate_since = None

    def observe(self, new_bpm: float) -> float:
        now = time.monotonic()
        if abs(new_bpm - self.stable_bpm) <= self.THRESHOLD:
            self._candidate = None
            self._candidate_since = None
            return self.stable_bpm
        if self._candidate is None or abs(new_bpm - self._candidate) > self.THRESHOLD:
            self._candidate = new_bpm
            self._candidate_since = now
        elif now - self._candidate_since >= self.SUSTAIN_SECS:
            self.stable_bpm = round(self._candidate, 1)
            self._candidate = None
            self._candidate_since = None
        return self.stable_bpm


class AudioAnalyzer:
    def __init__(self) -> None:
        self.bpm_stabilizer = _BpmStabilizer()
        self.confidence_history: list[float] = []
        self.scale_engine = ScaleInferenceEngine(sample_rate=SAMPLE_RATE, hop_size=HOP_SIZE)
        self._current_chord_root: str = 'C'
        self._current_key: str = 'C'
        self._bpm_stability: float = 0.0
        self.frame_count: int = 0
        self._raw_chunks: list[np.ndarray] = []

    # ── Per-chunk streaming (lightweight — no librosa) ────────────────────────

    def process_chunk(self, pcm_bytes: bytes) -> dict:
        """
        Accumulate raw PCM. No librosa calls here — keeps the async event loop
        free on low-CPU servers (Render free tier).

        Confidence is estimated from chunk RMS so the UI still shows signal.
        Key and chord are updated only after finalize_analysis().
        """
        samples = np.frombuffer(pcm_bytes, dtype=np.float32)
        if len(samples) < HOP_SIZE:
            return self._current_result()

        self._raw_chunks.append(samples.copy())

        # Lightweight energy-based confidence (no pitch detection yet)
        rms = float(np.sqrt(np.mean(samples ** 2)))
        self.confidence_history.append(min(1.0, rms / 0.1))
        self.confidence_history = self.confidence_history[-40:]

        self.frame_count += 1
        return self._current_result()

    # ── Full-buffer finalization (runs in thread executor) ────────────────────

    def finalize_analysis(self) -> dict:
        """
        Called once after the listen phase, in a thread executor.
        Runs all heavy librosa work on the full accumulated buffer.
        Returns {'bpm', 'key', 'chord_root'} to seed the Conductor.
        """
        if not self._raw_chunks:
            return {
                'bpm': self.bpm_stabilizer.stable_bpm,
                'key': self._current_key,
                'chord_root': self._current_chord_root,
            }

        full_audio = np.concatenate(self._raw_chunks)
        duration_s = len(full_audio) / SAMPLE_RATE

        # ── Key: pitch YIN over full buffer, energy-gated ─────────────────
        f0 = librosa.yin(
            full_audio,
            fmin=librosa.note_to_hz('C2'),
            fmax=librosa.note_to_hz('C7'),
            sr=SAMPLE_RATE,
            hop_length=HOP_SIZE,
            frame_length=WIN_SIZE,
        )
        gated: list[float] = []
        for i, hz in enumerate(f0):
            start = i * HOP_SIZE
            frame = full_audio[start:start + WIN_SIZE]
            rms = float(np.sqrt(np.mean(frame ** 2))) if len(frame) > 0 else 0.0
            gated.append(float(hz) if rms > _PLAYING_RMS_THRESHOLD and 80 < hz < 2000 else 0.0)

        self.scale_engine.process_pitches(gated)
        self._current_key = self.scale_engine.get_key(force=True)

        # Update confidence from voiced fraction of full buffer
        voiced = sum(1 for v in gated if v > 0)
        full_conf = voiced / max(len(gated), 1)
        self.confidence_history = [full_conf]

        # ── Chord: chroma over full buffer ────────────────────────────────
        chroma = librosa.feature.chroma_stft(
            y=full_audio, sr=SAMPLE_RATE, hop_length=HOP_SIZE
        ).mean(axis=1)
        root, _ = detect_chord(chroma)
        self._current_chord_root = root

        # ── BPM: beat_track on full buffer ────────────────────────────────
        if len(full_audio) >= MIN_BPM_SAMPLES:
            tempo, _ = librosa.beat.beat_track(
                y=full_audio, sr=SAMPLE_RATE, hop_length=HOP_SIZE
            )
            bpm = float(np.atleast_1d(tempo)[0])
            if 40 < bpm < 240:
                self.bpm_stabilizer.set_initial(bpm)

            seg = len(full_audio) // 3
            bpm_segs: list[float] = []
            for i in range(3):
                chunk = full_audio[i * seg:(i + 1) * seg]
                if len(chunk) >= MIN_BPM_SAMPLES // 2:
                    t2, _ = librosa.beat.beat_track(
                        y=chunk, sr=SAMPLE_RATE, hop_length=HOP_SIZE
                    )
                    v = float(np.atleast_1d(t2)[0])
                    if 40 < v < 240:
                        bpm_segs.append(v)
            self._bpm_stability = float(np.std(bpm_segs)) if len(bpm_segs) > 1 else 0.0

        stable_bpm = self.bpm_stabilizer.stable_bpm
        print(
            f"[Analyzer] key={self._current_key}, bpm={stable_bpm:.1f}, "
            f"stability=±{self._bpm_stability:.1f}, buffer={duration_s:.1f}s, "
            f"chord={self._current_chord_root}, voiced={voiced}/{len(gated)}"
        )
        return {
            'bpm': stable_bpm,
            'key': self._current_key,
            'chord_root': self._current_chord_root,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _current_result(self) -> dict:
        avg_conf = float(np.mean(self.confidence_history)) if self.confidence_history else 0.0
        energy = float(np.sqrt(np.mean(self._raw_chunks[-1] ** 2))) if self._raw_chunks else 0.0
        return {
            'pitch': 0.0,
            'key': self._current_key,
            'bpm': round(self.bpm_stabilizer.stable_bpm, 1),
            'energy': round(energy, 4),
            'pitch_confidence': round(avg_conf, 3),
            'bpm_stability': round(self._bpm_stability, 2),
            'chord_root': self._current_chord_root,
        }

    def reset(self) -> None:
        self.bpm_stabilizer = _BpmStabilizer()
        self.confidence_history.clear()
        self.scale_engine.reset()
        self._current_chord_root = 'C'
        self._current_key = 'C'
        self._bpm_stability = 0.0
        self.frame_count = 0
        self._raw_chunks.clear()
