"""The Brazier tower, its cone wash (Projectile._resolve_cone) and the
Burning status (Enemy.apply_burn)."""

import math

import pygame
import pytest
from conftest import find_buildable_anchor, start_first_floor

from entities import effects
from entities.effects import FlameWedge
from entities.enemy import BURN_TICK_INTERVAL, BurrowerEnemy, FlyingEnemy, GruntEnemy, ShieldedEnemy
from entities.projectile import Projectile
from entities.tower import RESONANCES, TOWER_TYPES, BrazierTower, OverloadCannonTower
from persistence import save_state
from presentation import ui
from support import settings
from world.spatial_index import EnemySpatialIndex


def _enemy_at(x, y=0, cls=GruntEnemy):
    enemy = cls([pygame.Vector2(x, y), pygame.Vector2(x + 500, y)], wave_number=1)
    enemy.pos = pygame.Vector2(x, y)
    return enemy


def _at_angle(degrees, distance, cls=GruntEnemy):
    radians = math.radians(degrees)
    return _enemy_at(distance * math.cos(radians), distance * math.sin(radians), cls)


def _brazier():
    return BrazierTower(0, 0, pygame.Vector2(0, 0))


def _wash(tower, target, enemies, enemy_index=None):
    shot = tower.create_projectile(target)
    shot.update(1 / 30, enemies, enemy_index)
    return shot


# --- Registration ---


def test_brazier_is_registered_unlockable_and_ground_only():
    from progression import meta_progression

    assert TOWER_TYPES["brazier"] is BrazierTower
    assert meta_progression.META_UNLOCKS["unlock_brazier"].tower_name == "brazier"
    assert not BrazierTower.can_target_flying and not BrazierTower.HITS_BURROWED
    assert BrazierTower.ATTACKS and not BrazierTower.IS_SUPPORT
    assert len(BrazierTower.SPECIALIZATIONS) == 2


def test_the_build_menu_fits_every_tower_in_two_rows_of_nine():
    rects = ui.build_button_rects(list(TOWER_TYPES))
    assert len(rects) == len(TOWER_TYPES) <= 2 * ui.BUTTONS_PER_ROW
    rows = {}
    for rect in rects.values():
        rows.setdefault(rect.y, []).append(rect)
    assert len(rows) == 2 and all(len(row) <= ui.BUTTONS_PER_ROW for row in rows.values())
    assert ui.hud_info_x(rects) < settings.PLAY_WIDTH


# --- Cone geometry ---


def test_the_wash_hits_everything_inside_the_cone_and_nothing_outside():
    brazier = _brazier()
    half = BrazierTower.cone_angle / 2
    target = _at_angle(0, 60)
    inside = [_at_angle(half - 3, 80), _at_angle(-(half - 3), 40), _at_angle(10, 90)]
    wide = [_at_angle(half + 5, 60), _at_angle(-(half + 5), 60), _at_angle(180, 30)]
    far = [_at_angle(0, BrazierTower.range + 5)]
    enemies = [target, *inside, *wide, *far]
    shot = _wash(brazier, target, enemies)
    assert shot.dead
    for enemy in [target, *inside]:
        assert enemy.hp < enemy.max_hp and enemy.is_burning
    for enemy in [*wide, *far]:
        assert enemy.hp == enemy.max_hp and not enemy.is_burning
    assert brazier.shots_hit == 1
    assert brazier.damage_dealt == pytest.approx(4 * BrazierTower.damage)


def test_the_cone_points_at_the_target_wherever_it_stands():
    brazier = _brazier()
    target = _at_angle(135, 70)
    beside = _at_angle(150, 70)
    behind = _at_angle(-45, 70)
    _wash(brazier, target, [target, beside, behind])
    assert beside.is_burning and not behind.is_burning
    shot = brazier.create_projectile(target)
    shot.update(0.0, [target], None)
    (origin, direction, half_angle, radius), = shot.cone_events
    assert direction == pytest.approx(135) and half_angle == pytest.approx(BrazierTower.cone_angle / 2)
    assert radius == pytest.approx(brazier.effective_range()) and origin == brazier.pos


def test_an_enemy_on_the_origin_counts_as_inside():
    brazier = _brazier()
    on_top = _enemy_at(0, 0)
    _wash(brazier, on_top, [on_top])
    assert on_top.is_burning


def test_a_wash_still_lands_if_its_target_died_first():
    brazier = _brazier()
    target, other = _at_angle(0, 50), _at_angle(5, 70)
    target.is_dead = True
    shot = _wash(brazier, target, [target, other])
    assert shot.dead and other.is_burning and not target.is_burning


