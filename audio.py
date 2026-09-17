"""Sound-effect loading with procedural-synthesis fallback -- audio's
counterpart to assets.py (see that module's own docstring for the pattern
mirrored here). Every sound the game needs is referred to elsewhere by a
*logical name* (e.g. "tower_placed", "enemy_killed") rather than a file
path. SOUND_MANIFEST maps a logical name to where its real audio file
should live under assets/sfx/, plus a fallback synthesis recipe -- a
sequence of SynthSpec "notes" (waveform, optional frequency sweep, a
simple attack/decay/sustain/release envelope) to build in pure Python if
that file doesn't exist yet.

This means: today, with no sound pack present, every cue is a short
procedurally-synthesized chiptune-style blip -- the audio equivalent of
AssetManager's colored-rect placeholders, not an attempt at realism, and a
deliberate match for the game's own placeholder-shape visual style. Later,
dropping real .wav/.ogg files into assets/sfx/ at the paths listed below
makes the real audio play with *no code changes*, exactly like sprites --
unless the pack uses different filenames, in which case only the path
string in the manifest needs editing.

Unlike a placeholder Surface, a synthesized sound's raw bytes are coupled
to the mixer's actual initialized sample format (pygame.mixer.get_init()'s
own return -- not necessarily what Game.__init__ requested it with, see
that method's own comment) -- SoundManager reads that back once and builds
a matching encoder, so synthesis works across mono/stereo and 8/16/32-bit
alike rather than assuming one fixed shape. An unrecognized format
disables *synthesis only*; a real on-disk file still plays regardless,
since SDL decodes those independently of anything this module builds by
hand.
"""

import array
import math
import os
import random
from dataclasses import dataclass

import pygame

from assets import (
    DEFAULT_ASSET_ROOT,  # both modules' files live under the same assets/ tree
)

# Raised from SDL_mixer's default of 8 -- a busy board can have well over a
# dozen towers firing, several projectiles resolving, and an enemy dying
# all in the same frame, and Sound.play() simply fails to find a free
# channel and drops the cue once every one is already busy, rather than
# stealing one. 32 gives generous headroom over any realistic single-frame
# burst at negligible mixing cost.
NUM_CHANNELS = 32


@dataclass(frozen=True)
class SynthSpec:
    """One "note" of a synthesized cue: a waveform held for `duration`
    seconds under a simple linear attack/decay/sustain/release envelope,
    optionally sweeping frequency linearly from one pitch to another
    instead of holding one constant pitch -- a zap/whoosh/descending-poof
    character with no extra machinery. waveform is one of "sine"/"square"/
    "triangle"/"noise" ("noise" ignores frequency; see _render_note's own
    deterministic per-sound-name Random). A SOUND_MANIFEST entry is a
    *tuple* of these, concatenated in time -- a single blip is a 1-tuple, a
    fanfare is several back to back, the same "one data-parametrized shape,
    several constructor-arg combinations" spirit Projectile/effects.
    ExpandingRing already use elsewhere in this codebase."""

    waveform: str
    frequency: float = 440.0  # or an (start_hz, end_hz) tuple for a linear sweep
    duration: float = 0.08
    volume: float = 0.6
    attack: float = 0.005
    decay: float = 0.02
    sustain_level: float = 0.7
    release: float = 0.03


