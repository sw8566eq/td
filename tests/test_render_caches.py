"""Render caches must draw exactly what an uncached draw would, and must
invalidate when their inputs change. See docs/agents/presentation.md
"Render caches"."""

import pygame

from entities import effects
from entities.effects import ExpandingRing, FloatingText
from entities.tower import TOWER_TYPES
from presentation import ui


def _font():
    pygame.font.init()
    return pygame.font.SysFont(None, 16)


def _pixels(surface):
    return pygame.image.tobytes(surface, "RGBA")


def test_floating_text_draws_the_same_pixels_as_an_uncached_render():
    font = _font()
    cached = pygame.Surface((80, 80))
    text = FloatingText((40, 40), "123", color=(220, 60, 60))
    text.update(0.3)
    text.draw(cached, font)

    reference = pygame.Surface((80, 80))
    rendered = font.render("123", True, (220, 60, 60))
    rendered.set_alpha(max(0, min(255, int(255 * (1 - text.age / text.lifetime)))))
    reference.blit(rendered, rendered.get_rect(center=(40, int(text.pos.y))))
    assert _pixels(cached) == _pixels(reference)


def test_labels_with_the_same_text_share_one_rendered_surface():
    font = _font()
    first = effects._text_entry(font, "9", (1, 2, 3))
    assert effects._text_entry(font, "9", (1, 2, 3)) is first
    assert effects._text_entry(font, "9", (3, 2, 1)) is not first


def test_text_cache_is_cleared_once_it_reaches_its_limit(monkeypatch):
    font = _font()
    monkeypatch.setattr(effects, "_text_cache", {})
    monkeypatch.setattr(effects, "_TEXT_CACHE_LIMIT", 2)
    effects._text_entry(font, "a", (0, 0, 0))
    effects._text_entry(font, "b", (0, 0, 0))
    effects._text_entry(font, "c", (0, 0, 0))
    assert list(effects._text_cache) == [(font, "c", (0, 0, 0))]


def test_expanding_ring_draws_the_same_pixels_as_an_uncached_draw():
    cached = pygame.Surface((80, 80))
    ring = ExpandingRing((40, 40), max_radius=30, duration=1.0, color=(10, 200, 30), width=2)
    ring.update(0.4)
    ring.draw(cached)

    reference = pygame.Surface((80, 80))
    radius = int(4.0 + (30 - 4.0) * 0.4)
    alpha = int(255 * 0.6)
    diameter = radius * 2 + 2
    fresh = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    pygame.draw.circle(fresh, (10, 200, 30, alpha), (diameter // 2, diameter // 2), radius, width=2)
    reference.blit(fresh, fresh.get_rect(center=(40, 40)))
    assert _pixels(cached) == _pixels(reference)


def test_ring_cache_is_cleared_once_it_reaches_its_limit(monkeypatch):
    monkeypatch.setattr(effects, "_ring_cache", {})
    monkeypatch.setattr(effects, "_RING_CACHE_LIMIT", 1)
    first = effects._ring_surface(5, 2, (1, 1, 1), 100)
    assert effects._ring_surface(5, 2, (1, 1, 1), 100) is first
    effects._ring_surface(6, 2, (1, 1, 1), 100)
    assert list(effects._ring_cache) == [(6, 2, (1, 1, 1), 100)]


def test_coverage_overlay_is_reused_until_a_ring_changes(monkeypatch):
    monkeypatch.setattr(ui, "_coverage_overlay_cache", {})
    tower = TOWER_TYPES["basic"](0, 0, (100, 100))
    mortar = TOWER_TYPES["mortar"](0, 0, (300, 200))
    screen = pygame.Surface((400, 300))

    ui.draw_coverage_overlay(screen, [tower, mortar])
    layer = ui._coverage_overlay_cache["surface"]
    ui.draw_coverage_overlay(screen, [tower, mortar])
    assert ui._coverage_overlay_cache["surface"] is layer  # nothing changed

    tower.aura_range_multiplier = 1.5  # e.g. a Support tower's buff landing
    ui.draw_coverage_overlay(screen, [tower, mortar])
    assert ui._coverage_overlay_cache["surface"] is not layer

    # And what it draws matches a from-scratch draw of the same board.
    cached = pygame.Surface((400, 300))
    ui.draw_coverage_overlay(cached, [tower, mortar])
    monkeypatch.setattr(ui, "_coverage_overlay_cache", {})
    fresh = pygame.Surface((400, 300))
    ui.draw_coverage_overlay(fresh, [tower, mortar])
    assert _pixels(cached) == _pixels(fresh)
