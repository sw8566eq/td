"""The Barricade -- a path structure that holds ground enemies until their
battering breaks it (Game._hold_enemies_at_barricades)."""

import pygame
import pytest
from conftest import start_first_floor

from core import game as game_module
from entities.enemy import BossEnemy, FlyingEnemy, GruntEnemy
from entities.tower import TOWER_TYPES, BarricadeTower
from persistence import save_state


def _barricade(game):
    run = start_first_floor(game, seed=1)
    run.unlocked_towers.append("barricade")
    game._rebuild_button_rects()
    game.selected_tower_name = "barricade"
    game.economy.gold = 1000
    for tile in sorted(game.grid.path_cells):
        center = game.grid.tile_to_pixel_center(*tile)
        if game.try_place_tower(*game.placement_anchor_at(*center, BarricadeTower)):
            return game.towers[-1]
    raise AssertionError("no path tile")


def _enemy_on(barricade, cls=GruntEnemy):
    enemy = cls([pygame.Vector2(barricade.pos), pygame.Vector2(barricade.pos.x + 500, barricade.pos.y)],
                wave_number=1)
    enemy.pos = pygame.Vector2(barricade.pos)
    return enemy


def test_a_barricade_holds_ground_enemies_and_takes_damage(game):
    barricade = _barricade(game)
    grunt = _enemy_on(barricade)
    game.enemies = [grunt]
    game.update(dt=1.0)
    assert grunt.held and grunt.pos == barricade.pos  # didn't move
    assert barricade.hp == pytest.approx(barricade.max_hp - game_module.BARRICADE_BREACH_DPS)
    assert grunt.hp == pytest.approx(grunt.max_hp - barricade.thorns_dps)


def test_flyers_pass_and_bosses_hit_harder(game):
    barricade = _barricade(game)
    flyer = _enemy_on(barricade, FlyingEnemy)
    game.enemies = [flyer]
    game.update(dt=0.5)
    assert not flyer.held and barricade.hp == barricade.max_hp
    boss = _enemy_on(barricade, BossEnemy)
    game.enemies = [boss]
    game.update(dt=1.0)
    expected = game_module.BARRICADE_BREACH_DPS * BossEnemy.BREACH_MULTIPLIER
    assert barricade.hp == pytest.approx(barricade.max_hp - expected)


def test_a_broken_barricade_is_removed_and_frees_its_tile(game):
    barricade = _barricade(game)
    game.selected_tower = barricade
    barricade.hp = 0.1
    game.enemies = [_enemy_on(barricade)]
    game.update(dt=1.0)
    assert barricade not in game.towers and barricade in game.sold_towers
    assert game.selected_tower is None
    assert not game.grid.is_occupied(barricade.anchor_col, barricade.anchor_row)
    game.update(dt=0.1)
    assert not game.enemies[0].held  # free to move on


def test_upgrading_repairs_and_raises_max_hp():
    barricade = BarricadeTower(0, 0, pygame.Vector2(0, 0))
    barricade.hp = 5
    assert barricade.upgrade()
    assert barricade.max_hp == pytest.approx(BarricadeTower.max_hp * 1.6) and barricade.hp == barricade.max_hp
    barricade.upgrade()
    barricade.hp = 1
    assert barricade.specialize("spiked")
    assert barricade.hp == barricade.max_hp and barricade.thorns_dps == pytest.approx(6.0)


def test_veterancy_makes_barricades_sturdier():
    barricade = BarricadeTower(0, 0, pygame.Vector2(0, 0))
    barricade.apply_veterancy(2)
    assert barricade.max_hp == pytest.approx(BarricadeTower.max_hp * 1.12) and barricade.hp == barricade.max_hp
    assert barricade.veterancy_damage_bonus == 0.0
    assert barricade.upgrade() and barricade.max_hp == pytest.approx(BarricadeTower.max_hp * 1.12 * 1.6)


def test_barricade_hp_survives_a_save(game):
    barricade = _barricade(game)
    barricade.hp = 33.0
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    restored = next(t for t in game.towers if isinstance(t, BarricadeTower))
    assert restored.hp == 33.0


def test_barricade_never_fires_and_draws_its_bar(game):
    barricade = _barricade(game)
    projectiles = []
    barricade.update(1.0, [_enemy_on(barricade)], projectiles)
    assert projectiles == []
    with pytest.raises(NotImplementedError):
        barricade.create_projectile(None)
    game.selected_tower = barricade
    game.render()
    assert not TOWER_TYPES["barricade"].ATTACKS


# --- Construction relics ---


def _run_with(game, relic_keys):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"], relics=list(relic_keys))
    game._enter_node("0-0")
    run.unlocked_towers += ["barricade", "mortar"]
    game._rebuild_button_rects()
    game.economy.gold = 5000
    return run


def _build(game, name):
    from conftest import find_buildable_anchor

    game.selected_tower_name = name
    cls = TOWER_TYPES[name]
    if cls.PLACEMENT == "path":
        for tile in sorted(game.grid.path_cells):
            if game.try_place_tower(*game.placement_anchor_at(*game.grid.tile_to_pixel_center(*tile), cls)):
                return game.towers[-1]
    assert game.try_place_tower(*find_buildable_anchor(game))
    return game.towers[-1]


def test_earthworks_toughens_barricades(game):
    _run_with(game, ["earthworks"])
    barricade = _build(game, "barricade")
    assert barricade.max_hp == pytest.approx(BarricadeTower.max_hp * 1.5) and barricade.hp == barricade.max_hp
    assert barricade.upgrade() and barricade.max_hp == pytest.approx(BarricadeTower.max_hp * 1.5 * 1.6)


def test_forward_observer_halves_the_dead_zone_only(game):
    from entities.tower import MortarTower

    _run_with(game, ["forward_observer"])
    assert _build(game, "mortar").MIN_RANGE == pytest.approx(MortarTower.MIN_RANGE / 2)
    assert _build(game, "basic").MIN_RANGE == 0
    assert MortarTower.MIN_RANGE == 80  # the class itself is untouched


def test_quick_release_mounts_needs_a_module(game):
    run = _run_with(game, ["quick_release_mounts"])
    plain = _build(game, "basic").effective_fire_rate()
    run.tower_modules["basic"] = "long_barrel"
    assert _build(game, "basic").effective_fire_rate() == pytest.approx(plain * 1.10)


def test_ambush_makes_held_enemies_take_more_damage(game):
    run = _run_with(game, ["ambush"])
    barricade = _build(game, "barricade")
    held, free = _enemy_on(barricade), GruntEnemy([pygame.Vector2(0, 0), pygame.Vector2(10, 0)], wave_number=1)
    game.enemies = [held, free]
    game._hold_enemies_at_barricades(0.0)
    assert held.held_damage_multiplier == pytest.approx(1.25) and free.held_damage_multiplier == 1.0
    before = held.hp
    held.take_damage(10)
    assert before - held.hp == pytest.approx(12.5)
    run.relics.remove("ambush")
    game._hold_enemies_at_barricades(0.0)
    assert held.held_damage_multiplier == 1.0
