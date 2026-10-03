"""Resonances (entities.tower.RESONANCES): named bonuses a tower gets with
a partner-type tower within RESONANCE_RADIUS."""

import pygame
import pytest

from entities.tower import RESONANCE_RADIUS, RESONANCES, TOWER_TYPES


def _tower(name, x):
    return TOWER_TYPES[name](0, 0, pygame.Vector2(x, 0))


def test_every_resonance_names_real_towers():
    for key, resonance in RESONANCES.items():
        assert resonance.tower in TOWER_TYPES and resonance.partner in TOWER_TYPES, key
        assert resonance.tower != resonance.partner
        assert resonance.damage_bonus or resonance.range_bonus or resonance.fire_rate_bonus


def test_superconductor_needs_a_frost_tower_in_reach():
    lightning = _tower("lightning", 0)
    base = lightning.effective_damage()
    lightning.set_nearby_tower_bonus([lightning, _tower("frost", RESONANCE_RADIUS + 5)])
    assert lightning.resonance_keys == []
    lightning.set_nearby_tower_bonus([lightning, _tower("frost", RESONANCE_RADIUS - 5)])
    assert lightning.resonance_keys == ["superconductor"]
    assert lightning.effective_damage() == pytest.approx(base + lightning.damage * 0.25)


def test_resonances_are_one_directional():
    frost, lightning = _tower("frost", 0), _tower("lightning", 10)
    frost.set_nearby_tower_bonus([frost, lightning])
    assert frost.resonance_keys == []


def test_range_and_fire_rate_resonances():
    sniper = _tower("sniper", 0)
    base_range = sniper.effective_range()
    sniper.set_nearby_tower_bonus([sniper, _tower("beacon", 20)])
    assert sniper.effective_range() == pytest.approx(base_range * 1.2)
    spike = _tower("spike_trap", 0)
    base_rate = spike.effective_fire_rate()
    spike.set_nearby_tower_bonus([spike, _tower("tar_pit", 30)])
    assert spike.effective_fire_rate() == pytest.approx(base_rate * 1.25)


def test_resonance_panel_lines():
    from presentation import ui

    assert ui.resonance_line(TOWER_TYPES["lightning"]) == "Pairs with: Frost"
    assert ui.resonance_line(TOWER_TYPES["barricade"]) == "Boosts: Mortar"
    assert ui.resonance_line(TOWER_TYPES["support"]) is None
    lightning = _tower("lightning", 0)
    assert ui.resonance_line(lightning) is None
    lightning.set_nearby_tower_bonus([lightning, _tower("frost", 10)])
    assert ui.resonance_line(lightning) == "Resonance: Superconductor"
    assert ui.resonance_line(None) is None


def test_resonance_updates_when_a_partner_is_sold(game):
    from conftest import start_first_floor

    start_first_floor(game, seed=1)
    run = game.active_run
    run.unlocked_towers += ["lightning", "frost"]
    game._rebuild_button_rects()
    game.economy.gold = 1000
    step = game.grid.subtiles_per_tile
    spots = sorted((c, r) for c in range(0, game.grid.sub_cols, step) for r in range(0, game.grid.sub_rows, step)
                   if game.grid.is_buildable(c, r))
    game.selected_tower_name = "lightning"
    assert game.try_place_tower(*spots[0])
    lightning = game.towers[-1]
    game.selected_tower_name = "frost"
    frost_spot = next(s for s in spots[1:] if game.grid.anchor_to_pixel_center(*s).distance_to(lightning.pos) <= RESONANCE_RADIUS)
    assert game.try_place_tower(*frost_spot)
    assert lightning.resonance_keys == ["superconductor"]
    game.try_sell_tower(game.towers[-1])
    assert lightning.resonance_keys == []
    game.selected_tower = lightning
    game.render()


def test_resonance_partners_work_both_ways_and_respect_reach():
    from entities.tower import resonance_partners

    lightning, far_lightning, basic = _tower("lightning", 50), _tower("lightning", 500), _tower("basic", 40)
    partners = resonance_partners("frost", pygame.Vector2(0, 0), [lightning, far_lightning, basic])
    assert partners == [lightning]  # Frost is Lightning's partner; out-of-reach and unrelated ones excluded


