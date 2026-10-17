"""Disruptors (jam nearby towers on a cooldown) and Bulwarks (a damage-
reduction aura for the enemies around them) -- two enemies that punish lazy
defenses, joining run waves via run_escalation.RUN_REINFORCEMENTS."""

import pygame
import pytest
from conftest import make_game, start_first_floor

from entities.enemy import (
    ENEMY_TYPES,
    BossEnemy,
    BulwarkEnemy,
    DisruptorEnemy,
    GruntEnemy,
    ShieldedEnemy,
)
from entities.tower import (
    BarricadeTower,
    BasicTower,
    OverloadCannonTower,
    SniperTower,
    SupportTower,
)
from progression import achievements
from run import run_escalation


def _enemy(cls, x=0.0, y=0.0):
    enemy = cls([pygame.Vector2(x, y), pygame.Vector2(x + 2000, y)], wave_number=1)
    enemy.pos = pygame.Vector2(x, y)
    return enemy


def _tower(cls, x, y=0.0):
    return cls(0, 0, pygame.Vector2(x, y))


# --- Disruptor: jamming ---


def test_disruptor_jams_only_jammable_towers_in_reach_then_cools_down():
    disruptor = _enemy(DisruptorEnemy)
    near = _tower(BasicTower, DisruptorEnemy.JAM_RADIUS - 5)
    far = _tower(SniperTower, DisruptorEnemy.JAM_RADIUS + 50)
    support, barricade = _tower(SupportTower, 10), _tower(BarricadeTower, 0)
    towers = [near, far, support, barricade]

    assert disruptor.jam_towers(towers) == [near]
    assert near.is_jammed and near.jammed_timer == DisruptorEnemy.JAM_DURATION
    assert not far.is_jammed and not support.is_jammed and not barricade.is_jammed
    assert disruptor.jam_cooldown == DisruptorEnemy.JAM_COOLDOWN

    near.jammed_timer = 0.0
    assert disruptor.jam_towers(towers) == []  # still cooling down
    disruptor.update(DisruptorEnemy.JAM_COOLDOWN)
    assert disruptor.jam_cooldown == 0.0
    disruptor.pos = pygame.Vector2(0, 0)  # it walked on meanwhile
    assert disruptor.jam_towers(towers) == [near]


def test_a_pulse_with_nothing_in_reach_keeps_the_disruptor_charged():
    disruptor = _enemy(DisruptorEnemy)
    assert disruptor.jam_towers([_tower(BasicTower, 500)]) == []
    assert disruptor.jam_cooldown == 0.0
    # Other species never jam, and a dead Disruptor doesn't either.
    assert _enemy(GruntEnemy).jam_towers([_tower(BasicTower, 0)]) == []
    disruptor.is_dead = True
    assert disruptor.jam_towers([_tower(BasicTower, 0)]) == []


def test_overlapping_jams_keep_the_longer_one():
    tower = _tower(BasicTower, 0)
    tower.jam(1.5)
    tower.jam(0.5)
    assert tower.jammed_timer == 1.5
    support = _tower(SupportTower, 0)
    support.jam(1.5)  # never jammable, even when jammed directly
    assert not support.is_jammed


def test_a_jammed_tower_cannot_fire_until_the_jam_lifts():
    tower = _tower(BasicTower, 0)
    grunt = _enemy(GruntEnemy, 50)
    projectiles = []
    tower.jam(1.5)
    tower.update(1.0, [grunt], projectiles)
    assert projectiles == [] and tower.is_jammed
    tower.update(0.6, [grunt], projectiles)
    assert len(projectiles) == 1 and not tower.is_jammed


def test_a_jam_pauses_an_overload_cannons_charge_without_losing_it():
    cannon = _tower(OverloadCannonTower, 0)
    grunt = _enemy(GruntEnemy, 50)
    grunt.max_hp = grunt.hp = 1e9
    projectiles = []
    cannon.update(0.01, [grunt], projectiles)  # acquire and begin charging
    cannon.update(0.5, [grunt], projectiles)
    charged = cannon._charge_elapsed
    cannon.jam(1.0)
    cannon.update(0.5, [grunt], projectiles)
    assert cannon._charge_elapsed == charged and cannon._charge_target is grunt
    cannon.update(0.6, [grunt], projectiles)
    assert cannon._charge_elapsed > charged


