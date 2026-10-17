"""The Accessibility screen: the Colorblind palette (support/palette.py) and
Reduce effects. See docs/agents/presentation.md "Accessibility: palettes and
reduced effects"."""

import pygame
import pytest
from conftest import make_game

from core.game import GameState
from entities import effects
from entities.effects import ExpandingRing, FloatingText
from entities.enemy import ENEMY_TYPES
from entities.tower import TOWER_TYPES
from persistence import player_settings
from presentation import ui
from run.run_map import NODE_TYPES
from support import palette, settings


@pytest.fixture(autouse=True)
def _restore_default_palette():
    yield
    palette.set_active(palette.DEFAULT_PALETTE)


# --- support/palette.py ---


def test_default_palette_matches_the_settings_constants():
    colors = palette.PALETTES["default"]
    assert colors.footprint_valid == settings.COLOR_FOOTPRINT_VALID
    assert colors.footprint_invalid == settings.COLOR_FOOTPRINT_INVALID
    assert colors.danger == settings.COLOR_LIVES
    assert colors.hp_bar_bg == settings.COLOR_ENEMY_HP_BAR_BG
    assert colors.hp_bar_fill == settings.COLOR_ENEMY_HP_BAR_FILL
    assert colors.enrage_ring == settings.COLOR_ENEMY_ENRAGE_RING
    assert colors.node_colors["boss"] == settings.COLOR_NODE_BOSS
    assert colors.node_locked == settings.COLOR_NODE_LOCKED


def test_every_palette_defines_the_same_node_types_as_the_run_map():
    for colors in palette.PALETTES.values():
        assert set(colors.node_colors) == set(NODE_TYPES)


def test_every_palette_color_is_a_hashable_rgb_tuple():
    # Render cache keys hold these (see presentation.md "Render caches").
    for colors in palette.PALETTES.values():
        values = [colors.footprint_valid, colors.footprint_invalid, colors.danger, colors.hp_bar_bg,
                  colors.hp_bar_fill, colors.armor_ring, colors.enrage_ring, colors.challenge_status,
                  colors.node_locked, *colors.node_colors.values()]
        for value in values:
            assert isinstance(value, tuple) and len(value) == 3
            hash(value)


def test_colorblind_palette_swaps_the_red_green_pairs():
    default, colorblind = palette.PALETTES["default"], palette.PALETTES["colorblind"]
    assert colorblind.footprint_invalid != default.footprint_invalid
    assert colorblind.hp_bar_fill != default.hp_bar_fill
    assert colorblind.danger != default.danger
    assert colorblind.node_colors["rest"] != default.node_colors["rest"]


def test_set_active_switches_lookups_and_rejects_unknown_keys():
    assert palette.active_key() == "default"
    assert palette.set_active("colorblind") is True
    assert palette.active() is palette.PALETTES["colorblind"]
    assert palette.node_color("shop") == palette.PALETTES["colorblind"].node_colors["shop"]
    assert palette.set_active("neon") is False
    assert palette.active_key() == "colorblind"


def test_is_light_flags_only_bright_fills():
    assert palette.is_light((235, 235, 235))
    assert palette.is_light((240, 228, 66))
    assert not palette.is_light((15, 15, 15))
    for color in palette.PALETTES["default"].node_colors.values():
        assert not palette.is_light(color)  # default map labels stay white


# --- Game: toggles, persistence, the screen ---


def test_a_fresh_game_uses_the_default_palette_and_full_effects(game):
    assert game.palette == "default"
    assert game.reduce_effects is False
    assert palette.active_key() == "default"


def test_toggle_colorblind_palette_switches_and_persists(game):
    game.toggle_colorblind_palette()
    assert game.palette == "colorblind"
    assert palette.active_key() == "colorblind"
    assert player_settings.load_settings(game.settings_path)["palette"] == "colorblind"
    game.toggle_colorblind_palette()
    assert game.palette == "default"
    assert palette.active_key() == "default"


