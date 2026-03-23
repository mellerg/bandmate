import time
import numpy as np
import librosa
from music_theory import detect_chord, infer_key_from_chord_sequence

SAMPLE_RATE = 22050
HOP_SIZE = 512
WIN_SIZE = 2048
MIN_BPM_SAMPLES = SAMPLE_RATE * 3   # need ≥3 s for reliable beat tracking


class _BpmStabilizer:
    """
    Holds a 'stable BPM' that only re-syncs when a change > THRESHOLD BPM
    is sustained for > SUSTAIN_SECS seconds.

    Rule (per user spec):
      • Small fluctuations (e.g. 100–110 BPM) → locked at the initial average
      • A deliberate tempo shift (>10 BPM) held for >5 s → band re-syncs
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
        """Feed a new BPM reading. Returns the current stable (locked) BPM."""
        now = time.monotonic()
        if abs(new_bpm - self.stable_bpm) <= self.THRESHOLD:
            # Within acceptable variance — reset any pending candidate
            self._candidate = None
            self._candidate_since = None
            return self.stable_bpm

        # Outside threshold: start or continue tracking a candidate
        if self._candidate is None or abs(new_bpm - self._candidate) > self.THRESHOLD:
            self._candidate = new_bpm
            self._candidate_since = now
        elif now - self._candidate_since >= self.SUSTAIN_SECS:
            # Candidate persisted long enough → lock it in
            self.stable_bpm = round(self._candidate, 1)
            self._candidate = None
            self._candidate_since = None

        return self.stable_bpm


class AudioAnalyzer:
    def __init__(self) -> None:
        self.bpm_stabilizer = _BpmStabilizer()
        self.confidence_history: list[float] = []
        self.chord_roots: list[str] = []       # chord sequence from listen phase
        self._current_chord_root: str = 'C'
        self._current_key: str = 'C'
        self._bpm_stability: float = 0.0      # set after finalize_analysis()
        self.frame_count: int = 0
        self._raw_chunks: list[np.ndarray] = []

    # ── Per-chunk streaming analysis ──────────────────────────────────────────

    def process_chunk(self, pcm_bytes: bytes) -> dict:
        """
        Called for every incoming PCM chunk during the listen phase.
        Updates chord detection and pitch confidence in real time.
        BPM detection is deferred to finalize_analysis().
        """
        samples = np.frombuffer(pcm_bytes, dtype=np.float32)
        if len(samples) < HOP_SIZE:
            return self._current_result()

        self._raw_chunks.append(samples.copy())

        # Pitch confidence via YIN (fraction of voiced frames)
        f0 = librosa.yin(
            samples,
            fmin=librosa.note_to_hz('C2'),
            fmax=librosa.note_to_hz('C7'),
            sr=SAMPLE_RATE,
            hop_length=HOP_SIZE,
            frame_length=WIN_SIZE,
        )
        voiced = sum(1 for hz in f0 if 80 < hz < 2000)
        self.confidence_history.append(voiced / max(len(f0), 1))
        self.confidence_history = self.confidence_history[-40:]

        # Chord detection from chroma
        chroma = librosa.feature.chroma_stft(
            y=samples, sr=SAMPLE_RATE, hop_length=HOP_SIZE
        ).mean(axis=1)
        root, _ = detect_chord(chroma)
        self._current_chord_root = root
        self.chord_roots.append(root)

        # Live key estimate from accumulated chord sequence
        self._current_key = infer_key_from_chord_sequence(self.chord_roots)

        self.frame_count += 1
        return self._current_result()

    # ── Full-buffer finalization (called once after listen phase) ─────────────

    def finalize_analysis(self) -> dict:
        """
        Run beat tracking on the full accumulated buffer for accurate BPM.
        Key is derived from the chord progression collected during listening.
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

        # ── BPM: full buffer + stability from 3 segments ──────────────────
        if len(full_audio) >= MIN_BPM_SAMPLES:
            tempo, _ = librosa.beat.beat_track(
                y=full_audio, sr=SAMPLE_RATE, hop_length=HOP_SIZE
            )
            bpm = float(np.atleast_1d(tempo)[0])
            if 40 < bpm < 240:
                self.bpm_stabilizer.set_initial(bpm)

            # Stability: std dev across 3 equal segments
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

        # ── Key: chord-progression based ──────────────────────────────────
        self._current_key = infer_key_from_chord_sequence(self.chord_roots)

        stable_bpm = self.bpm_stabilizer.stable_bpm
        print(
            f"[Analyzer] key={self._current_key}, bpm={stable_bpm:.1f}, "
            f"stability=±{self._bpm_stability:.1f}, "
            f"buffer={duration_s:.1f}s, chords={self.chord_roots[-6:]}"
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
        self.chord_roots.clear()
        self._current_chord_root = 'C'
        self._current_key = 'C'
        self._bpm_stability = 0.0
        self.frame_count = 0
        self._raw_chunks.clear()
