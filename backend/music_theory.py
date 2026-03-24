"""
Tonal Inference Engine for BandMate.

Implements the weighted scoring algorithm described in the music theory spec:

Scoring per voiced frame
------------------------
  • Note is in the candidate key's major scale  → +10 pts
  • Note is degree I, IV, or V (Tonic/Subdominant/Dominant) → +20 pts extra
  • Note is NOT in the candidate key's scale     → -15 pts
  • Note is a pedal point (sustained >2 s)       → score × 2
  • Note is a loop anchor (first note after silence) → score × 1.5

Key is committed when the leading candidate holds ≥ CONFIDENCE_THRESHOLD
of the total positive scoring mass (default 80 %).

Chord degree qualities (diatonic major scale)
---------------------------------------------
  I   → Major         (Tonic)
  ii  → minor         (Supertonic)
  iii → minor         (Mediant)
  IV  → Major         (Subdominant)
  V   → Major         (Dominant)
  vi  → minor         (Relative minor)
  vii → diminished    (Leading tone)

For blues, all chords are dominant 7ths regardless of degree.
"""

import numpy as np
from collections import defaultdict

# ── Constants ─────────────────────────────────────────────────────────────────

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Semitone offsets of the major scale from the root
MAJOR_SCALE_SEMITONES = {0, 2, 4, 5, 7, 9, 11}

# Strong degrees (Tonic=0, Subdominant=5, Dominant=7) get extra weight
STRONG_DEGREES = {0, 5, 7}

# Diatonic chord qualities per Roman numeral degree (major key)
DIATONIC_QUALITIES: dict[str, str] = {
    'I':   'major',
    'ii':  'minor',
    'iii': 'minor',
    'IV':  'major',
    'V':   'major',
    'vi':  'minor',
    'vii': 'diminished',
}

# Semitone offset of each Roman numeral from the key root
DEGREE_OFFSETS: dict[str, int] = {
    'I': 0, 'ii': 2, 'iii': 4, 'IV': 5, 'V': 7, 'vi': 9, 'vii': 11,
}

# Scoring weights (per document)
_IN_SCALE   =  10
_STRONG_DEG =  20   # bonus on top of IN_SCALE for I, IV, V
_OUT_SCALE  = -15
_PEDAL_MUL  =   2.0  # multiplier for notes held > 2 s
_ANCHOR_MUL =   1.5  # multiplier for first note after silence

# Confidence threshold to commit to a new key
CONFIDENCE_THRESHOLD = 0.80

# Silence detection: frames with unvoiced pitch before "loop anchor" resets
_SILENCE_FRAME_THRESHOLD = 4  # ~4 × (hop/sr) ≈ 0.09 s

# ── Chord detection templates ─────────────────────────────────────────────────

def _make_template(root_idx: int, quality: str) -> np.ndarray:
    t = np.zeros(12)
    t[root_idx % 12] = 1.0
    intervals = {
        'major':      [4, 7],
        'minor':      [3, 7],
        'dom7':       [4, 7, 10],
        'diminished': [3, 6],
    }.get(quality, [4, 7])
    for iv in intervals:
        t[(root_idx + iv) % 12] = 0.85
    return t

CHORD_TEMPLATES: list[tuple[str, str, np.ndarray]] = [
    (name, q, _make_template(idx, q))
    for idx, name in enumerate(NOTES)
    for q in ('major', 'minor', 'dom7', 'diminished')
]


def detect_chord(chroma: np.ndarray) -> tuple[str, str]:
    """
    Match a 12-element chroma vector to the closest chord.
    Returns (root_note, chord_quality) e.g. ('A', 'major').
    """
    if chroma.max() < 1e-6:
        return ('C', 'major')
    norm = chroma / (chroma.max() + 1e-9)
    best = max(CHORD_TEMPLATES, key=lambda t: float(np.dot(norm, t[2])))
    return (best[0], best[1])


# ── Tonal Inference Engine ────────────────────────────────────────────────────

class ScaleInferenceEngine:
    """
    Processes frame-level pitch detections and maintains a weighted score
    for each of the 12 major keys.  Commits to a new key only when
    confidence exceeds CONFIDENCE_THRESHOLD.
    """

    def __init__(self, sample_rate: int = 22050, hop_size: int = 512) -> None:
        self._sr = sample_rate
        self._hop = hop_size
        self._frame_dur = hop_size / sample_rate  # seconds per frame

        # Cumulative score per key
        self._scores: dict[str, float] = {n: 0.0 for n in NOTES}

        # Committed (stable) key — only updated when confidence >= threshold
        self.stable_key: str = 'C'

        # Pedal-point tracking: (pitch_class, consecutive_frame_count)
        self._last_pitch_class: int | None = None
        self._pitch_streak: int = 0

        # Silence / loop-anchor tracking
        self._silence_streak: int = 0
        self._next_is_anchor: bool = True   # first note of session = anchor

    # ── Public interface ──────────────────────────────────────────────────────

    def process_pitches(self, f0_hz: list[float]) -> None:
        """
        Feed a list of per-frame Hz values (from librosa.yin or similar).
        Unvoiced frames should be 0 or negative.
        """
        for hz in f0_hz:
            if 80 < hz < 2000:
                self._on_voiced(hz)
            else:
                self._on_silence()

    def get_key(self, force: bool = False) -> str:
        """
        Return the current best key.
        If force=True, commit unconditionally (used in finalize_analysis).
        """
        if not any(v != 0 for v in self._scores.values()):
            return self.stable_key

        best_key = max(self._scores, key=lambda k: self._scores[k])
        best_score = self._scores[best_key]

        if force:
            if best_score > 0:
                self.stable_key = best_key
            return self.stable_key

        # Confidence = best score / total positive mass
        pos_total = sum(v for v in self._scores.values() if v > 0)
        if pos_total > 0 and best_score / pos_total >= CONFIDENCE_THRESHOLD:
            self.stable_key = best_key

        return self.stable_key

    def reset(self) -> None:
        self._scores = {n: 0.0 for n in NOTES}
        self.stable_key = 'C'
        self._last_pitch_class = None
        self._pitch_streak = 0
        self._silence_streak = 0
        self._next_is_anchor = True

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _on_voiced(self, hz: float) -> None:
        midi = round(69 + 12 * np.log2(hz / 440.0))
        pitch_class = int(midi) % 12

        # Pedal-point tracking
        if pitch_class == self._last_pitch_class:
            self._pitch_streak += 1
        else:
            self._last_pitch_class = pitch_class
            self._pitch_streak = 1

        duration_s = self._pitch_streak * self._frame_dur
        is_pedal = duration_s > 2.0

        # Loop anchor
        is_anchor = self._next_is_anchor
        self._next_is_anchor = False
        self._silence_streak = 0

        # Score against all 12 keys
        for key_idx, key_name in enumerate(NOTES):
            semitone_dist = (pitch_class - key_idx) % 12
            if semitone_dist in MAJOR_SCALE_SEMITONES:
                score = float(_IN_SCALE)
                if semitone_dist in STRONG_DEGREES:
                    score += _STRONG_DEG
            else:
                score = float(_OUT_SCALE)

            if is_pedal:
                score *= _PEDAL_MUL
            if is_anchor:
                score *= _ANCHOR_MUL

            self._scores[key_name] += score

    def _on_silence(self) -> None:
        self._silence_streak += 1
        if self._silence_streak >= _SILENCE_FRAME_THRESHOLD:
            self._next_is_anchor = True   # next voiced note = loop anchor
            self._pitch_streak = 0