# logical_name -> (relative_path_under_assets/, (SynthSpec, ...))
SOUND_MANIFEST = {
    # --- Tower fire families (Tower.FIRE_SOUND, see tower.py) ---
    "tower_fire_default": ("sfx/tower_fire_default.wav", (
        SynthSpec("square", frequency=880, duration=0.05, volume=0.5, release=0.02),
    )),
    "tower_fire_heavy": ("sfx/tower_fire_heavy.wav", (
        SynthSpec("square", frequency=180, duration=0.09, volume=0.7, attack=0.001, release=0.05),
    )),
    "tower_fire_zap": ("sfx/tower_fire_zap.wav", (
        SynthSpec("square", frequency=(1200, 300), duration=0.06, volume=0.45, release=0.02),
    )),

    # --- Combat feedback ---
    "enemy_hit_small": ("sfx/enemy_hit_small.wav", (
        SynthSpec("square", frequency=520, duration=0.04, volume=0.35, release=0.02),
    )),
    "enemy_hit_splash": ("sfx/enemy_hit_splash.wav", (
        SynthSpec("noise", duration=0.12, volume=0.5, attack=0.002, decay=0.04, release=0.08),
    )),
    "enemy_killed": ("sfx/enemy_killed.wav", (
        SynthSpec("triangle", frequency=(400, 120), duration=0.12, volume=0.5, release=0.08),
    )),
    "life_lost": ("sfx/life_lost.wav", (
        SynthSpec("square", frequency=(300, 150), duration=0.25, volume=0.5, release=0.18),
    )),

    # --- Tower economy ---
    "tower_placed": ("sfx/tower_placed.wav", (
        SynthSpec("sine", frequency=660, duration=0.06, volume=0.45, release=0.03),
        SynthSpec("sine", frequency=880, duration=0.07, volume=0.45, release=0.04),
    )),
    "tower_upgraded": ("sfx/tower_upgraded.wav", (
        SynthSpec("sine", frequency=523, duration=0.06, volume=0.45, release=0.02),
        SynthSpec("sine", frequency=784, duration=0.09, volume=0.5, release=0.05),
    )),
    "tower_sold": ("sfx/tower_sold.wav", (
        SynthSpec("triangle", frequency=(500, 250), duration=0.15, volume=0.45, release=0.1),
    )),

    # --- Run/wave flow ---
    "wave_start": ("sfx/wave_start.wav", (
        SynthSpec("square", frequency=440, duration=0.08, volume=0.4, release=0.03),
        SynthSpec("square", frequency=660, duration=0.1, volume=0.45, release=0.05),
    )),
    "floor_cleared": ("sfx/floor_cleared.wav", (
        SynthSpec("sine", frequency=523, duration=0.09, volume=0.5, release=0.03),
        SynthSpec("sine", frequency=659, duration=0.09, volume=0.5, release=0.03),
        SynthSpec("sine", frequency=784, duration=0.16, volume=0.55, release=0.08),
    )),
    "boss_defeated": ("sfx/boss_defeated.wav", (
        SynthSpec("sine", frequency=392, duration=0.1, volume=0.55, release=0.03),
        SynthSpec("sine", frequency=523, duration=0.1, volume=0.55, release=0.03),
        SynthSpec("sine", frequency=659, duration=0.1, volume=0.55, release=0.03),
        SynthSpec("sine", frequency=1046, duration=0.3, volume=0.6, release=0.15),
    )),
    "game_over": ("sfx/game_over.wav", (
        SynthSpec("square", frequency=392, duration=0.12, volume=0.5, release=0.04),
        SynthSpec("square", frequency=330, duration=0.12, volume=0.5, release=0.04),
        SynthSpec("square", frequency=262, duration=0.12, volume=0.5, release=0.04),
        SynthSpec("square", frequency=196, duration=0.35, volume=0.55, release=0.2),
    )),
    "victory": ("sfx/victory.wav", (
        SynthSpec("sine", frequency=523, duration=0.09, volume=0.55, release=0.03),
        SynthSpec("sine", frequency=659, duration=0.09, volume=0.55, release=0.03),
        SynthSpec("sine", frequency=784, duration=0.09, volume=0.55, release=0.03),
        SynthSpec("sine", frequency=1318, duration=0.35, volume=0.6, release=0.18),
    )),

    # --- Shop / relics / meta ---
    "relic_acquired": ("sfx/relic_acquired.wav", (
        SynthSpec("sine", frequency=784, duration=0.06, volume=0.45, release=0.02),
        SynthSpec("sine", frequency=988, duration=0.06, volume=0.45, release=0.02),
        SynthSpec("sine", frequency=1244, duration=0.12, volume=0.5, release=0.06),
    )),
    "tower_unlocked_shop": ("sfx/tower_unlocked_shop.wav", (
        SynthSpec("square", frequency=660, duration=0.06, volume=0.4, release=0.02),
        SynthSpec("square", frequency=880, duration=0.08, volume=0.45, release=0.03),
    )),
    "achievement_toast": ("sfx/achievement_toast.wav", (
        SynthSpec("sine", frequency=1046, duration=0.1, volume=0.4, release=0.05),
    )),
}