def test_set_palette_ignores_an_unknown_key(game):
    game.set_palette("neon")
    assert game.palette == "default"
    assert not game.settings_path.exists()


def test_reduce_effects_persists(game):
    game.set_reduce_effects(True)
    assert game.reduce_effects is True
    assert player_settings.load_settings(game.settings_path)["reduce_effects"] is True


def test_a_fresh_game_restores_the_saved_accessibility_settings(tmp_path):
    first = make_game(tmp_path)
    try:
        first.set_palette("colorblind")
        first.set_reduce_effects(True)
        palette.set_active("default")  # as if the process restarted
    finally:
        pygame.quit()

    second = make_game(tmp_path)
    try:
        assert second.palette == "colorblind"
        assert palette.active_key() == "colorblind"
        assert second.reduce_effects is True
    finally:
        pygame.quit()


def test_settings_accessibility_button_opens_the_screen(game):
    game.state = GameState.SETTINGS
    game._handle_settings_click(game.accessibility_entry_button_rect.center)
    assert game.state == GameState.ACCESSIBILITY


def test_accessibility_entry_button_does_not_overlap_other_settings_buttons(game):
    others = [*game.settings_rects.values(), *game.volume_button_rects.values(),
              *game.hint_settings_rects.values(), game.keybinds_entry_button_rect]
    assert not any(game.accessibility_entry_button_rect.colliderect(rect) for rect in others)
    assert game.screen.get_rect().contains(game.accessibility_entry_button_rect)


def test_accessibility_clicks_toggle_each_option_and_back_returns_to_settings(game):
    game.state = GameState.ACCESSIBILITY
    game._handle_accessibility_click(game.accessibility_rects["colorblind"].center)
    assert game.palette == "colorblind"
    game._handle_accessibility_click(game.accessibility_rects["reduce_effects"].center)
    assert game.reduce_effects is True
    game._handle_accessibility_click((5, 5))  # off every button
    assert game.state == GameState.ACCESSIBILITY
    game._handle_accessibility_click(game.accessibility_rects["back"].center)
    assert game.state == GameState.SETTINGS


def test_accessibility_escape_returns_to_settings(game):
    game.state = GameState.ACCESSIBILITY
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.SETTINGS


def test_accessibility_click_routes_through_handle_events(game):
    game.state = GameState.ACCESSIBILITY
    pygame.event.post(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=game.accessibility_rects["colorblind"].center,
    ))
    game.handle_events()
    assert game.palette == "colorblind"


@pytest.mark.parametrize("colorblind", [False, True])
def test_accessibility_screen_renders_and_fits_on_screen(game, colorblind):
    if colorblind:
        game.set_palette("colorblind")
    game.state = GameState.ACCESSIBILITY
    game.render()
    screen = game.screen.get_rect()
    assert all(screen.contains(rect) for rect in game.accessibility_rects.values())
    # The selected (On) button is drawn in the selected color.
    pixel = game.screen.get_at(game.accessibility_rects["colorblind"].move(4, 0).midleft)[:3]
    expected = settings.COLOR_BUTTON_SELECTED if colorblind else settings.COLOR_BUTTON
    assert pixel == expected


def test_settings_screen_draws_the_accessibility_button(game):
    game.state = GameState.SETTINGS
    game.render()
    rect = game.accessibility_entry_button_rect
    assert game.screen.get_at(rect.move(4, 0).midleft)[:3] == settings.COLOR_BUTTON


# --- Palette lookups at the draw sites ---


def test_footprint_preview_uses_the_active_palette(game):
    surface = pygame.Surface((200, 200))
    palette.set_active("colorblind")
    ui.draw_footprint_preview(surface, game.grid, 0, 0, False)
    assert surface.get_at((0, 0))[:3] == palette.PALETTES["colorblind"].footprint_invalid
    ui.draw_footprint_preview(surface, game.grid, 0, 0, True)
    assert surface.get_at((0, 0))[:3] == palette.PALETTES["colorblind"].footprint_valid