def test_game_jams_towers_near_a_disruptor_and_shows_the_pulse(game):
    start_first_floor(game, seed=1)
    tower = _tower(BasicTower, 300, 300)
    game.towers = [tower]
    disruptor = _enemy(DisruptorEnemy, 300 + DisruptorEnemy.JAM_RADIUS - 10, 300)
    game.enemies = [disruptor]
    rings = len(game.impact_effects)
    game.update(dt=0.01)
    assert tower.is_jammed and disruptor.jam_cooldown > 0
    assert len(game.impact_effects) > rings
    game.selected_tower = tower
    game.render()  # jammed overlay, the stats panel's Jammed row, and the charged/spent rings


def test_faraday_mesh_shortens_jams(game):
    from test_barricade import _build, _run_with

    _run_with(game, ["faraday_mesh"])
    tower = _build(game, "basic")
    assert tower.jam_duration_multiplier == pytest.approx(0.4)
    tower.jam(DisruptorEnemy.JAM_DURATION)
    assert tower.jammed_timer == pytest.approx(DisruptorEnemy.JAM_DURATION * 0.4)


# --- Bulwark: damage-reduction aura ---


def test_bulwark_shields_others_in_reach_but_not_itself(game):
    start_first_floor(game, seed=1)
    bulwark = _enemy(BulwarkEnemy, 100)
    near, far = _enemy(GruntEnemy, 150), _enemy(GruntEnemy, 100 + BulwarkEnemy.AURA_RADIUS + 30)
    game.enemies = [near, bulwark, far]
    game._apply_enemy_auras()
    assert near.aura_damage_reduction == pytest.approx(0.30)
    assert bulwark.aura_damage_reduction == 0.0 and far.aura_damage_reduction == 0.0
    assert near.take_damage(10) == pytest.approx(7.0)
    # Fresh every frame: once the Bulwark is gone, so is the protection.
    bulwark.is_dead = True
    game._apply_enemy_auras()
    assert near.aura_damage_reduction == 0.0


def test_two_bulwarks_use_the_max_not_a_stack(game):
    start_first_floor(game, seed=1)
    first, second = _enemy(BulwarkEnemy, 100), _enemy(BulwarkEnemy, 120)
    grunt = _enemy(GruntEnemy, 110)
    game.enemies = [first, grunt, second]
    game._apply_enemy_auras()
    assert grunt.aura_damage_reduction == pytest.approx(0.30)
    # Each Bulwark protects the other.
    assert first.aura_damage_reduction == pytest.approx(0.30)


def test_linebreaker_weakens_the_aura(game):
    from test_barricade import _run_with

    _run_with(game, ["linebreaker"])
    bulwark, grunt = _enemy(BulwarkEnemy, 100), _enemy(GruntEnemy, 110)
    game.enemies = [bulwark, grunt]
    game._apply_enemy_auras()
    assert grunt.aura_damage_reduction == pytest.approx(0.30 * 0.25)


def test_aura_composes_with_mark_multiplicatively():
    grunt = _enemy(GruntEnemy)
    grunt.aura_damage_reduction = 0.3
    grunt.apply_mark(1.2, 3.0)
    assert grunt.take_damage(10) == pytest.approx(10 * 1.2 * 0.7)


def test_shields_absorb_the_raw_hit_and_the_aura_only_cuts_what_reaches_hp():
    shielded = _enemy(ShieldedEnemy)
    shielded.shield = 5.0
    shielded.aura_damage_reduction = 0.3
    applied = shielded.take_damage(10)
    assert shielded.shield == 0.0
    assert applied == pytest.approx(5 * 0.7)
    # Corrosive Poison skips the shield but still meets the aura.
    shielded.shield = 50.0
    assert shielded.take_poison_damage(10, ignore_shield=True) == pytest.approx(7.0)
    assert shielded.shield == 50.0


