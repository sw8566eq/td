"""The Harpoon tower and the Grounded status (Enemy.apply_ground /
enemy.is_airborne): a grounded flyer is in reach of every ground-only
attack -- targeting, splash, traps, burning ground and Barricades."""

import json

import pygame
import pytest
from conftest import find_buildable_anchor, start_first_floor

from entities.effects import GroundFire
from entities.enemy import FlyingEnemy, GruntEnemy, is_airborne
from entities.tower import (
    RESONANCES,
    TOWER_TYPES,
    BasicTower,
    CannonTower,
    HarpoonTower,
    KnockbackTower,
    MortarTower,
    SpikeTrapTower,
    TarPitTower,
)
from persistence import save_state
from presentation import ui
from run import modules


def _enemy_at(x, cls=GruntEnemy, y=0):
    enemy = cls([pygame.Vector2(x, y), pygame.Vector2(x + 500, y)], wave_number=1)
    enemy.pos = pygame.Vector2(x, y)
    return enemy


def _grounded_flyer_at(x, y=0, duration=3.0):
    flyer = _enemy_at(x, FlyingEnemy, y)
    flyer.apply_ground(duration)
    return flyer


# --- The Grounded status ---


def test_is_airborne_is_flying_and_not_grounded():
    flyer = _enemy_at(0, FlyingEnemy)
    assert is_airborne(flyer) and not flyer.is_grounded
    flyer.apply_ground(2.0)
    assert flyer.is_grounded and not is_airborne(flyer)
    assert not is_airborne(_enemy_at(0))

    class Bare:
        pass

    stand_in = Bare()
    assert not is_airborne(stand_in)
    stand_in.is_flying = True
    assert is_airborne(stand_in)


def test_grounding_refreshes_by_max_and_wears_off():
    flyer = _enemy_at(0, FlyingEnemy)
    flyer.apply_ground(3.0)
    flyer.apply_ground(1.0)  # a shorter grounding never cuts it short
    assert flyer.ground_timer == pytest.approx(3.0)
    flyer.apply_ground(4.0)
    assert flyer.ground_timer == pytest.approx(4.0)
    flyer.update(1.5)
    assert flyer.ground_timer == pytest.approx(2.5)
    flyer.update(3.0)
    assert flyer.ground_timer == 0.0 and is_airborne(flyer)


def test_grounding_is_a_no_op_on_ground_species_and_the_dead():
    grunt = _enemy_at(0)
    grunt.apply_ground(3.0)
    assert grunt.ground_timer == 0.0 and not grunt.is_grounded
    flyer = _enemy_at(0, FlyingEnemy)
    flyer.is_dead = True
    flyer.apply_ground(3.0)
    assert flyer.ground_timer == 0.0


def test_a_grounded_flyer_still_follows_its_own_waypoints():
    plain, grounded = _enemy_at(0, FlyingEnemy), _grounded_flyer_at(0)
    for _ in range(10):
        plain.update(0.1)
        grounded.update(0.1)
    assert grounded.pos == plain.pos and grounded.wp_index == plain.wp_index


def test_ground_only_towers_target_a_grounded_flyer_but_not_an_airborne_one():
    for cls, x in ((CannonTower, 50), (KnockbackTower, 50), (MortarTower, 150),
                   (SpikeTrapTower, 10), (TarPitTower, 10)):
        tower = cls(0, 0, pygame.Vector2(0, 0))
        assert tower.acquire_target([_enemy_at(x, FlyingEnemy)]) is None, cls.__name__
        grounded = _grounded_flyer_at(x)
        assert tower.acquire_target([grounded]) is grounded, cls.__name__


def test_ground_only_splash_touches_a_grounded_flyer():
    target = _enemy_at(150)
    for cls in (CannonTower, KnockbackTower, MortarTower, SpikeTrapTower, TarPitTower):
        shot = cls(0, 0, pygame.Vector2(0, 0)).create_projectile(target)
        assert not shot._can_hit(_enemy_at(150, FlyingEnemy)), cls.__name__
        assert shot._can_hit(_grounded_flyer_at(150)), cls.__name__


def test_a_mortar_blast_damages_a_grounded_flyer_in_the_splash():
    target = _enemy_at(150)
    airborne, grounded = _enemy_at(160, FlyingEnemy), _grounded_flyer_at(160)
    shot = MortarTower(0, 0, pygame.Vector2(0, 0)).create_projectile(target)
    shot._resolve_hit(pygame.Vector2(150, 0), [target, airborne, grounded])
    assert airborne.hp == airborne.max_hp
    assert grounded.hp < grounded.max_hp


