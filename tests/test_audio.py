"""Tests for audio.SoundManager.

Deliberately points every fallback-path test at a nonexistent asset_root
(never the project's real assets/ folder) so results stay the same no
matter what real audio has or hasn't been dropped into assets/sfx/
locally -- same reasoning test_assets.py's own module docstring gives.

Since nothing here can actually be *heard* headless, these tests instead
verify the mechanics that would matter if it could: synthesis produces a
valid, correctly-sized buffer for whatever format the mixer actually
initialized with; caching and the enabled/disabled gate behave correctly
(the gate via a monkeypatched pygame.mixer.Sound.play spy, not by relying
on any real audio-device behavior); a real on-disk file is loaded instead
of being synthesized; and an unrecognized mixer format degrades synthesis
gracefully rather than crashing or guessing.

This module opens the real pygame mixer, so it forces the SDL dummy video
(needed by pygame.init() itself) and audio driver before pygame is ever
touched -- same reasoning test_assets.py already documents for itself,
and for the same reason: this file collects before test_game.py
alphabetically, so it can't rely on conftest.py/that module's own
os.environ.setdefault() having already run.
"""

import os
import random
import tempfile
import wave

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

import audio
from audio import (
    DEFAULT_ASSET_ROOT,
    SOUND_MANIFEST,
    SoundManager,
    SynthSpec,
)

MISSING_ASSET_ROOT = "/nonexistent/path/for/tests/xyz"


@pytest.fixture(autouse=True)
def _mixer_initialized():
    """Every test in this module wants a real, known mixer format to
    synthesize against unless it says otherwise -- initialize once per
    test and always tear down, so one test's pygame.mixer.quit()/format
    override (see the tests that need one) can never leak into the next."""
    pygame.mixer.init(frequency=44100, size=-16, channels=2)
    yield
    pygame.mixer.quit()


def make_manager(**kwargs):
    kwargs.setdefault("asset_root", MISSING_ASSET_ROOT)
    return SoundManager(**kwargs)


def test_unknown_logical_name_raises_key_error():
    manager = make_manager()
    with pytest.raises(KeyError):
        manager.get("not_a_real_sound")


def test_get_caches_and_returns_the_same_sound_object():
    manager = make_manager()
    first = manager.get("tower_placed")
    second = manager.get("tower_placed")
    assert first is second


def test_different_logical_names_are_cached_separately():
    manager = make_manager()
    placed = manager.get("tower_placed")
    sold = manager.get("tower_sold")
    assert placed is not sold


def test_every_manifest_entry_can_be_synthesized_without_crashing():
    manager = make_manager()
    for name in SOUND_MANIFEST:
        sound = manager.get(name)
        assert isinstance(sound, pygame.mixer.Sound), name


def test_synthesized_buffer_length_matches_the_actual_mixer_format():
    # A single-note, known-duration cue -- the raw byte length should be
    # exactly sample_count * bytes_per_sample * channels for the mixer's
    # actual initialized format (44100/16-bit/stereo, per the fixture).
    manager = make_manager()
    sound = manager.get("tower_fire_default")
    (spec,) = SOUND_MANIFEST["tower_fire_default"][1]
    frequency, size, channels = pygame.mixer.get_init()
    expected_samples = round(spec.duration * frequency)
    bytes_per_sample = abs(size) // 8
    assert len(sound.get_raw()) == expected_samples * bytes_per_sample * channels


def test_every_manifest_entry_has_a_valid_synth_spec_sequence():
    for name, (path, spec_sequence) in SOUND_MANIFEST.items():
        assert len(spec_sequence) >= 1, name
        for spec in spec_sequence:
            assert spec.waveform in ("sine", "square", "triangle", "noise"), name
            assert spec.duration > 0, name
            assert spec.volume > 0, name


