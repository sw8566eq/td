"""Tests for AssetManager.

Deliberately points every fallback-path test at a nonexistent asset_root
(never the project's real assets/ folder) so results stay the same no
matter what real art has or hasn't been dropped into assets/ locally --
these tests must not become flaky just because someone's mid-way through
adding a sprite pack.
"""

import os
import tempfile

import pygame
import pytest

from assets import SPRITE_MANIFEST, AssetManager

MISSING_ASSET_ROOT = "/nonexistent/path/for/tests/xyz"


def make_manager():
    return AssetManager(asset_root=MISSING_ASSET_ROOT)


def test_unknown_logical_name_raises_key_error():
    manager = make_manager()
    with pytest.raises(KeyError):
        manager.get("not_a_real_sprite")


def test_missing_file_falls_back_to_a_placeholder_of_the_requested_size():
    manager = make_manager()
    surface = manager.get("enemy_grunt", (40, 60))
    assert surface.get_size() == (40, 60)


def test_missing_file_falls_back_to_default_size_when_none_given():
    manager = make_manager()
    surface = manager.get("enemy_grunt")
    assert surface.get_size() == (48, 48)


def test_get_caches_and_returns_the_same_surface_object():
    manager = make_manager()
    first = manager.get("tower_basic", (32, 32))
    second = manager.get("tower_basic", (32, 32))
    assert first is second


def test_different_sizes_are_cached_separately():
    manager = make_manager()
    small = manager.get("tower_basic", (16, 16))
    large = manager.get("tower_basic", (64, 64))
    assert small is not large
    assert small.get_size() == (16, 16)
    assert large.get_size() == (64, 64)


def test_different_logical_names_are_cached_separately():
    manager = make_manager()
    grunt = manager.get("enemy_grunt", (32, 32))
    scout = manager.get("enemy_scout", (32, 32))
    assert grunt is not scout


def test_circle_placeholder_center_pixel_matches_the_manifest_fallback_color():
    manager = make_manager()
    _, fallback_color, shape = SPRITE_MANIFEST["enemy_grunt"]
    assert shape == "circle"
    surface = manager.get("enemy_grunt", (30, 30))
    assert surface.get_at((15, 15))[:3] == fallback_color


def test_rect_placeholder_interior_pixel_matches_the_manifest_fallback_color():
    manager = make_manager()
    _, fallback_color, shape = SPRITE_MANIFEST["tower_basic"]
    assert shape == "rect"
    surface = manager.get("tower_basic", (30, 30))
    assert surface.get_at((15, 15))[:3] == fallback_color


def test_placeholder_has_transparent_corners_outside_the_drawn_shape():
    # SRCALPHA background is fully transparent -- a circle placeholder
    # shouldn't paint over its corners.
    manager = make_manager()
    surface = manager.get("enemy_grunt", (30, 30))
    assert surface.get_at((0, 0))[3] == 0  # alpha channel


def test_every_manifest_entry_has_a_valid_shape():
    for name, (path, color, shape) in SPRITE_MANIFEST.items():
        assert shape in ("circle", "rect"), name


def test_every_manifest_entry_has_a_valid_fallback_color():
    for name, (path, color, shape) in SPRITE_MANIFEST.items():
        assert len(color) == 3, name
        assert all(0 <= channel <= 255 for channel in color), name


def test_every_manifest_entry_can_be_loaded_as_a_placeholder():
    manager = make_manager()
    for name in SPRITE_MANIFEST:
        surface = manager.get(name, (20, 20))
        assert surface.get_size() == (20, 20), name


def test_small_circle_placeholder_is_plain_with_no_outline():
    # Below the "plain" threshold (short_side < 12), a circle placeholder
    # skips the outline stroke entirely -- not enough pixels left for one
    # without the shape collapsing into a dot (see _make_placeholder).
    manager = make_manager()
    _, fallback_color, shape = SPRITE_MANIFEST["enemy_grunt"]
    assert shape == "circle"

    surface = manager.get("enemy_grunt", (10, 10))

    assert surface.get_at((5, 5))[:3] == fallback_color  # plain fill, no lighter outline ring


def test_real_file_on_disk_with_no_requested_size_keeps_the_original_size():
    pygame.init()
    pygame.display.set_mode((10, 10))
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "enemies"))
            source = pygame.Surface((20, 20), pygame.SRCALPHA)
            pygame.draw.circle(source, (10, 20, 30, 255), (10, 10), 9)
            pygame.image.save(source, os.path.join(tmpdir, "enemies", "grunt.png"))

            manager = AssetManager(asset_root=tmpdir)
            surface = manager.get("enemy_grunt")  # no size -- never scaled

            assert surface.get_size() == (20, 20)  # the real file's own size, untouched
    finally:
        pygame.quit()


def test_real_file_on_disk_is_loaded_and_scaled_instead_of_the_placeholder():
    pygame.init()
    pygame.display.set_mode((10, 10))
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "enemies"))
            source = pygame.Surface((20, 20), pygame.SRCALPHA)
            pygame.draw.circle(source, (10, 20, 30, 255), (10, 10), 9)
            pygame.image.save(source, os.path.join(tmpdir, "enemies", "grunt.png"))

            manager = AssetManager(asset_root=tmpdir)
            surface = manager.get("enemy_grunt", (40, 40))

            assert surface.get_size() == (40, 40)  # scaled, not the source's 20x20
            # Center pixel should be the real file's color, not the
            # fallback color from SPRITE_MANIFEST.
            assert surface.get_at((20, 20))[:3] == (10, 20, 30)
    finally:
        pygame.quit()
