"""Sappers -- an enemy that batters Barricades five times as hard, joining
run waves from Act 2 on via run_escalation.add_species."""

from entities.enemy import ENEMY_TYPES, BossEnemy, GruntEnemy, SapperEnemy
from run import run_escalation


def test_breach_multipliers():
    assert GruntEnemy.BREACH_MULTIPLIER == 1.0
    assert SapperEnemy.BREACH_MULTIPLIER == 5.0
    assert BossEnemy.BREACH_MULTIPLIER == 6.0
    assert ENEMY_TYPES["sapper"] is SapperEnemy


def test_reinforcements_grow_with_depth():
    sapper = run_escalation.RUN_REINFORCEMENTS[0]
    assert sapper.species == "sapper"
    assert sapper.count_for_depth(sapper.min_depth - 1) == 0
    assert sapper.count_for_depth(sapper.min_depth) == 1
    assert sapper.count_for_depth(sapper.min_depth + sapper.depth_step) == 2
    assert run_escalation.reinforcements_for_depth(0) == []
    assert run_escalation.reinforcements_for_depth(9) == [("sapper", 1), ("burrower", 1)]
    for reinforcement in run_escalation.RUN_REINFORCEMENTS:
        assert reinforcement.species in ENEMY_TYPES


def test_add_species_copies_and_adds_to_each_waves_first_cell():
    authored = [{(0, 0): {"grunt": 3}, (5, 0): {"scout": 2}}, {(0, 0): {"sapper": 1}}]
    result = run_escalation.add_species(authored, "sapper", 2)
    assert result == [{(0, 0): {"grunt": 3, "sapper": 2}, (5, 0): {"scout": 2}}, {(0, 0): {"sapper": 3}}]
    assert authored == [{(0, 0): {"grunt": 3}, (5, 0): {"scout": 2}}, {(0, 0): {"sapper": 1}}]


def test_act_two_floors_carry_sappers_and_act_one_floors_do_not(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"])
    node = run.map.node("0-0")
    plain = game._level_for_node(run, node)
    assert all("sapper" not in comp for wave in plain.wave_specs for comp in wave.values())
    run.act = 1
    deep = game._level_for_node(run, node)
    assert all(any("sapper" in comp for comp in wave.values()) for wave in deep.wave_specs)
    run.act = 2
    deeper = game._level_for_node(run, node)
    assert all(any("burrower" in comp for comp in wave.values()) for wave in deeper.wave_specs)
    game._enter_node("0-0")
    assert any("sapper" in comp for comp in game.level.wave_specs[0].values())


# --- Burrowers ---


def _burrower_at(x):
    import pygame

    from entities.enemy import BurrowerEnemy

    enemy = BurrowerEnemy([pygame.Vector2(x, 0), pygame.Vector2(x + 500, 0)], wave_number=1)
    enemy.pos = pygame.Vector2(x, 0)
    return enemy


def test_path_traps_cannot_target_or_splash_burrowers():
    import pygame

    from entities.tower import BasicTower, MortarTower, SpikeTrapTower

    spike = SpikeTrapTower(0, 0, pygame.Vector2(0, 0))
    burrower, grunt = _burrower_at(10), GruntEnemy([pygame.Vector2(10, 0), pygame.Vector2(500, 0)], wave_number=1)
    grunt.pos = pygame.Vector2(10, 0)
    assert spike.acquire_target([burrower]) is None
    shot = spike.create_projectile(grunt)
    assert not shot._can_hit(burrower) and shot._can_hit(grunt)
    assert BasicTower(0, 0, pygame.Vector2(0, 0)).acquire_target([burrower]) is burrower
    assert MortarTower(0, 0, pygame.Vector2(0, 0)).acquire_target([_burrower_at(150)]) is not None


def test_trap_and_mortar_splash_respects_flying():
    import pygame

    from entities.enemy import FlyingEnemy
    from entities.tower import MortarTower, SpikeTrapTower, TarPitTower

    flyer = FlyingEnemy([pygame.Vector2(0, 0), pygame.Vector2(500, 0)], wave_number=1)
    for cls in (SpikeTrapTower, TarPitTower, MortarTower):
        shot = cls(0, 0, pygame.Vector2(0, 0)).create_projectile(flyer)
        assert not shot._can_hit(flyer), cls.__name__


def test_barricades_do_not_hold_burrowers(game):
    from test_barricade import _barricade

    barricade = _barricade(game)
    burrower = _burrower_at(0)
    burrower.pos = barricade.pos.copy()
    game.enemies = [burrower]
    game.update(dt=0.5)
    assert not burrower.held and barricade.hp == barricade.max_hp


def test_a_marked_burrower_surfaces_for_traps_and_barricades():
    import pygame

    from entities.tower import SpikeTrapTower

    burrower = _burrower_at(10)
    trap = SpikeTrapTower(0, 0, pygame.Vector2(0, 0))
    assert burrower.is_burrowed and trap.acquire_target([burrower]) is None
    burrower.apply_mark(1.2, 3.0)
    assert not burrower.is_burrowed
    assert trap.acquire_target([burrower]) is burrower
    assert trap.create_projectile(burrower)._can_hit(burrower)
    burrower.update(3.5)
    assert burrower.is_burrowed  # the mark wore off -- back underground


def test_burrowed_and_surfaced_burrowers_both_draw(game):
    surface, assets = game.screen, game.assets
    burrower = _burrower_at(50)
    burrower.draw(surface, assets)
    burrower.apply_mark(1.2, 2.0)
    burrower.draw(surface, assets)


def test_enemy_tooltip_lines_show_traits_and_states(game):
    from conftest import clear_mouse_mock, mock_mouse_pos, start_first_floor

    from entities.enemy import ENEMY_TYPES
    from presentation import ui

    for name, cls in ENEMY_TYPES.items():
        assert cls.display_name and cls.description, name
    burrower = _burrower_at(100)
    lines = ui.enemy_tooltip_lines(burrower)
    assert lines[0] == "Burrower" and lines[-1] == "Burrowed"
    burrower.apply_mark(1.2, 2.0)
    burrower.apply_slow(0.5, 2.0)
    assert ui.enemy_tooltip_lines(burrower)[-1] == "Marked, Slowed"
    start_first_floor(game, seed=1)
    game.enemies = [burrower]
    try:
        mock_mouse_pos((100, 0))
        assert game._hovered_enemy() is burrower
        game.render()
        mock_mouse_pos((400, 400))
        assert game._hovered_enemy() is None
    finally:
        clear_mouse_mock()
