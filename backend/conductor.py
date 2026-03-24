"""
Conductor: generates synchronized multi-instrument NoteEvent streams.

Design principles
-----------------
- All instruments reference the same chord each 4-second chunk.
- Keys play full chord voicings (root + third + fifth + optional 7th)
  as simultaneous NoteEvents — not random single notes.
- Bass plays groove patterns that relate to the chord (root, fifth, sixth).
- Drums lock to the groove feel (blues shuffle vs. rock straight).
- Each instrument's rhythm pattern is internally consistent so the band
  sounds like it's playing together, not independently.
"""

import random
from dataclasses import dataclass

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def note_with_octave(note: str, octave: int) -> str:
    return f'{note}{octave}'


def weighted_choice(options: list[tuple[str, int]]) -> str:
    items = [o[0] for o in options]
    weights = [o[1] for o in options]
    return random.choices(items, weights=weights, k=1)[0]


# ── Note event ────────────────────────────────────────────────────────────────

@dataclass
class NoteEvent:
    instrument: str   # 'drums' | 'bass' | 'keys'
    note: str         # e.g. 'kick', 'A3', 'C4'
    duration: str     # Tone.js notation: '4n', '8n', '16n'
    time: float       # seconds offset from chunk start
    velocity: float   # 0.0 – 1.0


# ── Chord library ─────────────────────────────────────────────────────────────

# Semitone intervals for each chord quality
CHORD_INTERVALS: dict[str, list[int]] = {
    'major': [0, 4, 7],
    'minor': [0, 3, 7],
    'dom7':  [0, 4, 7, 10],   # dominant 7th — characteristic blues sound
}

# Quality of each scale degree per genre
DEGREE_QUALITY: dict[str, dict[str, str]] = {
    'blues': {'I': 'dom7', 'IV': 'dom7', 'V': 'dom7'},
    'rock':  {'I': 'major', 'IV': 'major', 'V': 'major', 'VI': 'minor'},
}

# Semitone offset of each Roman numeral from the key root
DEGREE_OFFSETS: dict[str, int] = {'I': 0, 'IV': 5, 'V': 7, 'VI': 9}

# Markov chord progressions
BLUES_PROGRESSIONS: dict[str, list[tuple[str, int]]] = {
    'I':  [('I', 1), ('IV', 3), ('V', 1)],
    'IV': [('I', 2), ('IV', 1), ('V', 2)],
    'V':  [('I', 3), ('IV', 1)],
}
ROCK_PROGRESSIONS: dict[str, list[tuple[str, int]]] = {
    'I':  [('I', 1), ('IV', 2), ('V', 2), ('VI', 1)],
    'IV': [('I', 2), ('V', 2), ('IV', 1)],
    'V':  [('I', 3), ('IV', 1)],
    'VI': [('IV', 2), ('I', 1), ('V', 1)],
}


# ── Conductor ─────────────────────────────────────────────────────────────────