def test_real_file_on_disk_is_loaded_instead_of_synthesized():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "sfx"))
        real_path = os.path.join(tmpdir, "sfx", "tower_placed.wav")
        with wave.open(real_path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(44100)
            f.writeframes(b"\x00\x01" * 500)  # arbitrary, just non-empty PCM

        manager = SoundManager(asset_root=tmpdir)
        real_sound = manager.get("tower_placed")

        synthesized = make_manager().get("tower_placed")
        assert len(real_sound.get_raw()) != len(synthesized.get_raw())


class _FakeSound:
    """A pygame.mixer.Sound stand-in -- the real class is an immutable C
    extension type, so its own play() can't be monkeypatched directly;
    patching SoundManager.get() to return one of these instead tests
    play()'s own gating logic (falsy name / disabled / mixer not ready)
    without needing to touch pygame's Sound internals at all."""

    def __init__(self):
        self.play_count = 0

    def play(self):
        self.play_count += 1


def test_play_is_a_noop_for_a_falsy_logical_name(monkeypatch):
    manager = make_manager()
    get_calls = []
    monkeypatch.setattr(manager, "get", lambda name: get_calls.append(name))
    manager.play(None)
    manager.play("")
    assert get_calls == []  # never even looked the sound up


def test_play_does_nothing_while_disabled(monkeypatch):
    manager = make_manager(enabled=False)
    fake = _FakeSound()
    monkeypatch.setattr(manager, "get", lambda name: fake)
    manager.play("tower_placed")
    assert fake.play_count == 0


def test_play_calls_sound_play_once_enabled(monkeypatch):
    manager = make_manager(enabled=False)
    fake = _FakeSound()
    monkeypatch.setattr(manager, "get", lambda name: fake)
    manager.play("tower_placed")
    manager.set_enabled(True)
    manager.play("tower_placed")
    assert fake.play_count == 1


# --- Volume ---


def test_sound_manager_defaults_to_full_volume():
    assert make_manager().volume == 1.0


def test_sound_manager_accepts_a_custom_initial_volume():
    assert make_manager(volume=0.4).volume == 0.4


def test_sound_manager_clamps_an_out_of_range_initial_volume():
    assert make_manager(volume=5).volume == 1.0
    assert make_manager(volume=-5).volume == 0.0


def test_set_volume_clamps_to_the_valid_range():
    manager = make_manager()
    manager.set_volume(5)
    assert manager.volume == 1.0
    manager.set_volume(-5)
    assert manager.volume == 0.0


def test_get_applies_the_current_volume_to_a_newly_synthesized_sound():
    # abs=0.01, not the default relative tolerance -- SDL_mixer quantizes
    # a Sound's volume to its own internal 0-128 fixed-point scale, so
    # get_volume() echoes back the nearest representable step (0.3 ->
    # 0.296875 here), not the exact float that was set.
    manager = make_manager(volume=0.3)
    sound = manager.get("tower_placed")
    assert sound.get_volume() == pytest.approx(0.3, abs=0.01)


def test_set_volume_reapplies_to_an_already_cached_sound():
    manager = make_manager()
    sound = manager.get("tower_placed")  # cached at the default volume, 1.0
    manager.set_volume(0.25)
    assert sound.get_volume() == pytest.approx(0.25, abs=0.01)


@pytest.mark.parametrize("requested_format", [
    (44100, -16, 2),
    (22050, 16, 1),
    (48000, 32, 2),
    (11025, -8, 1),
])
def test_synthesis_is_robust_across_plausible_mixer_formats(requested_format):
    # Actually re-initializes the real (dummy-driver) mixer to each format,
    # rather than just monkeypatching get_init() -- pygame.mixer.Sound(
    # buffer=...) validates the buffer against the *actual* initialized
    # format, so a merely-faked get_init() would let a real mismatch (e.g.
    # a mono buffer handed to a stereo-initialized mixer) pass silently.
    frequency, size, channels = requested_format
    pygame.mixer.quit()
    pygame.mixer.init(frequency=frequency, size=size, channels=channels)
    actual_frequency, actual_size, actual_channels = pygame.mixer.get_init()

    manager = make_manager()
    sound = manager.get("tower_placed")
    assert isinstance(sound, pygame.mixer.Sound)

    total_duration = sum(spec.duration for spec in SOUND_MANIFEST["tower_placed"][1])
    expected_samples = sum(
        round(spec.duration * actual_frequency) for spec in SOUND_MANIFEST["tower_placed"][1]
    )
    bytes_per_sample = abs(actual_size) // 8
    assert len(sound.get_raw()) == expected_samples * bytes_per_sample * actual_channels
    assert total_duration > 0  # sanity: the manifest entry isn't accidentally empty


def test_unrecognized_mixer_format_disables_synthesis_only(monkeypatch):
    # 24-bit isn't one of the documented pygame.mixer size values (8/-8/
    # 16/-16/32) -- synthesis should degrade gracefully rather than crash
    # or silently guess a wrong encoding.
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: (44100, 24, 2))
    manager = make_manager()
    assert manager._encoder is None
    assert manager.get("tower_placed") is None
    manager.play("tower_placed")  # must not raise