class SoundManager:
    """Plays sounds by logical name, caching results and falling back to a
    synthesized pygame.mixer.Sound when the real audio file is absent --
    same "falling back is silent either way" spirit as AssetManager.
    Synthesized sounds are cached in memory for this instance's lifetime
    only, never written to disk -- assets/sfx/ stays empty except its own
    .gitkeep until a human drops a real file in, exactly like every other
    assets/ subfolder."""

    def __init__(self, asset_root=DEFAULT_ASSET_ROOT, enabled=True):
        self.asset_root = asset_root
        self.enabled = bool(enabled)
        self._cache = {}
        mixer_format = pygame.mixer.get_init()  # None if never initialized
        self.mixer_ready = mixer_format is not None
        self._format = mixer_format
        self._encoder = _encoder_for(mixer_format) if mixer_format else None

        if self.mixer_ready:
            # Owned here, not by whoever happens to call pygame.mixer.
            # init() first -- every SoundManager needs this same fix
            # regardless of construction path (Game.__init__, a test, ...),
            # so it belongs on the class that defines NUM_CHANNELS, not
            # duplicated at each call site.
            try:
                pygame.mixer.set_num_channels(NUM_CHANNELS)
            except pygame.error:
                pass

    def set_enabled(self, value):
        self.enabled = bool(value)

    def preload_all(self):
        """Synthesize/load every SOUND_MANIFEST entry now rather than
        leaving each cue's one-time cost (measured around 15-20ms for the
        single heaviest cue, ~100ms for the whole manifest) to land on
        whatever frame first needs it -- a rare cue (e.g. "boss_defeated",
        played once per run at a dramatic moment) would otherwise risk a
        frame hitch landing on exactly the frame it needs to play cleanly.

        Deliberately *not* called from __init__ itself: main.py calls this
        once, right after constructing Game() and before game.run() starts
        the frame loop, so a real play session still pays this cost up
        front as a one-time load-time hit -- but every other construction
        path (every test's own Game()/playing_game fixture, the run-td
        driver, anything that just wants a working SoundManager without
        caring about warm-cache timing) stays cheap and lazy instead of
        eagerly synthesizing ~18 cues -- and re-synthesizing them again for
        every single one of a test suite's several thousand Game()
        constructions -- for no benefit any of those callers can use.

        A no-op if the mixer never came up (get() would only return None
        for every fileless entry anyway); per-entry failures are swallowed
        the same defensive way play() itself is, so one bad/corrupt real
        file can't block every other cue from warming."""
        if not self.mixer_ready:
            return
        for logical_name in SOUND_MANIFEST:
            try:
                self.get(logical_name)
            except pygame.error:
                pass

    def play(self, logical_name):
        """Fire-and-forget. A silent no-op for a falsy logical_name (e.g.
        Tower.FIRE_SOUND=None on SupportTower), while sound is disabled, or
        while the mixer itself never came up -- and wrapped in a broad
        try/except, same "an audio hiccup should never crash the game"
        spirit as every other defensive fallback in this codebase."""
        if not logical_name or not self.enabled or not self.mixer_ready:
            return
        sound = self.get(logical_name)
        if sound is None:
            return
        try:
            sound.play()
        except pygame.error:
            pass

    def get(self, logical_name):
        """Return a pygame.mixer.Sound for logical_name, or None if it has
        no real file on disk and this mixer's own format can't be
        hand-synthesized for (see _encoder_for). Cached per logical name --
        one dict lookup on a cache hit (the common case once preload_all()
        has run), not two."""
        try:
            return self._cache[logical_name]
        except KeyError:
            pass
        sound = self._load_or_synthesize(logical_name)
        self._cache[logical_name] = sound
        return sound

    def _load_or_synthesize(self, logical_name):
        if logical_name not in SOUND_MANIFEST:
            raise KeyError(
                f"Unknown sound logical_name {logical_name!r} -- "
                f"add it to SOUND_MANIFEST in audio.py"
            )
        rel_path, spec_sequence = SOUND_MANIFEST[logical_name]
        full_path = os.path.join(self.asset_root, rel_path)

        if os.path.isfile(full_path):
            return pygame.mixer.Sound(full_path)

        if self._encoder is None:
            return None

        frequency, _size, channels = self._format
        raw = _render_pcm(logical_name, spec_sequence, frequency, channels, self._encoder)
        return pygame.mixer.Sound(buffer=raw)


# --- Synthesis: pure Python (array/math/random), no numpy ---

