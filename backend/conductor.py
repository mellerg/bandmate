import random
from dataclasses import dataclass

# ── Music theory helpers ──────────────────────────────────────────────────────

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11]
MINOR_INTERVALS = [0, 2, 3, 5, 7, 8, 10]
BLUES_INTERVALS = [0, 3, 5, 6, 7, 10]  # blues pentatonic


def get_scale(root: str, scale_type: str = 'major') -> list[str]:
    root_idx = NOTES.index(root)
    if scale_type == 'blues':
        intervals = BLUES_INTERVALS
    elif scale_type == 'minor':
        intervals = MINOR_INTERVALS
    else:
        intervals = MAJOR_INTERVALS
    return [NOTES[(root_idx + i) % 12] for i in intervals]


def note_with_octave(note: str, octave: int) -> str:
    return f'{note}{octave}'


# ── Note event dataclass ──────────────────────────────────────────────────────

@dataclass
class NoteEvent:
    instrument: str   # 'drums' | 'bass' | 'keys'
    note: str         # e.g. 'kick', 'C3'
    duration: str     # Tone.js notation: '4n', '8n', '16n'
    time: float       # seconds offset within this chunk
    velocity: float   # 0.0 – 1.0


# ── Markov state tables ───────────────────────────────────────────────────────

# Drum patterns: list of (beat_offset, note_name, velocity)
BLUES_DRUM_PATTERN = [
    (0.0, 'kick', 0.9),
    (0.5, 'hat', 0.5),
    (1.0, 'snare', 0.85),
    (1.5, 'hat', 0.5),
    (2.0, 'kick', 0.9),
    (2.5, 'hat', 0.45),
    (3.0, 'snare', 0.85),
    (3.5, 'hat', 0.5),
]

ROCK_DRUM_PATTERN = [
    (0.0, 'kick', 0.95),
    (0.5, 'hat', 0.6),
    (1.0, 'snare', 0.9),
    (1.5, 'hat', 0.55),
    (2.0, 'kick', 0.95),
    (2.25, 'kick', 0.7),
    (3.0, 'snare', 0.9),
    (3.5, 'hat', 0.55),
]

# Markov chord progressions: maps chord -> list of next chords (with weights)
BLUES_PROGRESSIONS = {
    'I':  [('I', 1), ('IV', 3), ('V', 1)],
    'IV': [('I', 2), ('IV', 1), ('V', 2)],
    'V':  [('I', 3), ('IV', 1)],
}

ROCK_PROGRESSIONS = {
    'I':  [('I', 1), ('IV', 2), ('V', 2), ('VI', 1)],
    'IV': [('I', 2), ('V', 2), ('IV', 1)],
    'V':  [('I', 3), ('IV', 1)],
    'VI': [('IV', 2), ('I', 1), ('V', 1)],
}

DEGREE_OFFSETS = {'I': 0, 'IV': 5, 'V': 7, 'VI': 9}


def weighted_choice(options: list[tuple[str, int]]) -> str:
    items = [o[0] for o in options]
    weights = [o[1] for o in options]
    return random.choices(items, weights=weights, k=1)[0]


# ── Conductor ─────────────────────────────────────────────────────────────────

class Conductor:
    def __init__(self):
        self.genre = 'blues'
        self.key = 'A'
        self.bpm = 100.0
        self.current_chord = 'I'
        self.energy = 0.5
        self.last_musicality_score: float = 1.0  # ratio of in-scale pitched notes

    def update(self, key: str, bpm: float, genre: str, energy: float):
        if key:
            self.key = key
        if bpm > 0:
            self.bpm = max(60.0, min(200.0, bpm))
        self.genre = genre
        self.energy = energy

    def generate_chunk(self, duration_seconds: float = 4.0) -> list[NoteEvent]:
        """Generate a list of NoteEvents covering the next duration_seconds."""
        events: list[NoteEvent] = []
        beat_duration = 60.0 / self.bpm  # seconds per beat
        beats_in_chunk = int(duration_seconds / beat_duration)

        # Advance chord
        progressions = BLUES_PROGRESSIONS if self.genre == 'blues' else ROCK_PROGRESSIONS
        options = progressions.get(self.current_chord, [('I', 1)])
        self.current_chord = weighted_choice(options)

        # Build scale/chord notes
        scale_type = 'blues' if self.genre == 'blues' else 'major'
        scale = get_scale(self.key, scale_type)
        root_offset = DEGREE_OFFSETS.get(self.current_chord, 0)
        root_idx = NOTES.index(self.key)
        chord_root = NOTES[(root_idx + root_offset) % 12]

        # Drums
        pattern = BLUES_DRUM_PATTERN if self.genre == 'blues' else ROCK_DRUM_PATTERN
        bar_duration = beat_duration * 4
        bars = max(1, int(duration_seconds / bar_duration))
        for bar in range(bars):
            bar_offset = bar * bar_duration
            for (beat_off, drum_note, vel) in pattern:
                t = bar_offset + beat_off * beat_duration
                if t < duration_seconds:
                    events.append(NoteEvent('drums', drum_note, '16n', t, vel * self._drum_velocity()))

        # Bass line: root on beats 1 and 3
        for beat in range(beats_in_chunk):
            if beat % 4 in (0, 2):
                t = beat * beat_duration
                bass_note = note_with_octave(chord_root, 2)
                events.append(NoteEvent('bass', bass_note, '4n', t, 0.75 * self.energy + 0.1))
            elif beat % 4 == 1 and random.random() < 0.4:
                # Walking bass passing note
                passing = scale[random.randint(0, min(2, len(scale) - 1))]
                events.append(NoteEvent('bass', note_with_octave(passing, 2), '8n', beat * beat_duration, 0.6))

        # Keys: chord stabs on off-beats
        if self.energy > 0.3:
            chord_notes = [
                note_with_octave(chord_root, 4),
                note_with_octave(scale[min(2, len(scale)-1)], 4),
                note_with_octave(scale[min(4, len(scale)-1)], 4),
            ]
            for beat in range(beats_in_chunk):
                if beat % 2 == 0 and random.random() < 0.6:
                    t = beat * beat_duration
                    note = random.choice(chord_notes)
                    events.append(NoteEvent('keys', note, '8n', t, 0.5 * self.energy + 0.15))

        events.sort(key=lambda e: e.time)

        # Compute musicality score: % of pitched (bass/keys) notes in the current scale
        pitched = [e for e in events if e.instrument in ('bass', 'keys')]
        if pitched:
            in_scale = sum(
                1 for e in pitched
                if e.note[:2].rstrip('0123456789') in scale
                or e.note[:1] in scale
            )
            self.last_musicality_score = in_scale / len(pitched)
        else:
            self.last_musicality_score = 1.0

        return events

    def _drum_velocity(self) -> float:
        base = 0.5 + self.energy * 0.5
        return max(0.3, min(1.0, base + random.uniform(-0.05, 0.05)))
