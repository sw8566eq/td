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
    assert ui.resonance_line(TOWER_TYPES["frost"]) is None
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