def test_enemy_health_bar_uses_the_active_palette():
    enemy = ENEMY_TYPES["grunt"]([(100, 100), (300, 100)], 1)
    enemy.hp = enemy.max_hp / 2
    palette.set_active("colorblind")
    surface = pygame.Surface((400, 200))
    enemy._draw_health_bar(surface)
    colors = palette.PALETTES["colorblind"]
    bar_y = int(enemy.pos.y - enemy.radius - 4 - 2)
    left = int(enemy.pos.x - enemy.radius)
    assert surface.get_at((left, bar_y))[:3] == colors.hp_bar_fill
    assert surface.get_at((left + enemy.radius * 2 - 1, bar_y))[:3] == colors.hp_bar_bg


def test_damage_numbers_default_to_the_palette_danger_color():
    palette.set_active("colorblind")
    assert FloatingText((0, 0), "5").color == palette.PALETTES["colorblind"].danger
    assert FloatingText((0, 0), "5", color=(1, 2, 3)).color == (1, 2, 3)


def test_coverage_overlay_cache_rebuilds_when_the_palette_switches(monkeypatch):
    monkeypatch.setattr(ui, "_coverage_overlay_cache", {})
    mortar = TOWER_TYPES["mortar"](0, 0, (200, 150))
    screen = pygame.Surface((400, 300))
    ui.draw_coverage_overlay(screen, [mortar])
    layer = ui._coverage_overlay_cache["surface"]

    palette.set_active("colorblind")
    ui.draw_coverage_overlay(screen, [mortar])
    assert ui._coverage_overlay_cache["surface"] is not layer

    # The rebuilt layer draws the dead zone in the colorblind danger color.
    layer = ui._coverage_overlay_cache["surface"]
    row = {tuple(layer.get_at((x, 150)))[:3] for x in range(200, 400)}
    assert palette.PALETTES["colorblind"].danger in row
    assert palette.PALETTES["default"].danger not in row


# --- Reduce effects ---


def test_alpha_scale_dims_rings_without_reusing_a_full_strength_surface(monkeypatch):
    monkeypatch.setattr(effects, "_ring_cache", {})
    ring = ExpandingRing((40, 40), max_radius=30, duration=1.0, color=(10, 200, 30))
    ring.draw(pygame.Surface((80, 80)))
    ring.draw(pygame.Surface((80, 80)), effects.REDUCED_EFFECTS_ALPHA)
    alphas = sorted(key[3] for key in effects._ring_cache)
    assert alphas == [int(255 * effects.REDUCED_EFFECTS_ALPHA), 255]


def test_alpha_scale_dims_floating_text():
    pygame.font.init()
    font = pygame.font.SysFont(None, 16)
    text = FloatingText((40, 40), "88", color=(255, 255, 255))
    full, dim = pygame.Surface((80, 80)), pygame.Surface((80, 80))
    text.draw(full, font)
    text.draw(dim, font, effects.REDUCED_EFFECTS_ALPHA)
    brightest = max(full.get_at((x, y))[0] for x in range(80) for y in range(80))
    dimmed = max(dim.get_at((x, y))[0] for x in range(80) for y in range(80))
    assert dimmed < brightest


def test_renderer_passes_the_reduced_alpha_only_when_enabled(playing_game, monkeypatch):
    seen = []
    monkeypatch.setattr(ExpandingRing, "draw", lambda self, surface, alpha_scale=1.0: seen.append(alpha_scale))
    playing_game.impact_effects.append(ExpandingRing((100, 100), max_radius=30))
    playing_game.render()
    playing_game.set_reduce_effects(True)
    playing_game.render()
    assert seen == [1.0, effects.REDUCED_EFFECTS_ALPHA]
