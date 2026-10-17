"""Elite affixes and named bosses built from the newer threats -- Disruptors,
Bulwarks and flyers: Jammers, Phalanx, Windborne, The Static Throne and The
Iron Phalanx (run/elite_affixes.py), and how their spawn-queue rules and boss
traits reach WaveManager, survive a resume and show in the UI."""

import pygame
import pytest
from conftest import make_linear_run_map

from entities.enemy import (
    ENEMY_TYPES,
    BossEnemy,
    DisruptorEnemy,
    FinalBossEnemy,
    GruntEnemy,
)
from entities.tower import BasicTower
from persistence import save_state
from presentation import ui
from run import ascension, elite_affixes, endless_mutators
from run.card_pool import STARTER_TOWERS
from run.elite_affixes import AFFIXES, BOSS_AFFIXES
from run.endless_mutators import MutatorEffects, SpeciesSwap
from run.run_state import RunState
from support import settings

_FLYING = frozenset(name for name, cls in ENEMY_TYPES.items() if cls.is_flying)
_BOSSES = frozenset(name for name, cls in ENEMY_TYPES.items() if cls.IS_BOSS)


def _run_with(game, node_type, key, registry):
    """A run whose row-0 `node_type` node rolls `key` -- the seed is
    searched, not hardcoded, so this doesn't depend on the rng's values."""
    for seed in range(400):
        game.active_run = RunState(
            seed=seed, map=make_linear_run_map([node_type, "combat"]), difficulty="normal",
            unlocked_towers=list(STARTER_TOWERS), lives=20,
        )
        game._enter_map()
        if game._elite_affix(game.active_run, game.active_run.map.node("0-0")) is registry[key]:
            return game.active_run
    raise AssertionError(f"no seed in range rolls {key}")


def _queue_totals(manager, wave_index=0):
    totals = {}
    for _cell, names in manager._wave_queues(wave_index):
        for name in names:
            totals[name] = totals.get(name, 0) + 1
    return totals


def _authored_totals(level, wave_index=0):
    totals = {}
    for composition in level.wave_specs[wave_index].values():
        for name, count in composition.items():
            totals[name] = totals.get(name, 0) + count
    return totals


def _enemy(cls, x=0.0):
    enemy = cls([pygame.Vector2(x, 0), pygame.Vector2(x + 2000, 0)], wave_number=1)
    enemy.pos = pygame.Vector2(x, 0)
    return enemy


# --- Registry data -------------------------------------------------------------

def test_new_affixes_use_only_real_species_and_enemy_attributes():
    for affix in list(AFFIXES.values()) + list(BOSS_AFFIXES.values()):
        if affix.escort_per_spawn:
            assert affix.escort_species in ENEMY_TYPES
        if affix.swap is not None:
            assert affix.swap.to in ENEMY_TYPES
        for name, _value in affix.boss_traits:
            assert hasattr(BossEnemy, name) and name.isupper()


def test_spawn_rules_carry_only_the_queue_half():
    assert elite_affixes.spawn_rules(AFFIXES["swift"]) is None
    assert elite_affixes.spawn_rules(AFFIXES["jammers"]) == MutatorEffects(escorts=(("disruptor", 1),))
    assert elite_affixes.spawn_rules(AFFIXES["windborne"]) == MutatorEffects(swaps=(SpeciesSwap(3, "flying"),))
    phalanx = elite_affixes.spawn_rules(AFFIXES["phalanx"])
    assert phalanx.hp_multiplier == 1.0  # its +10% HP goes through the escalation instead


def test_merged_folds_like_compose_and_keeps_swap_order():
    first = MutatorEffects(swaps=(SpeciesSwap(3, "flying"),), escorts=(("bulwark", 1),))
    second = endless_mutators.compose(["escort", "shielded_ranks", "swarm"])
    merged = first.merged(second)
    assert merged.swaps == (SpeciesSwap(3, "flying"), SpeciesSwap(4, "shielded"))
    assert dict(merged.escorts) == {"bulwark": 1, "tank": 1}
    assert merged.count_multiplier == second.count_multiplier
    assert first.merged(None) is first
    both = MutatorEffects(hp_multiplier=2.0, regen_fraction_per_second=0.01, burrows=True).merged(
        MutatorEffects(hp_multiplier=1.5, regen_fraction_per_second=0.02, breach_multiplier=3.0))
    assert (both.hp_multiplier, both.burrows, both.breach_multiplier) == (3.0, True, 3.0)
    assert both.regen_fraction_per_second == pytest.approx(0.03)


