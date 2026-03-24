"""
Music theory knowledge base for BandMate.

Key detection strategy
----------------------
1. Per audio chunk: compute chroma → find best-matching major/minor chord.
2. Accumulate a chord-root sequence across the entire listen phase.
3. Score every possible key by counting how many of the detected chord roots
   are diatonic to that key.  The highest-scoring key wins.

Example: user plays A – D – A – E – A
  Chord roots: [A, D, A, E, A]
  A major diatonic set: {A, B, C#, D, E, F#, G#}  (I IV V all present)
  → A scores 5/5, all other keys score lower → key = A
"""

import numpy as np

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Semitone offsets from the key root for diatonic scale degrees I ii iii IV V vi
DIATONIC_OFFSETS = [0, 2, 4, 5, 7, 9]


def _make_template(root_idx: int, chord_type: str) -> np.ndarray:
    t = np.zeros(12)
    t[root_idx % 12] = 1.0
    if chord_type == 'major':
        t[(root_idx + 4) % 12] = 0.8   # major third
        t[(root_idx + 7) % 12] = 0.9   # perfect fifth
    else:                               # minor
        t[(root_idx + 3) % 12] = 0.8   # minor third
        t[(root_idx + 7) % 12] = 0.9   # perfect fifth
    return t


# Precomputed chord templates: list of (root_name, chord_type, chroma_vector)
CHORD_TEMPLATES: list[tuple[str, str, np.ndarray]] = [
    (name, ctype, _make_template(idx, ctype))
    for idx, name in enumerate(NOTES)
    for ctype in ('major', 'minor')
]


def detect_chord(chroma: np.ndarray) -> tuple[str, str]:
    """
    Match a 12-element chroma vector to the closest major or minor chord.
    Returns (root_note, chord_type) e.g. ('A', 'major').
    """
    if chroma.max() < 1e-6:
        return ('C', 'major')
    norm = chroma / (chroma.max() + 1e-9)
    best = max(CHORD_TEMPLATES, key=lambda t: float(np.dot(norm, t[2])))
    return (best[0], best[1])


def infer_key_from_chord_sequence(chord_roots: list[str]) -> str:
    """
    Two-rule key inference:

    Rule 1 — Majority chord: if one chord root appears ≥60% of the time it is
    almost certainly the tonic.  Example: A A A A → key = A.

    Rule 2 — Diatonic scoring: score every possible key by counting how many
    of the detected chords are diatonic to it, then pick the highest.
    Example: A D E → all diatonic to A major → key = A.
    """
    if not chord_roots:
        return 'C'

    from collections import Counter
    counts = Counter(chord_roots)
    most_common, mc_count = counts.most_common(1)[0]

    # Rule 1: dominant chord = tonic
    if mc_count / len(chord_roots) >= 0.60:
        return most_common

    # Rule 2: diatonic scoring with circle-of-fifths tiebreak
    scores: dict[str, float] = {}
    for key_idx, key_name in enumerate(NOTES):
        diatonic = {NOTES[(key_idx + off) % 12] for off in DIATONIC_OFFSETS}
        scores[key_name] = sum(1.0 for c in chord_roots if c in diatonic)
    best_score = max(scores.values())
    circle = ['C', 'G', 'D', 'A', 'E', 'B', 'F#', 'F', 'A#', 'D#', 'G#', 'C#']
    candidates = [k for k in circle if scores.get(k, 0) == best_score]
    return candidates[0] if candidates else max(scores, key=lambda k: scores[k])
