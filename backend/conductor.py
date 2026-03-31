"""
Conductor: generates synchronized multi-instrument NoteEvent streams.

Design principles
-----------------
- Blues uses a deterministic 12-bar cycle (I-I-I-I / IV-IV-I-I / V-IV-I-V).
- Rock uses a Markov chord progression.
- Each chunk is bar-aligned: actual_duration = round(target/bar_dur) * bar_dur,
  so there are no gaps or overlaps between consecutive chunks.
- Per-bar chord selection means chord changes happen on downbeats, not mid-chunk.
"""

import math
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

CHORD_INTERVALS: dict[str, list[int]] = {
    'major': [0, 4, 7],
    'minor': [0, 3, 7],
    'dom7':  [0, 4, 7, 10],   # dominant 7th — characteristic blues sound
}

DEGREE_QUALITY: dict[str, dict[str, str]] = {
    'blues': {'I': 'dom7', 'IV': 'dom7', 'V': 'dom7'},
    'rock':  {'I': 'major', 'IV': 'major', 'V': 'major', 'VI': 'minor'},
}

DEGREE_OFFSETS: dict[str, int] = {'I': 0, 'IV': 5, 'V': 7, 'VI': 9}

# 12-bar blues: bars 0-11, repeating
# | I  | I  | I  | I  |
# | IV | IV | I  | I  |
# | V  | IV | I  | V  |
BLUES_12BAR = ['I', 'I', 'I', 'I', 'IV', 'IV', 'I', 'I', 'V', 'IV', 'I', 'V']

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
        self._bar_count = 0   # global bar counter — drives 12-bar position

    def update(self, key: str, bpm: float, genre: str, energy: float) -> None:
        if key:
            self.key = key
        if bpm > 0:
            self.bpm = max(60.0, min(200.0, bpm))
        self.genre = genre
        self.energy = energy

    def generate_chunk(self, duration_seconds: float = 4.0) -> tuple[list[NoteEvent], float]:
        """
        Generate one chunk of notes.

        Returns (events, actual_duration) where actual_duration is
        bar-aligned (integer number of bars × bar_dur). The caller should
        sleep for actual_duration and tell the frontend to advance
        batchOffset by actual_duration so there are no gaps.
        """
        events: list[NoteEvent] = []
        beat_dur = 60.0 / self.bpm
        bar_dur = beat_dur * 4
        bars = max(1, round(duration_seconds / bar_dur))
        actual_duration = bars * bar_dur

        last_chord_tones: list[str] = []

        for bar_idx in range(bars):
            b0 = bar_idx * bar_dur

            # ── Select chord for this bar ─────────────────────────────────
            if self.genre == 'blues':
                chord_degree = BLUES_12BAR[self._bar_count % 12]
            else:
                chord_degree = weighted_choice(
                    ROCK_PROGRESSIONS.get(self.current_chord, [('I', 1)])
                )
                self.current_chord = chord_degree

            self._bar_count += 1

            # ── Compute chord tones ───────────────────────────────────────
            key_idx = NOTES.index(self.key)
            chord_offset = DEGREE_OFFSETS.get(chord_degree, 0)
            chord_root_idx = (key_idx + chord_offset) % 12
            chord_root_name = NOTES[chord_root_idx]
            fifth_name = NOTES[(chord_root_idx + 7) % 12]
            sixth_name = NOTES[(chord_root_idx + 9) % 12]
            quality = DEGREE_QUALITY[self.genre].get(chord_degree, 'major')
            intervals = CHORD_INTERVALS[quality]
            chord_tones = [NOTES[(chord_root_idx + iv) % 12] for iv in intervals]
            last_chord_tones = chord_tones

            # Fill: last bar of 12-bar cycle (blues) or every 4th bar (rock)
            is_fill = (
                (self._bar_count - 1) % 12 == 11 if self.genre == 'blues'
                else (self._bar_count - 1) % 4 == 3
            )

            # ── Generate notes for this bar ───────────────────────────────
            if self.genre == 'blues':
                self._blues_drums_bar(events, b0, beat_dur, bar_dur, is_fill)
                self._blues_bass_bar(events, b0, beat_dur, chord_root_name, fifth_name, sixth_name)
                self._blues_keys_bar(events, b0, beat_dur, chord_tones)
            else:
                self._rock_drums_bar(events, b0, beat_dur, bar_dur, is_fill)
                self._rock_bass_bar(events, b0, beat_dur, chord_root_name)
                self._rock_keys_bar(events, b0, beat_dur, chord_tones)

        events.sort(key=lambda e: e.time)

        # ── Musicality score (last bar's chord) ───────────────────────────
        pitched = [e for e in events if e.instrument in ('bass', 'keys')]
        if pitched and last_chord_tones:
            in_chord = sum(1 for e in pitched if any(ct in e.note for ct in last_chord_tones))
            self.last_musicality_score = in_chord / len(pitched)
        else:
            self.last_musicality_score = 1.0

        return events, actual_duration

    # ── Blues patterns (single bar) ───────────────────────────────────────────

    def _blues_drums_bar(
        self, events: list, b0: float, beat_dur: float, bar_dur: float, is_fill: bool,
    ) -> None:
        """Blues shuffle: kick on 1&3, snare on 2&4, hi-hat on swing 8ths."""
        sw = beat_dur * 2 / 3
        for beat in range(4):
            t = b0 + beat * beat_dur
            if beat in (0, 2):
                events.append(NoteEvent('drums', 'kick',  '8n', t,       0.88 * self._dv()))
            if beat in (1, 3):
                events.append(NoteEvent('drums', 'snare', '8n', t,       0.82 * self._dv()))
            events.append(NoteEvent('drums', 'hat', '16n', t,            0.48 * self._dv()))
            if t + sw < b0 + bar_dur:
                events.append(NoteEvent('drums', 'hat', '16n', t + sw,   0.36 * self._dv()))
        if is_fill:
            fill_t = b0 + 3 * beat_dur
            for frac in [0.0, 0.25, 0.5, 0.75]:
                events.append(NoteEvent('drums', 'snare', '16n', fill_t + frac * beat_dur, 0.75))

    def _blues_bass_bar(
        self, events: list, b0: float, beat_dur: float,
        root: str, fifth: str, sixth: str,
    ) -> None:
        """Boogie bass: root on each beat, fifth/sixth on swing 'and'."""
        sw = beat_dur * 2 / 3
        for beat in range(4):
            t = b0 + beat * beat_dur
            events.append(NoteEvent('bass', note_with_octave(root, 2), '8n', t, 0.82))
            passing = sixth if beat == 3 else fifth
            events.append(NoteEvent('bass', note_with_octave(passing, 2), '16n', t + sw, 0.65))

    def _blues_keys_bar(
        self, events: list, b0: float, beat_dur: float, chord_tones: list[str],
    ) -> None:
        """Blues comping: chord voicings on beats 2 and 4."""
        sw = beat_dur * 2 / 3
        vel = max(0.45, min(0.75, 0.5 * self.energy + 0.3))
        voicing = [note_with_octave(ct, 4) for ct in chord_tones]
        for comp_beat in [1, 3]:
            t = b0 + comp_beat * beat_dur
            for note in voicing:
                events.append(NoteEvent('keys', note, '8n', t, vel))
            if comp_beat == 3 and random.random() < 0.30:
                ante_t = t - beat_dur + sw
                if ante_t >= b0:
                    for note in voicing:
                        events.append(NoteEvent('keys', note, '16n', ante_t, vel * 0.7))

    # ── Rock Engine v1 (single bar) ───────────────────────────────────────────

    _BEAT_VEL    = [115/127, 85/127, 100/127, 85/127]
    _ARP_PATTERN = [0, 1, 2, 1, 0, 1, 2, 1]

    def _vel_scale(self) -> float:
        return 1.0 + self.energy * 0.15

    def _rock_drums_bar(
        self, events: list, b0: float, beat_dur: float, bar_dur: float, is_fill: bool,
    ) -> None:
        eighth = beat_dur * 0.5
        vs = self._vel_scale()
        for tick in range(8):
            t = b0 + tick * eighth
            beat = tick // 2
            if is_fill and tick >= 4:
                if tick in (4, 5):
                    events.append(NoteEvent('drums', 'kick',  '16n', t,
                                            min(1.0, (110/127) * vs * self._dv())))
                if tick in (6, 7):
                    events.append(NoteEvent('drums', 'snare', '16n', t,
                                            min(1.0, (120/127) * vs * self._dv())))
                events.append(NoteEvent('drums', 'hat', '16n', t,
                                        min(1.0, 0.80 * vs * self._dv())))
            else:
                bv = min(1.0, self._BEAT_VEL[beat] * vs * self._dv())
                if tick in (0, 4):
                    events.append(NoteEvent('drums', 'kick',  '8n', t, bv))
                if tick in (2, 6):
                    events.append(NoteEvent('drums', 'snare', '8n', t, bv))
                hat_v = min(1.0, (0.75 if tick % 2 == 0 else 0.55) * vs * self._dv())
                events.append(NoteEvent('drums', 'hat', '16n', t, hat_v))

    def _rock_bass_bar(
        self, events: list, b0: float, beat_dur: float, root: str,
    ) -> None:
        vs = self._vel_scale()
        for beat in range(4):
            t = b0 + beat * beat_dur
            vel = min(1.0, self._BEAT_VEL[beat] * vs)
            events.append(NoteEvent('bass', note_with_octave(root, 2), '4n', t, vel))
            events.append(NoteEvent('keys', note_with_octave(root, 3), '4n', t,
                                    max(0.0, vel - 10/127)))

    def _rock_keys_bar(
        self, events: list, b0: float, beat_dur: float, chord_tones: list[str],
    ) -> None:
        eighth = beat_dur * 0.5
        rh_vel = min(1.0, max(0.40, 0.63 * self._vel_scale()))
        n = len(chord_tones)
        for tick in range(8):
            t = b0 + tick * eighth
            idx = self._ARP_PATTERN[tick] % n
            note = note_with_octave(chord_tones[idx], 4)
            events.append(NoteEvent('keys', note, '8n', t, rh_vel))

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _dv(self) -> float:
        """Drum velocity with human-like micro-variation."""
        base = 0.5 + self.energy * 0.5
        return max(0.3, min(1.0, base + random.uniform(-0.08, 0.08)))