def test_burning_ground_burns_a_grounded_flyer(game):
    start_first_floor(game, seed=1)
    airborne, grounded = _enemy_at(100, FlyingEnemy), _grounded_flyer_at(100)
    game.enemies = [airborne, grounded]
    game.ground_fires = [GroundFire(pygame.Vector2(100, 0), 40, 10.0, 3.0)]
    game._update_ground_fires(1.0)
    assert airborne.hp == airborne.max_hp
    assert grounded.hp == pytest.approx(grounded.max_hp - 10.0)


def test_a_barricade_holds_a_grounded_flyer_and_its_burst_hits_one(game):
    from test_barricade import _barricade, _enemy_on

    barricade = _barricade(game)
    flyer = _enemy_on(barricade, FlyingEnemy)
    flyer.apply_ground(5.0)
    game.enemies = [flyer]
    game.update(dt=0.5)
    assert flyer.held and barricade.hp < barricade.max_hp
    grounded = _enemy_on(barricade, FlyingEnemy)
    grounded.apply_ground(5.0)
    airborne = _enemy_on(barricade, FlyingEnemy)
    game.enemies = [grounded, airborne]
    game._barricade_burst(barricade, 5.0)
    assert grounded.hp < grounded.max_hp and airborne.hp == airborne.max_hp


def test_the_tooltip_lists_grounded_and_a_grounded_flyer_draws():
    from presentation.assets import AssetManager

    grounded = _grounded_flyer_at(100, y=100)
    assert "Grounded" in ui.enemy_tooltip_lines(grounded)[-1]
    assert "Grounded" not in " ".join(ui.enemy_tooltip_lines(_enemy_at(100, FlyingEnemy)))
    grounded.draw(pygame.Surface((300, 300)), AssetManager(asset_root="/nonexistent"))


# --- The Harpoon tower ---


def test_harpoon_is_registered_and_unlockable():
    from progression import meta_progression

    assert TOWER_TYPES["harpoon"] is HarpoonTower
    assert meta_progression.META_UNLOCKS["unlock_harpoon"].tower_name == "harpoon"
    assert HarpoonTower.can_target_flying and HarpoonTower.ATTACKS


def test_a_harpoon_hit_grounds_a_flyer():
    harpoon = HarpoonTower(0, 0, pygame.Vector2(0, 0))
    flyer = _enemy_at(100, FlyingEnemy)
    shot = harpoon.create_projectile(flyer)
    assert shot.ground_duration == HarpoonTower.ground_duration and shot.slow_effect is None
    shot._resolve_hit(flyer.pos, [flyer])
    assert flyer.ground_timer == pytest.approx(HarpoonTower.ground_duration)
    assert flyer.hp < flyer.max_hp and harpoon.damage_dealt > 0
    assert CannonTower(0, 0, pygame.Vector2(0, 0)).acquire_target([flyer]) is flyer


def test_harpoon_fires_through_the_normal_loop_and_prefers_airborne_flyers():
    harpoon = HarpoonTower(0, 0, pygame.Vector2(0, 0))
    assert harpoon.targeting_mode == "flying"
    leader, flyer, grounded = _enemy_at(100), _enemy_at(60, FlyingEnemy), _grounded_flyer_at(80)
    leader.distance_traveled, flyer.distance_traveled, grounded.distance_traveled = 300, 100, 200
    assert harpoon.acquire_target([leader, flyer, grounded]) is flyer
    # No airborne flyer in range: falls back to "first".
    assert harpoon.acquire_target([leader, grounded]) is leader
    projectiles = []
    harpoon.update(0.1, [leader, flyer], projectiles)
    assert len(projectiles) == 1 and projectiles[0].target is flyer and harpoon.fired_this_frame


def test_flying_targeting_mode_is_harpoon_only_and_cycles():
    assert "flying" not in BasicTower.TARGETING_MODES
    harpoon = HarpoonTower(0, 0, pygame.Vector2(0, 0))
    seen = set()
    for _ in HarpoonTower.TARGETING_MODES:
        seen.add(harpoon.targeting_mode)
        harpoon.cycle_targeting_mode()
    assert seen == set(HarpoonTower.TARGETING_MODES) and harpoon.targeting_mode == "flying"


def _maxed_harpoon():
    harpoon = HarpoonTower(0, 0, pygame.Vector2(0, 0))
    while not harpoon.is_max_level:
        harpoon.upgrade()
    return harpoon


def test_deep_anchor_grounds_longer():
    harpoon = _maxed_harpoon()
    assert harpoon.specialize("deep_anchor")
    shot = harpoon.create_projectile(_enemy_at(100, FlyingEnemy))
    assert shot.ground_duration == pytest.approx(HarpoonTower.ground_duration * 1.7)