def test_boss_armor_comes_off_before_the_aura():
    boss = _enemy(BossEnemy)
    boss.armor_timer = 1.0
    boss.aura_damage_reduction = 0.3
    assert boss.take_damage(20) == pytest.approx((20 - BossEnemy.ARMOR_FLAT_REDUCTION) * 0.7)


def test_bulwark_and_fortified_enemies_draw(game):
    surface, assets = game.screen, game.assets
    bulwark, grunt = _enemy(BulwarkEnemy, 100, 100), _enemy(GruntEnemy, 120, 100)
    grunt.aura_damage_reduction = 0.3
    bulwark.draw(surface, assets)
    grunt.draw(surface, assets)
    disruptor = _enemy(DisruptorEnemy, 200, 200)
    disruptor.draw(surface, assets)  # charged: shows its jam radius
    disruptor.jam_cooldown = 1.0
    disruptor.draw(surface, assets)


# --- Bringing them into play ---


def test_reinforcement_depths_leave_the_opening_rows_alone():
    by_species = {r.species: r for r in run_escalation.RUN_REINFORCEMENTS}
    assert by_species["disruptor"].min_depth == 4  # mid Act 1, past grace and the row-3 step
    assert by_species["bulwark"].min_depth == 7  # Act 2's second row
    for depth in range(4):
        assert run_escalation.reinforcements_for_depth(depth) == []
    assert run_escalation.reinforcements_for_depth(4) == [("disruptor", 1)]
    assert ("bulwark", 1) in run_escalation.reinforcements_for_depth(7)


def test_run_floors_carry_them_at_their_depths(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat"] * 6)

    def species(node_id):
        level = game._level_for_node(run, run.map.node(node_id))
        return {name for wave in level.wave_specs for comp in wave.values() for name in comp}

    assert "disruptor" not in species("3-0")
    assert "disruptor" in species("4-0") and "bulwark" not in species("4-0")
    run.act = 1
    assert "bulwark" in species("1-0") and "bulwark" not in species("0-0")


def test_a_mid_floor_save_keeps_the_reinforced_waves(game, tmp_path):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "combat"], act=2)
    game._enter_node("0-0")
    first_wave = game.level.wave_specs[0]
    assert any("disruptor" in comp and "bulwark" in comp for comp in first_wave.values())
    game.save_run()
    fresh = make_game(tmp_path)
    fresh._continue_saved_run()
    assert fresh.level.wave_specs == game.level.wave_specs
    # A resumed floor's towers start unjammed (jams are never saved).
    assert all(not tower.is_jammed for tower in fresh.towers)


def test_killing_them_counts_toward_their_achievements(game):
    start_first_floor(game, seed=1)
    disruptor, bulwark = _enemy(DisruptorEnemy, 300, 300), _enemy(BulwarkEnemy, 600, 300)
    disruptor.is_dead = bulwark.is_dead = True
    game.enemies = [disruptor, bulwark]
    game.update(dt=0.01)
    counters = achievements.load_achievements(game.achievements_path)["counters"]
    assert counters["disruptors_killed"] == 1 and counters["bulwarks_killed"] == 1


def test_tooltip_and_field_manual_rows(game):
    from presentation import ui

    grunt = _enemy(GruntEnemy)
    grunt.aura_damage_reduction = 0.3
    assert ui.enemy_tooltip_lines(grunt)[-1] == "Fortified (-30% dmg)"
    assert ui.enemy_tooltip_lines(_enemy(DisruptorEnemy))[0] == "Disruptor"
    names = [name for kind, name, _ in ui.compendium_rows(game.small_font) if kind == "entry"]
    assert "Disruptor" in names and "Bulwark" in names
    assert ENEMY_TYPES["disruptor"] is DisruptorEnemy and ENEMY_TYPES["bulwark"] is BulwarkEnemy
