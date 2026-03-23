import numpy as np
import librosa

SAMPLE_RATE = 22050
HOP_SIZE = 512
WIN_SIZE = 2048

PITCH_CLASSES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])

# Minimum samples needed for reliable BPM detection (~3 seconds)
MIN_BPM_SAMPLES = SAMPLE_RATE * 3


def hz_to_note(hz: float) -> tuple[str, int]:
    if hz <= 0:
        return ('', 0)
    midi = 69 + 12 * np.log2(hz / 440.0)
    note_idx = int(round(midi)) % 12
    octave = int(round(midi)) // 12 - 1
    return (PITCH_CLASSES[note_idx], octave)


class AudioAnalyzer:
    def __init__(self):
        self.pitch_history: list[float] = []
        self.bpm_history: list[float] = []
        self.confidence_history: list[float] = []
        self.chroma_accum = np.zeros(12)
        self.frame_count = 0
        # Raw audio accumulation for full-buffer BPM/key analysis
        self._raw_chunks: list[np.ndarray] = []

    def process_chunk(self, pcm_bytes: bytes) -> dict:
        """Process a raw Float32 PCM chunk. BPM is deferred to finalize_analysis()."""
        samples = np.frombuffer(pcm_bytes, dtype=np.float32)

        if len(samples) < HOP_SIZE:
            return self._current_result()

        # Accumulate raw audio for final BPM/key detection
        self._raw_chunks.append(samples.copy())

        # ── Pitch detection via librosa YIN ───────────────────────────────────
        f0 = librosa.yin(
            samples,
            fmin=librosa.note_to_hz('C2'),
            fmax=librosa.note_to_hz('C7'),
            sr=SAMPLE_RATE,
            hop_length=HOP_SIZE,
            frame_length=WIN_SIZE,
        )

        pitches = []
        confidences = []
        for hz in f0:
            if 80 < hz < 2000:
                pitches.append(float(hz))
                confidences.append(1.0)
                note, _ = hz_to_note(float(hz))
                chroma_idx = PITCH_CLASSES.index(note)
                self.chroma_accum[chroma_idx] += 1
            else:
                confidences.append(0.0)

        self.confidence_history.extend(confidences)
        self.confidence_history = self.confidence_history[-40:]

        if pitches:
            self.pitch_history.extend(pitches)
        self.pitch_history = self.pitch_history[-20:]

        self.frame_count += 1
        return self._current_result()

    def finalize_analysis(self) -> dict:
        """
        Run full-buffer BPM and chroma analysis on all accumulated audio.
        Call this once after the listen phase ends, before starting generation.
        Returns {'bpm': float, 'key': str}.
        """
        if not self._raw_chunks:
            return {'bpm': 100.0, 'key': self._detect_key()}

        full_audio = np.concatenate(self._raw_chunks)

        # BPM on full buffer (needs ≥3s for reliable results)
        if len(full_audio) >= MIN_BPM_SAMPLES:
            tempo, _ = librosa.beat.beat_track(
                y=full_audio,
                sr=SAMPLE_RATE,
                hop_length=HOP_SIZE,
            )
            bpm = float(np.atleast_1d(tempo)[0])
            if 40 < bpm < 240:
                self.bpm_history.append(bpm)

        # Chroma on full buffer — more accurate than per-chunk accumulation
        chroma = librosa.feature.chroma_stft(
            y=full_audio,
            sr=SAMPLE_RATE,
            hop_length=HOP_SIZE,
        )
        self.chroma_accum = chroma.mean(axis=1)

        avg_bpm = float(np.median(self.bpm_history)) if self.bpm_history else 100.0
        key = self._detect_key()

        print(f"[Analyzer] Finalized: key={key}, bpm={avg_bpm:.1f} "
              f"(buffer={len(full_audio)/SAMPLE_RATE:.1f}s)")
        return {'bpm': avg_bpm, 'key': key}

    def _current_result(self) -> dict:
        avg_pitch = float(np.median(self.pitch_history)) if self.pitch_history else 0.0
        avg_bpm = float(np.median(self.bpm_history)) if self.bpm_history else 100.0
        bpm_stability = float(np.std(self.bpm_history)) if len(self.bpm_history) > 1 else 0.0
        avg_confidence = float(np.mean(self.confidence_history)) if self.confidence_history else 0.0
        samples_so_far = sum(len(c) for c in self._raw_chunks)
        energy = 0.0
        if self._raw_chunks:
            last = self._raw_chunks[-1]
            energy = float(np.sqrt(np.mean(last ** 2)))
        return {
            'pitch': round(avg_pitch, 2),
            'key': self._detect_key(),
            'bpm': round(avg_bpm, 1),
            'energy': round(energy, 4),
            'pitch_confidence': round(avg_confidence, 3),
            'bpm_stability': round(bpm_stability, 2),
        }

    def _detect_key(self) -> str:
        if self.chroma_accum.sum() == 0:
            return 'C'
        chroma = self.chroma_accum / self.chroma_accum.sum()
        best_score = -np.inf
        best_key = 'C'
        for i, name in enumerate(PITCH_CLASSES):
            rotated = np.roll(MAJOR_PROFILE, -i)
            rotated = rotated / rotated.sum()
            score = float(np.dot(chroma, rotated))
            if score > best_score:
                best_score = score
                best_key = name
        return best_key

    def reset(self):
        self.pitch_history.clear()
        self.bpm_history.clear()
        self.confidence_history.clear()
        self.chroma_accum = np.zeros(12)
        self.frame_count = 0
        self._raw_chunks.clear()
