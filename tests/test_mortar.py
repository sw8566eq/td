"""The Mortar -- long range, a minimum-range dead zone, big splash."""

import pygame
import pytest

from entities.enemy import FlyingEnemy, GruntEnemy
from entities.tower import TOWER_TYPES, MortarTower


def _enemy_at(x, cls=GruntEnemy):
    enemy = cls([pygame.Vector2(x, 0), pygame.Vector2(x + 500, 0)], wave_number=1)
    enemy.pos = pygame.Vector2(x, 0)
    return enemy


def test_mortar_cannot_hit_inside_its_dead_zone():
    mortar = MortarTower(0, 0, pygame.Vector2(0, 0))
    near, far = _enemy_at(MortarTower.MIN_RANGE - 10), _enemy_at(MortarTower.MIN_RANGE + 50)
    assert mortar.acquire_target([near]) is None
    assert mortar.acquire_target([near, far]) is far


def test_mortar_ignores_flyers_and_splashes():
    mortar = MortarTower(0, 0, pygame.Vector2(0, 0))
    assert mortar.acquire_target([_enemy_at(150, FlyingEnemy)]) is None
    target = _enemy_at(150)
    assert mortar.create_projectile(target).splash_radius == MortarTower.splash_radius


def test_ordinary_towers_have_no_dead_zone():
    assert all(cls.MIN_RANGE == 0 for name, cls in TOWER_TYPES.items() if name != "mortar")


def test_range_previews_draw_the_dead_zone():
    from presentation import ui

    surface = pygame.Surface((400, 400))
    ui.draw_range_preview(surface, MortarTower, (200, 200))
    ui.draw_tower_range_preview(surface, MortarTower(0, 0, pygame.Vector2(200, 200)))


# --- Incendiary Shells (ground fire) ---


def _mortar_run(game, relic_keys):
    from conftest import find_buildable_anchor
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"], relics=list(relic_keys))
    game._enter_node("0-0")
    run.unlocked_towers.append("mortar")
    game._rebuild_button_rects()
    game.economy.gold = 1000
    game.selected_tower_name = "mortar"
    assert game.try_place_tower(*find_buildable_anchor(game))
    return game.towers[-1]


def test_incendiary_shells_tag_mortar_shells_only(game):
    mortar = _mortar_run(game, ["incendiary_shells"])
    target = _enemy_at(150)
    assert mortar.create_projectile(target).ground_fire == (0.3, 3.0)
    plain = _mortar_run(game, [])
    assert plain.create_projectile(target).ground_fire is None


def test_a_shell_impact_leaves_fire_that_burns_ground_enemies_and_credits_the_mortar(game):
    mortar = _mortar_run(game, ["incendiary_shells"])
    target = _enemy_at(150)
    shot = mortar.create_projectile(target)
    shot.impact_events.append((pygame.Vector2(150, 0), shot.splash_radius))
    game.projectiles = [shot]
    victim, flyer = _enemy_at(150), _enemy_at(150, FlyingEnemy)
    flyer.pos = pygame.Vector2(150, 0)
    game.enemies = [victim, flyer]
    game.update(dt=0.01)
    assert len(game.ground_fires) == 1
    fire = game.ground_fires[0]
    hp = victim.hp
    game._update_ground_fires(1.0)
    assert victim.hp == pytest.approx(hp - fire.dps * 1.0)
    assert flyer.hp == flyer.max_hp
    assert mortar.damage_dealt > 0
    victim.hp = 0.01
    game._update_ground_fires(0.5)
    assert victim.is_dead and mortar.kills == 1
    game._update_ground_fires(5.0)
    assert game.ground_fires == []


def test_ground_fires_render_and_reset_on_reload(game):
    from entities.effects import GroundFire

    _mortar_run(game, ["incendiary_shells"])
    game.ground_fires = [GroundFire(pygame.Vector2(100, 100), 40, 5.0, 3.0)]
    game.render()
    game.state = game.state.__class__.PAUSED
    game.reset()
    assert game.ground_fires == []


def test_flashpoint_doubles_ground_fire_on_slowed_enemies(game):
    from entities.effects import GroundFire

    _mortar_run(game, ["incendiary_shells", "flashpoint"])
    slowed, normal = _enemy_at(100), _enemy_at(100)
    slowed.apply_slow(0.5, 5.0)
    game.enemies = [slowed, normal]
    game.ground_fires = [GroundFire(pygame.Vector2(100, 0), 40, 10.0, 3.0)]
    game._update_ground_fires(1.0)
    assert slowed.max_hp - slowed.hp == pytest.approx(20.0)
    assert normal.max_hp - normal.hp == pytest.approx(10.0)


def test_kill_corridor_boosts_only_path_traps_vs_slowed(game):
    from test_barricade import _build, _run_with

    run = _run_with(game, ["kill_corridor"])
    run.unlocked_towers.append("spike_trap")
    game._rebuild_button_rects()
    trap = _build(game, "spike_trap")
    basic = _build(game, "basic")
    assert trap.relic_damage_vs_slowed_multiplier == pytest.approx(1.5)
    assert basic.relic_damage_vs_slowed_multiplier == pytest.approx(1.0)