def _envelope(t, spec):
    """Piecewise-linear ADSR gain in [0, 1] at time t (seconds) into a note
    of spec.duration seconds. attack/decay/release are scaled down together
    if their sum would otherwise overrun duration, so a very short note
    (e.g. a 0.03s blip) still fades in and out cleanly instead of clicking
    at its edges."""
    attack, decay, release = spec.attack, spec.decay, spec.release
    total = attack + decay + release
    if total > spec.duration > 0:
        scale = spec.duration / total
        attack, decay, release = attack * scale, decay * scale, release * scale

    if t < attack:
        return t / attack if attack > 0 else 1.0
    if t < attack + decay:
        frac = (t - attack) / decay if decay > 0 else 1.0
        return 1.0 + (spec.sustain_level - 1.0) * frac
    release_start = spec.duration - release
    if t < release_start:
        return spec.sustain_level
    frac = (t - release_start) / release if release > 0 else 1.0
    return spec.sustain_level * max(0.0, 1.0 - frac)


def _render_note(spec, sample_rate, noise_rng):
    """Return spec's samples as a list of floats in [-1, 1] at sample_rate."""
    sample_count = max(1, round(spec.duration * sample_rate))
    freq_start, freq_end = spec.frequency if isinstance(spec.frequency, tuple) else (spec.frequency, spec.frequency)
    phase = 0.0
    samples = []
    for i in range(sample_count):
        t = i / sample_rate
        freq = freq_start + (freq_end - freq_start) * (i / sample_count)
        phase += freq / sample_rate
        theta = 2 * math.pi * phase
        if spec.waveform == "sine":
            raw = math.sin(theta)
        elif spec.waveform == "square":
            raw = 1.0 if math.sin(theta) >= 0 else -1.0
        elif spec.waveform == "triangle":
            raw = (2.0 / math.pi) * math.asin(math.sin(theta))
        elif spec.waveform == "noise":
            raw = noise_rng.uniform(-1.0, 1.0)
        else:
            raise ValueError(
                f"Unknown SynthSpec.waveform {spec.waveform!r} -- "
                f"expected 'sine'/'square'/'triangle'/'noise'"
            )
        gain = spec.volume * _envelope(t, spec)
        samples.append(max(-1.0, min(1.0, raw * gain)))
    return samples


def _render_pcm(logical_name, spec_sequence, sample_rate, channels, encoder):
    """Build a raw PCM byte buffer for pygame.mixer.Sound(buffer=...) out of
    spec_sequence's notes, concatenated in time and replicated across every
    output channel. Seeded from the sound's own logical name, not the
    shared `random` module -- deterministic/reproducible across runs and
    never perturbs any of this codebase's own seeded gameplay RNG streams,
    the same "derive a fresh Random from a string key" precedent Game.
    _run_rng already sets for run-loop RNG (see CLAUDE.md's "run loop"
    section)."""
    typecode, encode = encoder
    noise_rng = random.Random(f"td-sfx:{logical_name}")
    floats = []
    for spec in spec_sequence:
        floats.extend(_render_note(spec, sample_rate, noise_rng))
    out = array.array(typecode)
    for value in floats:
        encoded = encode(value)
        for _ in range(channels):
            out.append(encoded)  # no throwaway list -- append the same encoded value `channels` times
    return out.tobytes()


def _encoder_for(mixer_format):
    """mixer_format is pygame.mixer.get_init()'s own (frequency, size,
    channels) -- the *actual* initialized format, which isn't guaranteed to
    match what Game.__init__ requested it with. Returns (typecode,
    encode_one_sample) for turning a float sample in [-1, 1] into one raw
    value of that format, or None for a size this module doesn't recognize
    -- see SoundManager's own docstring for what happens then (synthesis
    degrades, real on-disk files are unaffected). size's only documented
    values are 8/-8/16/-16 (bit depth, negative meaning signed) and 32
    (always float -- pygame/SDL never expose a signed/unsigned 32-bit
    *integer* format through this API, so there's no ambiguity to resolve
    there). array's typecodes are always native-endian, which is also all
    pygame's own `size` abstraction ever produces (it has no explicit
    LSB/MSB variant), so there's no byte-order mismatch to worry about
    either."""
    _frequency, size, _channels = mixer_format
    if abs(size) == 32:
        return "f", lambda s: s
    bits, signed = abs(size), size < 0
    if bits == 8:
        typecode = "b" if signed else "B"
    elif bits == 16:
        typecode = "h" if signed else "H"
    else:
        return None
    peak = 2 ** (bits - 1) - 1
    if signed:
        return typecode, lambda s, peak=peak: int(s * peak)
    midpoint = peak + 1
    return typecode, lambda s, peak=peak, midpoint=midpoint: int(midpoint + s * peak)