def test_uninitialized_mixer_disables_playback_without_crashing(monkeypatch):
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    manager = make_manager()
    assert manager.mixer_ready is False
    manager.play("tower_placed")  # must not raise


def test_synth_spec_supports_a_frequency_sweep_without_crashing():
    manager = make_manager()
    (spec,) = SOUND_MANIFEST["tower_fire_zap"][1]
    assert isinstance(spec.frequency, tuple)
    assert isinstance(manager.get("tower_fire_zap"), pygame.mixer.Sound)


def test_unknown_waveform_raises_value_error():
    frequency, _size, _channels = pygame.mixer.get_init()
    with pytest.raises(ValueError):
        audio._render_note(SynthSpec("triwave", duration=0.01), frequency, random.Random(0))


def test_num_channels_is_raised_above_sdl_mixers_default_of_eight():
    assert audio.NUM_CHANNELS > 8


def test_constructing_a_sound_manager_actually_raises_the_real_mixer_channel_count():
    # Not just that the constant is bigger than SDL's default (see above)
    # -- that __init__ actually applies it to the real mixer, since every
    # SoundManager is supposed to get this fix regardless of construction
    # path (Game.__init__, a test, ...) rather than relying on a caller to
    # remember a separate set_num_channels() call.
    assert pygame.mixer.get_num_channels() != audio.NUM_CHANNELS  # sanity: still SDL's own default
    make_manager()
    assert pygame.mixer.get_num_channels() == audio.NUM_CHANNELS


def test_construction_alone_does_not_preload_anything():
    # Deliberately lazy by default -- only main.py's own real launch opts
    # into preload_all() explicitly (see its own docstring for why baking
    # this into __init__ would make every test's Game() construction pay
    # the full manifest-wide synthesis cost too).
    manager = make_manager()
    assert manager._cache == {}


def test_preload_all_populates_the_cache_for_every_manifest_entry():
    manager = make_manager()
    manager.preload_all()
    assert set(manager._cache.keys()) == set(SOUND_MANIFEST.keys())


def test_preload_all_is_a_noop_when_the_mixer_never_came_up(monkeypatch):
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    manager = make_manager()
    manager.preload_all()  # must not raise
    assert manager._cache == {}


# --- DEFAULT_ASSET_ROOT (a packaged build's launch-cwd independence) ---

def test_default_asset_root_is_anchored_to_the_assets_folder_not_a_bare_relative_path():
    assert DEFAULT_ASSET_ROOT == os.path.join(os.path.dirname(os.path.abspath(audio.__file__)), "assets")
    assert os.path.isabs(DEFAULT_ASSET_ROOT)


def test_default_asset_root_is_reused_from_assets_py_not_recomputed():
    import assets as assets_module
    assert audio.DEFAULT_ASSET_ROOT is assets_module.DEFAULT_ASSET_ROOT


def test_sound_manager_with_no_args_defaults_to_default_asset_root():
    manager = SoundManager()
    assert manager.asset_root == DEFAULT_ASSET_ROOT
