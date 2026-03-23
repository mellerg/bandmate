import aubio
import numpy as np

SAMPLE_RATE = 22050
HOP_SIZE = 512
WIN_SIZE = 2048

# Pitch class to note name mapping
PITCH_CLASSES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Major scale intervals for key detection
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])

def hz_to_note(hz: float) -> tuple[str, int]:
    """Convert Hz to note name and octave."""
    if hz <= 0:
        return ('', 0)
    midi = 69 + 12 * np.log2(hz / 440.0)
    note_idx = int(round(midi)) % 12
    octave = int(round(midi)) // 12 - 1
    return (PITCH_CLASSES[note_idx], octave)


class AudioAnalyzer:
    def __init__(self):
        self.pitch_detector = aubio.pitch('yinfft', WIN_SIZE, HOP_SIZE, SAMPLE_RATE)
        self.pitch_detector.set_unit('Hz')
        self.pitch_detector.set_silence(-40)
        self.pitch_detector.set_tolerance(0.8)

        self.tempo_detector = aubio.tempo('default', WIN_SIZE, HOP_SIZE, SAMPLE_RATE)

        # Rolling buffers for smoothing
        self.pitch_history: list[float] = []
        self.bpm_history: list[float] = []
        self.confidence_history: list[float] = []
        self.chroma_accum = np.zeros(12)
        self.frame_count = 0

    def process_chunk(self, pcm_bytes: bytes) -> dict:
        """Process a raw Float32 PCM chunk and return analysis."""
        samples = np.frombuffer(pcm_bytes, dtype=np.float32)

        pitches = []
        bpm_beats = []

        # Process in HOP_SIZE windows
        for i in range(0, len(samples) - HOP_SIZE, HOP_SIZE):
            frame = samples[i:i + HOP_SIZE].astype(np.float32)
            if len(frame) < HOP_SIZE:
                break

            # Pitch
            pitch_hz = float(self.pitch_detector(frame)[0])
            confidence = float(self.pitch_detector.get_confidence())
            self.confidence_history.append(confidence)
            if confidence > 0.7 and 80 < pitch_hz < 2000:
                pitches.append(pitch_hz)
                note, octave = hz_to_note(pitch_hz)
                chroma_idx = PITCH_CLASSES.index(note)
                self.chroma_accum[chroma_idx] += 1

            # BPM
            is_beat = self.tempo_detector(frame)
            if is_beat[0] > 0:
                bpm = float(self.tempo_detector.get_bpm())
                if 40 < bpm < 240:
                    bpm_beats.append(bpm)

        # Smooth pitch
        if pitches:
            self.pitch_history.extend(pitches)
        self.pitch_history = self.pitch_history[-20:]
        avg_pitch = float(np.median(self.pitch_history)) if self.pitch_history else 0.0

        # Smooth BPM
        if bpm_beats:
            self.bpm_history.extend(bpm_beats)
        self.bpm_history = self.bpm_history[-10:]
        avg_bpm = float(np.median(self.bpm_history)) if self.bpm_history else 100.0
        bpm_stability = float(np.std(self.bpm_history)) if len(self.bpm_history) > 1 else 0.0

        # Pitch confidence (rolling average over recent frames)
        self.confidence_history = self.confidence_history[-40:]
        avg_confidence = float(np.mean(self.confidence_history)) if self.confidence_history else 0.0

        # Key detection via Krumhansl-Schmuckler
        key = self._detect_key()

        # Energy
        energy = float(np.sqrt(np.mean(samples ** 2))) if len(samples) > 0 else 0.0

        self.frame_count += 1

        return {
            'pitch': round(avg_pitch, 2),
            'key': key,
            'bpm': round(avg_bpm, 1),
            'energy': round(energy, 4),
            'pitch_confidence': round(avg_confidence, 3),
            'bpm_stability': round(bpm_stability, 2),
        }

    def _detect_key(self) -> str:
        """Detect musical key using chroma accumulation."""
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