def test_the_wash_skips_airborne_flyers_and_burrowers_but_burns_a_grounded_flyer():
    brazier = _brazier()
    target = _at_angle(0, 50)
    airborne = _at_angle(5, 60, FlyingEnemy)
    grounded = _at_angle(-5, 60, FlyingEnemy)
    grounded.apply_ground(3.0)
    burrower = _at_angle(0, 70, BurrowerEnemy)
    _wash(brazier, target, [target, airborne, grounded, burrower])
    assert not airborne.is_burning and airborne.hp == airborne.max_hp
    assert not burrower.is_burning and burrower.hp == burrower.max_hp
    assert grounded.is_burning
    # Targeting follows the same rules.
    assert brazier.acquire_target([airborne, burrower]) is None
    assert brazier.acquire_target([grounded]) is grounded
    marked = _at_angle(0, 70, BurrowerEnemy)
    marked.apply_mark(1.2, 2.0)  # a mark surfaces a burrower
    assert brazier.acquire_target([marked]) is marked


def test_the_enemy_index_gives_the_same_wash_as_the_raw_list():
    def board():
        return [_at_angle(angle, distance) for angle in range(-60, 61, 7) for distance in (20, 55, 90, 120)]

    raw, indexed = board(), board()
    _wash(_brazier(), raw[len(raw) // 2], raw)
    _wash(_brazier(), indexed[len(indexed) // 2], indexed, EnemySpatialIndex(indexed))
    assert [e.hp for e in raw] == [e.hp for e in indexed]
    assert [e.is_burning for e in raw] == [e.is_burning for e in indexed]


def test_the_brazier_fires_through_the_normal_tower_loop():
    brazier = _brazier()
    enemies = [_at_angle(0, 50), _at_angle(10, 70)]
    projectiles = []
    brazier.update(0.1, enemies, projectiles)
    assert brazier.fired_this_frame and brazier.shots_fired == 1
    assert len(projectiles) == 1 and projectiles[0].cone_radius > 0
    for shot in projectiles:
        shot.update(0.1, enemies)
    assert all(e.is_burning for e in enemies)
    assert brazier.cooldown == pytest.approx(1 / BrazierTower.fire_rate)


def test_relic_and_module_on_hit_fields_ride_the_wash():
    from run import modules

    brazier = _brazier()
    modules.apply_module(brazier, modules.MODULES["venom_injector"])
    enemies = [_at_angle(0, 50), _at_angle(10, 70)]
    projectiles = []
    brazier.update(0.1, enemies, projectiles)
    projectiles[0].update(0.1, enemies)
    assert all(e.poison_time_remaining > 0 and e.is_burning for e in enemies)


def test_damage_modules_and_buffs_scale_the_burn_too():
    from run import modules

    brazier = _brazier()
    assert brazier.burn_tick() == pytest.approx(BrazierTower.burn_damage_per_tick)
    modules.apply_module(brazier, modules.MODULES["heavy_payload"])
    assert brazier.burn_tick() == pytest.approx(BrazierTower.burn_damage_per_tick * 1.35)
    brazier.damage = 0
    assert brazier.burn_tick() == pytest.approx(BrazierTower.burn_damage_per_tick)


def test_long_barrel_deepens_the_cone():
    from run import modules

    brazier = _brazier()
    modules.apply_module(brazier, modules.MODULES["long_barrel"])
    assert brazier.create_projectile(_enemy_at(50)).cone_radius == pytest.approx(BrazierTower.range * 1.2)


def test_overload_cannon_needs_no_brazier_relic_fields():
    # The burn is a tower-own field on the shot, not a relic_* tag.
    shot = OverloadCannonTower(0, 0, pygame.Vector2(0, 0)).create_projectile(_enemy_at(50))
    assert shot.burn_effect is None and shot.cone_radius == 0


# --- The Burning status ---


def test_burn_ticks_on_its_interval_and_credits_its_source():
    brazier = _brazier()
    enemy = _enemy_at(0)
    enemy.apply_burn(5.0, 1.0, source=brazier)
    enemy.update(0.01)  # first tick lands right away
    assert enemy.hp == pytest.approx(enemy.max_hp - 5.0)
    assert brazier.damage_dealt == pytest.approx(5.0)
    enemy.update(BURN_TICK_INTERVAL)
    assert enemy.hp == pytest.approx(enemy.max_hp - 10.0)
    enemy.update(1.0)
    assert not enemy.is_burning and enemy.burn_damage_per_tick == 0.0
    hp = enemy.hp
    enemy.update(1.0)
    assert enemy.hp == hp


def test_a_killing_burn_tick_credits_the_kill_and_stops_the_corpse():
    brazier = _brazier()
    enemy = _enemy_at(0)
    enemy.hp = 3.0
    enemy.apply_burn(5.0, 2.0, source=brazier)
    pos = pygame.Vector2(enemy.pos)
    enemy.update(0.1)
    assert enemy.is_dead and brazier.kills == 1 and enemy.pos == pos


def test_burn_refreshes_to_the_stronger_tick_and_the_longer_duration():
    weak, strong = _brazier(), _brazier()
    enemy = _enemy_at(0)
    enemy.apply_burn(5.0, 3.0, source=strong)
    enemy.apply_burn(2.0, 1.0, source=weak)
    assert enemy.burn_damage_per_tick == 5.0 and enemy.burn_time_remaining == pytest.approx(3.0)
    assert enemy.burn_source is strong
    enemy.apply_burn(6.0, 4.0, source=weak)
    assert enemy.burn_source is weak and enemy.burn_time_remaining == pytest.approx(4.0)
    enemy.apply_burn(1.0, 1.0)  # a sourceless burn keeps the credit
    assert enemy.burn_source is weak


def test_burn_and_poison_stack_as_separate_channels():
    enemy = _enemy_at(0)
    enemy.apply_poison(4.0, 0.5, 2.0)
    enemy.apply_burn(5.0, 2.0)
    enemy.update(0.01)
    assert enemy.hp == pytest.approx(enemy.max_hp - 9.0)
    assert enemy.poison_damage_per_tick == 4.0 and enemy.burn_damage_per_tick == 5.0


def test_burn_is_a_no_op_on_the_dead_and_does_not_slip_past_a_shield():
    dead = _enemy_at(0)
    dead.is_dead = True
    dead.apply_burn(5.0, 2.0)
    assert not dead.is_burning
    shielded = _enemy_at(0, cls=ShieldedEnemy)
    shielded.apply_burn(5.0, 2.0)
    shielded.update(0.01)
    assert shielded.hp == shielded.max_hp and shielded.shield < shielded.max_shield


def test_the_tooltip_lists_burning_and_a_burning_enemy_draws():
    from presentation.assets import AssetManager

    enemy = _enemy_at(100, 100)
    assert "Burning" not in " ".join(ui.enemy_tooltip_lines(enemy))
    enemy.apply_burn(2.0, 2.0)
    assert "Burning" in ui.enemy_tooltip_lines(enemy)[-1]
    enemy.draw(pygame.Surface((300, 300)), AssetManager(asset_root="/nonexistent"))


def test_the_run_guide_explains_burning():
    assert any("Burning" in line for line in ui.RUN_GUIDE_LINES)


# --- Specializations ---


def _maxed(spec):
    brazier = _brazier()
    while not brazier.is_max_level:
        brazier.upgrade()
    assert brazier.specialize(spec)
    return brazier


def test_level_scales_the_hit_and_the_burn_but_not_the_reach():
    brazier = _brazier()
    while not brazier.is_max_level:
        brazier.upgrade()
    assert brazier.range == BrazierTower.range
    assert brazier.damage == pytest.approx(BrazierTower.damage * 1.8)
    assert brazier.burn_damage_per_tick == pytest.approx(BrazierTower.burn_damage_per_tick * 1.8)


def test_wide_arc_widens_the_cone_to_110_degrees():
    brazier = _maxed("wide_arc")
    assert brazier.cone_angle == pytest.approx(110.0)
    target = _at_angle(0, 50)
    edge = _at_angle(50, 60)  # outside 70 degrees, inside 110
    _wash(brazier, target, [target, edge])
    assert edge.is_burning
    plain = _brazier()
    edge2 = _at_angle(50, 60)
    _wash(plain, target, [target, edge2])
    assert not edge2.is_burning


def test_blue_flame_burns_hotter_and_longer():
    brazier = _maxed("blue_flame")
    tick, duration = brazier.create_projectile(_enemy_at(50)).burn_effect
    assert duration == pytest.approx(BrazierTower.burn_duration * 1.6)
    assert tick == pytest.approx(BrazierTower.burn_damage_per_tick * 1.8 * 1.2)


# --- Relic, resonances, hints ---


def _brazier_run(game, relic_keys=()):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "combat"], relics=list(relic_keys))
    game._enter_node("0-0")
    game.active_run.unlocked_towers += ["brazier", "basic"]
    game._rebuild_button_rects()
    game.economy.gold = 1000
    game.selected_tower_name = "brazier"
    assert game.try_place_tower(*find_buildable_anchor(game))
    return game.towers[-1]


def test_pitch_oil_strengthens_brazier_burns_only(game):
    from run.relics import RELICS

    assert not RELICS["pitch_oil"].is_curse and not RELICS["pitch_oil"].is_boss_relic
    brazier = _brazier_run(game, ["pitch_oil"])
    assert brazier.burn_tick() == pytest.approx(BrazierTower.burn_damage_per_tick * 1.5)
    assert _brazier_run(game, []).burn_tick() == pytest.approx(BrazierTower.burn_damage_per_tick)
    game.active_run.relics.append("pitch_oil")
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    basic = game.towers[-1]
    assert basic.relic_brazier_burn_bonus_multiplier == 1.5
    assert basic.create_projectile(_enemy_at(50)).burn_effect is None


def test_brazier_resonances():
    def at(name, x):
        return TOWER_TYPES[name](0, 0, pygame.Vector2(x, 0))

    brazier, barricade, tar = at("brazier", 0), at("barricade", 40), at("tar_pit", 80)
    towers = [brazier, barricade, tar]
    for tower in towers:
        tower.set_nearby_tower_bonus(towers)
    assert brazier.resonance_keys == ["firebreak", "kindling"]
    assert brazier.effective_fire_rate() == pytest.approx(
        BrazierTower.fire_rate * (1 + RESONANCES["firebreak"].fire_rate_bonus))
    assert brazier.effective_damage() == pytest.approx(
        BrazierTower.damage * (1 + RESONANCES["kindling"].damage_bonus))
    assert ui.resonance_line(BrazierTower) == "Pairs with: Barricade, Tar Pit"


def test_building_a_brazier_queues_its_field_note(game):
    start_first_floor(game)
    while game.hints.current is not None:
        game.hints.dismiss()
    game.active_run.unlocked_towers.append("brazier")
    game._rebuild_button_rects()
    game.economy.gold = 1000
    game.selected_tower_name = "brazier"
    assert game.try_place_tower(*find_buildable_anchor(game))
    shown = ([game.hints.current] if game.hints.current else []) + list(game.hints.pending)
    assert "brazier" in shown


# --- Game: save/resume and the flame wedge ---


def test_a_placed_brazier_survives_save_and_resume(game):
    brazier = _brazier_run(game)
    while not brazier.is_max_level:
        assert game.try_upgrade_tower(brazier)
    assert game.try_specialize_tower(brazier, "wide_arc")
    brazier.damage_dealt, brazier.kills = 120.0, 4
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    restored = next(t for t in game.towers if isinstance(t, BrazierTower))
    assert restored.specialization == "wide_arc" and restored.level == restored.MAX_LEVEL
    assert restored.cone_angle == pytest.approx(110.0)
    assert restored.damage_dealt == 120.0 and restored.kills == 4


def test_a_wash_in_game_spawns_a_fading_flame_wedge(game):
    brazier = _brazier_run(game)
    enemy = _enemy_at(brazier.pos.x + 40, brazier.pos.y)
    game.enemies = [enemy]
    game.update(1 / 30)
    wedges = [effect for effect in game.impact_effects if isinstance(effect, FlameWedge)]
    assert len(wedges) == 1 and enemy.is_burning
    assert not any(projectile.cone_radius for projectile in game.projectiles)
    wedge = wedges[0]
    wedge.draw(game.screen)
    wedge.update(wedge.duration)
    assert wedge.dead
    wedge.draw(game.screen)  # a dead wedge draws nothing
    game.update(1 / 30)
    assert wedge not in game.impact_effects


def test_flame_wedges_share_a_cached_surface_and_the_cache_clears_at_its_limit(monkeypatch):
    monkeypatch.setattr(effects, "_wedge_cache", {})
    first = effects._wedge_surface(60, 45, 35, (255, 130, 40))
    assert effects._wedge_surface(60, 45, 35, (255, 130, 40)) is first
    assert effects._wedge_surface(60, 50, 35, (255, 130, 40)) is not first
    monkeypatch.setattr(effects, "_WEDGE_CACHE_LIMIT", 2)
    effects._wedge_surface(10, 0, 35, (1, 1, 1))
    assert list(effects._wedge_cache) == [(10, 0, 35, (1, 1, 1))]


def test_a_cached_wedge_draws_the_same_pixels_as_a_fresh_one(monkeypatch):
    def draw():
        surface = pygame.Surface((200, 200))
        wedge = FlameWedge((100, 100), 47.0, 35.0, 80)
        wedge.update(0.1)
        wedge.draw(surface)
        return pygame.image.tobytes(surface, "RGBA")

    monkeypatch.setattr(effects, "_wedge_cache", {})
    fresh = draw()
    assert draw() == fresh  # second draw is a cache hit
    tiny = FlameWedge((0, 0), 0.0, 35.0, 0.5)
    tiny.draw(pygame.Surface((10, 10)))  # under a pixel: nothing to draw
    instant = FlameWedge((0, 0), 0.0, 35.0, 20, duration=0)
    assert instant.dead


def test_a_cone_projectile_records_no_impact_ring():
    target = _enemy_at(50)
    shot = Projectile(pos=(0, 0), target=target, speed=0.0, damage=1, cone_radius=90, cone_half_angle=35)
    shot.update(1 / 30, [target])
    assert shot.impact_events == [] and len(shot.cone_events) == 1