def test_harmonic_tuning_doubles_resonances(game):
    from test_barricade import _build, _run_with

    run = _run_with(game, ["harmonic_tuning"])
    run.unlocked_towers += ["lightning", "frost"]
    game._rebuild_button_rects()
    lightning = _build(game, "lightning")
    assert lightning.relic_resonance_multiplier == 2.0
    lightning.set_nearby_tower_bonus([lightning, _tower("frost", lightning.pos.x)])
    assert lightning.resonance_damage_bonus == pytest.approx(0.5)


def test_placement_preview_draws_resonance_links(game):
    from conftest import clear_mouse_mock, mock_mouse_pos, start_first_floor

    start_first_floor(game, seed=1)
    game.active_run.unlocked_towers += ["lightning"]
    game._rebuild_button_rects()
    game.economy.gold = 1000
    game.selected_tower_name = "lightning"
    step = game.grid.subtiles_per_tile
    spot = next((c, r) for r in range(0, game.grid.sub_rows, step) for c in range(0, game.grid.sub_cols, step)
                if game.grid.is_buildable(c, r))
    assert game.try_place_tower(*spot)
    game.selected_tower_name = "frost"
    try:
        mock_mouse_pos(tuple(game.towers[0].pos + pygame.Vector2(0, 70)))
        game.render()
    finally:
        clear_mouse_mock()


def test_active_resonances_feed_the_harmonist_counter(game):
    from conftest import start_first_floor

    from progression import achievements

    start_first_floor(game, seed=1)
    run = game.active_run
    run.unlocked_towers += ["lightning"]
    game._rebuild_button_rects()
    game.economy.gold = 1000
    step = game.grid.subtiles_per_tile
    spots = sorted((c, r) for c in range(0, game.grid.sub_cols, step) for r in range(0, game.grid.sub_rows, step)
                   if game.grid.is_buildable(c, r))
    game.selected_tower_name = "lightning"
    assert game.try_place_tower(*spots[0])
    lightning = game.towers[-1]
    game.selected_tower_name = "frost"
    frost_spot = next(s for s in spots[1:] if game.grid.anchor_to_pixel_center(*s).distance_to(lightning.pos)
                      <= RESONANCE_RADIUS)
    assert game.try_place_tower(*frost_spot)
    counters = achievements.load_achievements(game.achievements_path)["counters"]
    assert counters["resonances_active"] == 1


def test_v_toggles_the_coverage_overlay(game):
    from conftest import start_first_floor

    start_first_floor(game, seed=1)
    run = game.active_run
    run.unlocked_towers += ["lightning", "mortar"]
    game._rebuild_button_rects()
    game.economy.gold = 2000
    step = game.grid.subtiles_per_tile
    spots = sorted((c, r) for c in range(0, game.grid.sub_cols, step) for r in range(0, game.grid.sub_rows, step)
                   if game.grid.is_buildable(c, r))
    for name, spot in zip(("lightning", "frost", "mortar"), spots, strict=False):
        game.selected_tower_name = name
        game.try_place_tower(*spot)
    assert not game.show_coverage
    game._handle_keydown(pygame.K_v)
    assert game.show_coverage
    game.render()
    game._handle_keydown(pygame.K_v)
    assert not game.show_coverage


def test_a_resonance_is_announced_once_per_floor(game):
    from conftest import start_first_floor

    start_first_floor(game, seed=1)
    game.active_run.unlocked_towers += ["lightning"]
    game._rebuild_button_rects()
    game.economy.gold = 2000
    step = game.grid.subtiles_per_tile
    spots = sorted((c, r) for c in range(0, game.grid.sub_cols, step) for r in range(0, game.grid.sub_rows, step)
                   if game.grid.is_buildable(c, r))
    game.selected_tower_name = "lightning"
    assert game.try_place_tower(*spots[0])
    lightning = game.towers[-1]
    near = [s for s in spots[1:] if game.grid.anchor_to_pixel_center(*s).distance_to(lightning.pos) <= RESONANCE_RADIUS]
    game.selected_tower_name = "frost"
    for spot in near[:2]:
        game.try_place_tower(*spot)
    toasts = [toast.text for toast in game.achievement_toasts if "Resonance" in toast.text]
    assert toasts == ["Resonance: Superconductor!"]