def test_reel_in_adds_a_slow_and_damage():
    harpoon = _maxed_harpoon()
    damage_before = harpoon.damage
    assert harpoon.specialize("reel_in")
    flyer = _enemy_at(100, FlyingEnemy)
    shot = harpoon.create_projectile(flyer)
    assert shot.slow_effect == (pytest.approx(0.6), HarpoonTower.REEL_SLOW_DURATION)
    assert harpoon.damage == pytest.approx(damage_before * 1.15)
    shot._resolve_hit(flyer.pos, [flyer])
    assert flyer.slow_multiplier == pytest.approx(0.6) and flyer.is_grounded


def test_harpoon_shows_its_extra_stats():
    harpoon = HarpoonTower(0, 0, pygame.Vector2(0, 0))
    labels = [(label, fmt(getattr(harpoon, attr))) for label, attr, fmt in HarpoonTower.EXTRA_STATS]
    assert ("Grounds for", "3.00s") in labels and ("Reel slow", "0% slower") in labels


def _harpoon_run(game, relic_keys=()):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"], relics=list(relic_keys))
    game._enter_node("0-0")
    run.unlocked_towers += ["harpoon", "basic"]
    game._rebuild_button_rects()
    game.economy.gold = 1000
    game.selected_tower_name = "harpoon"
    assert game.try_place_tower(*find_buildable_anchor(game))
    return game.towers[-1]


def test_barbed_tethers_lengthens_harpoon_grounding_only(game):
    from run.relics import RELICS

    assert "barbed_tethers" in RELICS
    harpoon = _harpoon_run(game, ["barbed_tethers"])
    shot = harpoon.create_projectile(_enemy_at(100, FlyingEnemy))
    assert shot.ground_duration == pytest.approx(HarpoonTower.ground_duration * 1.6)
    plain = _harpoon_run(game, [])
    assert plain.create_projectile(_enemy_at(100, FlyingEnemy)).ground_duration == HarpoonTower.ground_duration
    # Every other tower carries the field harmlessly and never grounds.
    game.selected_tower_name = "basic"
    game.active_run.relics.append("barbed_tethers")
    assert game.try_place_tower(*find_buildable_anchor(game))
    basic = game.towers[-1]
    assert basic.create_projectile(_enemy_at(100, FlyingEnemy)).ground_duration == 0.0


def test_a_placed_harpoon_survives_save_and_resume(game):
    harpoon = _harpoon_run(game)
    while not harpoon.is_max_level:
        assert game.try_upgrade_tower(harpoon)
    assert game.try_specialize_tower(harpoon, "deep_anchor")
    harpoon.cycle_targeting_mode()
    harpoon.cycle_targeting_mode()  # past "flying" and "first" to "last"
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    restored = next(t for t in game.towers if isinstance(t, HarpoonTower))
    assert restored.specialization == "deep_anchor" and restored.targeting_mode == "last"
    assert restored.ground_duration == pytest.approx(HarpoonTower.ground_duration * 1.7)


def test_a_saved_harpoon_on_flying_mode_resumes_but_other_towers_cannot_use_it(game):
    _harpoon_run(game)
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert next(t for t in game.towers if isinstance(t, HarpoonTower)).targeting_mode == "flying"
    with open(game.save_path) as handle:
        raw = json.load(handle)
    raw["towers"][0]["type"] = "basic"
    with open(game.save_path, "w") as handle:
        json.dump(raw, handle)
    assert save_state.load_run(game.save_path) is None


def test_modules_fit_a_harpoon():
    harpoon = HarpoonTower(0, 0, pygame.Vector2(0, 0))
    modules.apply_module(harpoon, modules.MODULES["cryo_coil"])
    modules.apply_module(harpoon, modules.MODULES["rapid_loader"])
    assert harpoon.effective_fire_rate() == pytest.approx(HarpoonTower.fire_rate * 1.2)
    projectiles = []
    flyer = _enemy_at(100, FlyingEnemy)
    harpoon.update(0.1, [flyer], projectiles)
    assert projectiles[0].relic_slow_chance == 1.0 and projectiles[0].ground_duration > 0


def test_harpoon_resonances():
    def at(name, x):
        return TOWER_TYPES[name](0, 0, pygame.Vector2(x, 0))

    mortar, harpoon, cannon = at("mortar", 0), at("harpoon", 40), at("cannon", 80)
    towers = [mortar, harpoon, cannon]
    for tower in towers:
        tower.set_nearby_tower_bonus(towers)
    assert "grounded_barrage" in mortar.resonance_keys
    assert mortar.resonance_fire_rate_bonus == pytest.approx(RESONANCES["grounded_barrage"].fire_rate_bonus)
    assert harpoon.resonance_keys == ["anchor_line"]
    assert harpoon.effective_range() == pytest.approx(HarpoonTower.range * 1.2)
    assert ui.resonance_line(HarpoonTower) == "Pairs with: Cannon"