# --- Elite affixes on spawns ---------------------------------------------------

@pytest.mark.parametrize("key, species", [("jammers", "disruptor"), ("phalanx", "bulwark")])
def test_escort_affixes_add_one_per_spawn_to_every_wave(game, key, species):
    _run_with(game, "elite", key, AFFIXES)
    game._enter_node("0-0")
    manager = game.wave_manager
    spawns = len(game.level.wave_specs[0])
    for wave_index in (0, len(game.level.wave_specs) - 1):
        authored = _authored_totals(game.level, wave_index)
        totals = _queue_totals(manager, wave_index)
        assert totals[species] == authored.get(species, 0) + spawns
        assert sum(totals.values()) == sum(authored.values()) + spawns
    assert manager.next_wave_preview() == _queue_totals(manager)
    manager._begin_wave()
    queued = [cls for _cell, queue in manager._spawn_queues for cls in queue]
    assert queued.count(ENEMY_TYPES[species]) == _queue_totals(manager)[species]


def test_phalanx_also_toughens_enemies(game):
    run = _run_with(game, "elite", "phalanx", AFFIXES)
    plain = game._node_escalation(run, run.map.node("0-0")).enemy_hp_multiplier
    from run import run_escalation
    bare = run_escalation.apply_elite_multiplier(run_escalation.escalation_for_floor(0)).enemy_hp_multiplier
    assert plain == pytest.approx(bare * 1.1)


def test_windborne_turns_every_third_ground_enemy_into_a_flyer_but_never_a_boss():
    rules = elite_affixes.spawn_rules(AFFIXES["windborne"])
    queue = rules.transform_composition({"grunt": 6, "flying": 2, "boss": 1}, _FLYING, _BOSSES)
    assert queue.count("flying") == 4 and queue.count("grunt") == 4 and queue.count("boss") == 1
    assert queue[:6] == ["grunt", "grunt", "flying", "grunt", "grunt", "flying"]


def test_windborne_reaches_the_live_wave_and_keeps_the_stored_specs(game):
    _run_with(game, "elite", "windborne", AFFIXES)
    game._enter_node("0-0")
    authored = _authored_totals(game.level)
    totals = _queue_totals(game.wave_manager)
    assert sum(totals.values()) == sum(authored.values())
    assert totals.get("flying", 0) > authored.get("flying", 0)
    assert game.level.wave_specs[0] == {cell: dict(c) for cell, c in game.level.wave_specs[0].items()}
    assert _authored_totals(game.level) == authored  # the queue changed, never level.wave_specs


def test_plain_floors_have_no_spawn_rules_or_boss_traits(game):
    game.active_run = RunState(seed=1, map=make_linear_run_map(["combat", "combat"]), difficulty="normal",
                               unlocked_towers=list(STARTER_TOWERS), lives=20)
    game._enter_map()
    game._enter_node("0-0")
    assert game.wave_manager.spawn_rules is None and game.wave_manager.enemy_boss_traits == ()
    assert _queue_totals(game.wave_manager) == _authored_totals(game.level)


def test_spawn_rules_and_endless_mutators_share_one_queue(game):
    _run_with(game, "elite", "jammers", AFFIXES)
    game._enter_node("0-0")
    manager = game.wave_manager
    manager.mutators = endless_mutators.compose(["escort"])
    totals = _queue_totals(manager)
    spawns = len(game.level.wave_specs[0])
    assert totals["tank"] == _authored_totals(game.level).get("tank", 0) + spawns
    assert totals["disruptor"] == _authored_totals(game.level).get("disruptor", 0) + spawns


# --- Named bosses --------------------------------------------------------------