class Conductor:
    def __init__(self) -> None:
        self.genre = 'blues'
        self.key = 'A'
        self.bpm = 100.0
        self.current_chord = 'I'
        self.energy = 0.5
        self.last_musicality_score: float = 1.0
        self._chunk_count = 0

    def update(self, key: str, bpm: float, genre: str, energy: float) -> None:
        if key:
            self.key = key
        if bpm > 0:
            self.bpm = max(60.0, min(200.0, bpm))
        self.genre = genre
        self.energy = energy

    def generate_chunk(self, duration_seconds: float = 4.0) -> list[NoteEvent]:
        events: list[NoteEvent] = []
        beat_dur = 60.0 / self.bpm
        bar_dur = beat_dur * 4
        bars = max(1, int(duration_seconds / bar_dur))

        # ── Advance chord (Markov) ────────────────────────────────────────
        progressions = BLUES_PROGRESSIONS if self.genre == 'blues' else ROCK_PROGRESSIONS
        self.current_chord = weighted_choice(
            progressions.get(self.current_chord, [('I', 1)])
        )

        # ── Compute chord tones ───────────────────────────────────────────
        key_idx = NOTES.index(self.key)
        chord_offset = DEGREE_OFFSETS.get(self.current_chord, 0)
        chord_root_idx = (key_idx + chord_offset) % 12
        chord_root_name = NOTES[chord_root_idx]

        quality = DEGREE_QUALITY[self.genre].get(self.current_chord, 'major')
        intervals = CHORD_INTERVALS[quality]
        # Names of each chord tone (root, 3rd, 5th, [7th for blues])
        chord_tones = [NOTES[(chord_root_idx + iv) % 12] for iv in intervals]

        fifth_name = NOTES[(chord_root_idx + 7) % 12]
        sixth_name = NOTES[(chord_root_idx + 9) % 12]   # major sixth (for bass turnaround)

        # ── Generate each instrument ──────────────────────────────────────
        if self.genre == 'blues':
            self._blues_drums(events, bars, beat_dur, bar_dur)
            self._blues_bass(events, bars, beat_dur, bar_dur, chord_root_name, fifth_name, sixth_name)
            self._blues_keys(events, bars, beat_dur, bar_dur, chord_root_idx, chord_tones)
        else:
            self._rock_drums(events, bars, beat_dur, bar_dur)
            self._rock_bass(events, bars, beat_dur, bar_dur, chord_root_name, fifth_name)
            self._rock_keys(events, bars, beat_dur, bar_dur, chord_root_idx, chord_tones)

        events.sort(key=lambda e: e.time)

        # ── Musicality score ──────────────────────────────────────────────
        pitched = [e for e in events if e.instrument in ('bass', 'keys')]
        if pitched:
            in_chord = sum(
                1 for e in pitched
                if any(ct in e.note for ct in chord_tones)
            )
            self.last_musicality_score = in_chord / len(pitched)
        else:
            self.last_musicality_score = 1.0

        self._chunk_count += 1
        return events

    # ── Blues patterns ────────────────────────────────────────────────────────

    def _blues_drums(self, events: list, bars: int, beat_dur: float, bar_dur: float) -> None:
        """Blues shuffle: kick on 1&3, snare on 2&4, hi-hat on swing 8ths."""
        sw = beat_dur * 2 / 3   # swing "and" (triplet feel)
        is_fill = (self._chunk_count % 4 == 3)

        for bar in range(bars):
            b0 = bar * bar_dur
            for beat in range(4):
                t = b0 + beat * beat_dur

                if beat in (0, 2):
                    events.append(NoteEvent('drums', 'kick',  '8n',  t,        0.88 * self._dv()))
                if beat in (1, 3):
                    events.append(NoteEvent('drums', 'snare', '8n',  t,        0.82 * self._dv()))
                # Hi-hat: on the beat and on the swing "and"
                events.append(NoteEvent('drums', 'hat', '16n', t,        0.48 * self._dv()))
                if t + sw < b0 + bar_dur:
                    events.append(NoteEvent('drums', 'hat', '16n', t + sw,  0.36 * self._dv()))

            # Drum fill on last bar of every 4th chunk
            if is_fill and bar == bars - 1:
                fill_t = b0 + 3 * beat_dur
                for frac in [0.0, 0.25, 0.5, 0.75]:
                    events.append(NoteEvent('drums', 'snare', '16n', fill_t + frac * beat_dur, 0.75))

    def _blues_bass(
        self, events: list, bars: int, beat_dur: float, bar_dur: float,
        root: str, fifth: str, sixth: str,
    ) -> None:
        """
        Classic blues boogie bass: root on each beat, fifth on the swing 'and',
        sixth on the 'and' of beat 4 for a turnaround feel.
        """
        sw = beat_dur * 2 / 3
        for bar in range(bars):
            b0 = bar * bar_dur
            for beat in range(4):
                t = b0 + beat * beat_dur
                events.append(NoteEvent('bass', note_with_octave(root, 2), '8n', t, 0.82))
                # Swing "and": fifth, except beat 4 → sixth (turnaround)
                passing = sixth if beat == 3 else fifth
                events.append(NoteEvent('bass', note_with_octave(passing, 2), '16n', t + sw, 0.65))

    def _blues_keys(
        self, events: list, bars: int, beat_dur: float, bar_dur: float,
        chord_root_idx: int, chord_tones: list[str],
    ) -> None:
        """
        Blues comping: chord voicings (root + 3rd + 5th + 7th) on beats 2 and 4.
        Occasionally adds an anticipation hit on the swing 'and' before beat 4.
        """
        sw = beat_dur * 2 / 3
        vel = max(0.45, min(0.75, 0.5 * self.energy + 0.3))

        # Chord voicing: play all chord tones simultaneously
        voicing = [note_with_octave(ct, 4) for ct in chord_tones]

        for bar in range(bars):
            b0 = bar * bar_dur
            for comp_beat in [1, 3]:    # beats 2 and 4 (0-indexed)
                t = b0 + comp_beat * beat_dur
                for note in voicing:
                    events.append(NoteEvent('keys', note, '8n', t, vel))
                # Anticipation: 30% chance of extra hit just before beat 4
                if comp_beat == 3 and random.random() < 0.30:
                    ante_t = t - beat_dur + sw   # swing "and" of beat 3
                    if ante_t >= b0:
                        for note in voicing:
                            events.append(NoteEvent('keys', note, '16n', ante_t, vel * 0.7))

    # ── Rock patterns ─────────────────────────────────────────────────────────

    def _rock_drums(self, events: list, bars: int, beat_dur: float, bar_dur: float) -> None:
        """Rock 4/4: kick on 1&3, snare on 2&4, straight 8th hi-hats."""
        half = beat_dur / 2

        for bar in range(bars):
            b0 = bar * bar_dur
            for beat in range(4):
                t = b0 + beat * beat_dur
                if beat in (0, 2):
                    events.append(NoteEvent('drums', 'kick',  '8n',  t,       0.92 * self._dv()))
                if beat in (1, 3):
                    events.append(NoteEvent('drums', 'snare', '8n',  t,       0.88 * self._dv()))
                events.append(NoteEvent('drums', 'hat', '16n', t,       0.55 * self._dv()))
                if t + half < b0 + bar_dur:
                    events.append(NoteEvent('drums', 'hat', '16n', t + half, 0.42 * self._dv()))

    def _rock_bass(
        self, events: list, bars: int, beat_dur: float, bar_dur: float,
        root: str, fifth: str,
    ) -> None:
        """Rock bass: root on 1&3, fifth on 2, root on 4. 8ths on high energy."""
        for bar in range(bars):
            b0 = bar * bar_dur
            beat_notes = [root, fifth, root, fifth]
            for beat in range(4):
                t = b0 + beat * beat_dur
                note = note_with_octave(beat_notes[beat], 2)
                events.append(NoteEvent('bass', note, '4n', t, 0.82))
                # Extra 8th on the "and" when energy is high
                if self.energy > 0.6 and beat in (0, 2):
                    events.append(NoteEvent('bass', note, '8n', t + beat_dur * 0.5, 0.60))

    def _rock_keys(
        self, events: list, bars: int, beat_dur: float, bar_dur: float,
        chord_root_idx: int, chord_tones: list[str],
    ) -> None:
        """Rock keys: power chord stabs on beats 1 and 3."""
        vel = max(0.50, min(0.80, 0.55 * self.energy + 0.3))
        voicing = [note_with_octave(ct, 4) for ct in chord_tones]

        for bar in range(bars):
            b0 = bar * bar_dur
            for stab_beat in [0, 2]:
                t = b0 + stab_beat * beat_dur
                for note in voicing:
                    events.append(NoteEvent('keys', note, '4n', t, vel))

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _dv(self) -> float:
        """Drum velocity with human-like micro-variation."""
        base = 0.5 + self.energy * 0.5
        return max(0.3, min(1.0, base + random.uniform(-0.08, 0.08)))