def test_static_throne_gives_the_boss_its_own_jam_pack():
    from entities.waves import WaveManager
    from world.levels import LEVELS

    manager = WaveManager(LEVELS[1], lambda col, row: pygame.Vector2(col, row))
    manager.enemy_boss_traits = BOSS_AFFIXES["static_throne"].boss_traits
    boss, grunt = _enemy(FinalBossEnemy), _enemy(GruntEnemy)
    manager.apply_spawn_multipliers(boss)
    manager.apply_spawn_multipliers(grunt)
    assert (boss.JAM_RADIUS, boss.JAM_DURATION, boss.JAM_COOLDOWN) == (110, 2.0, 6.0)
    assert grunt.JAM_RADIUS == 0
    assert FinalBossEnemy.JAM_RADIUS == 0  # the class is never touched

    near, far = BasicTower(0, 0, pygame.Vector2(100, 0)), BasicTower(0, 0, pygame.Vector2(200, 0))
    assert boss.jam_towers([near, far]) == [near]
    assert near.jammed_timer == 2.0 and boss.jam_cooldown == 6.0
    assert DisruptorEnemy.JAM_DURATION != 2.0  # its own pack, not a Disruptor's


def test_iron_phalanx_boss_shields_the_enemies_around_it(game):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "boss"])
    game.active_run.current_node_id = None
    boss, grunt, distant = _enemy(FinalBossEnemy, 100), _enemy(GruntEnemy, 150), _enemy(GruntEnemy, 400)
    for name, value in BOSS_AFFIXES["iron_phalanx"].boss_traits:
        setattr(boss, name, value)
    game.enemies = [boss, grunt, distant]
    game._apply_enemy_auras()
    assert grunt.aura_damage_reduction == pytest.approx(0.25)
    assert distant.aura_damage_reduction == 0.0 and boss.aura_damage_reduction == 0.0


@pytest.mark.parametrize("key, species, trait", [
    ("static_throne", "disruptor", "JAM_RADIUS"),
    ("iron_phalanx", "bulwark", "AURA_RADIUS"),
])
def test_named_threat_bosses_load_escorts_and_traits_and_survive_resume(game, key, species, trait):
    _run_with(game, "boss", key, BOSS_AFFIXES)
    game._enter_node("0-0")
    affix = BOSS_AFFIXES[key]

    def check():
        manager = game.wave_manager
        assert manager.enemy_boss_traits == affix.boss_traits
        assert manager.spawn_rules == elite_affixes.spawn_rules(affix)
        spawns = len(game.level.wave_specs[0])
        assert _queue_totals(manager)[species] == _authored_totals(game.level).get(species, 0) + spawns
        boss = _enemy(FinalBossEnemy)
        manager.apply_spawn_multipliers(boss)
        assert getattr(boss, trait) == dict(affix.boss_traits)[trait]

    check()
    assert affix.display_name in game.renderer._run_modifiers_text()
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    check()


# --- UI --------------------------------------------------------------------------

NEW_KEYS = [("jammers", AFFIXES), ("phalanx", AFFIXES), ("windborne", AFFIXES),
            ("static_throne", BOSS_AFFIXES), ("iron_phalanx", BOSS_AFFIXES)]


def test_field_manual_lists_the_new_affixes_and_bosses(game):
    rows = ui.compendium_rows(game.small_font)
    names = {name for kind, name, _detail in rows if kind == "entry"}
    for key, registry in NEW_KEYS:
        assert registry[key].display_name in names


@pytest.mark.parametrize("key, registry", NEW_KEYS)
def test_map_tooltip_names_and_explains_the_affix(game, key, registry):
    from run.run_map import MapNode

    affix = registry[key]
    node_type = "elite" if registry is AFFIXES else "boss"
    node = MapNode("0-0", row=0, col=0, node_type=node_type, level_id=1)
    title, body = ui.map_node_tooltip_lines(game.small_font, node, affix)
    assert affix.display_name in title
    assert affix.description.split()[0] in " ".join(body)
    assert all(game.small_font.size(line)[0] <= ui.MAP_TOOLTIP_MAX_WIDTH for line in body)


@pytest.mark.parametrize("key, registry", NEW_KEYS)
def test_sidebar_text_fits_the_panel_at_a_deep_gauntlet(game, key, registry, tmp_path):
    node_type = "elite" if registry is AFFIXES else "boss"
    run = _run_with(game, node_type, key, registry)
    run.ascension = len(ascension.ASCENSION_LEVELS)  # the widest "Gauntlet N" prefix
    game._enter_node("0-0")
    text = game.renderer._run_modifiers_text()
    assert registry[key].display_name in text
    # Drawn from the panel's left padding; must end before the screen edge.
    assert settings.PLAY_WIDTH + ui.PANEL_PADDING + game.small_font.size(text)[0] <= settings.SCREEN_WIDTH
    game.render()
    pygame.image.save(game.screen, str(tmp_path / f"{key}.png"))
