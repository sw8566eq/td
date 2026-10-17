"""Tests for endless mutators -- every MUTATOR_CADENCE endless waves the
final boss fight draws one more stacking mutator (run/endless_mutators.py),
re-derived from the run seed, node id and wave index on every load."""

import random

import pygame
import pytest
from conftest import make_game, make_linear_run_map, quit_pygame_keeping_the_mixer

from entities.enemy import ENEMY_TYPES, FlyingEnemy, GruntEnemy, ShieldedEnemy
from entities.waves import WaveManager, WaveState
from persistence import save_state
from presentation import ui
from progression import run_history
from run import endless_mutators
from run.card_pool import STARTER_TOWERS
from run.endless_mutators import MUTATOR_CADENCE, MUTATORS
from run.potions import POTIONS
from run.run_map import ACT_COUNT
from run.run_state import RunState
from support import settings
from world.levels import LEVELS, Level

FLYING = frozenset({"flying"})
BOSSES = frozenset({"boss"})


def _fixed_rng(index):
    return random.Random(f"test:{index}")


# --- the pure module ---------------------------------------------------------

def test_a_mutator_arrives_every_cadence_endless_waves():
    assert MUTATOR_CADENCE == 5
    assert [endless_mutators.mutator_count(n) for n in (0, 4, 5, 9, 10, 14, 15)] == [0, 0, 1, 1, 2, 2, 3]
    assert endless_mutators.mutator_count(-3) == 0


def test_draws_are_deterministic_for_the_same_keys():
    first = endless_mutators.draw_mutators(_fixed_rng, 6)
    assert first == endless_mutators.draw_mutators(_fixed_rng, 6)
    # A longer draw extends a shorter one -- earlier mutators never change.
    assert endless_mutators.draw_mutators(_fixed_rng, 3) == first[:3]


def test_every_mutator_shows_once_before_only_repeatables_repeat():
    keys = endless_mutators.draw_mutators(_fixed_rng, len(MUTATORS) + 12)
    assert sorted(keys[:len(MUTATORS)]) == sorted(MUTATORS)
    assert all(MUTATORS[key].repeatable for key in keys[len(MUTATORS):])


def test_compose_stacks_multipliers_and_adds_traits():
    effects = endless_mutators.compose(["swarm", "swarm", "ironclad", "regrowth", "regrowth", "escort", "escort"])
    assert effects.count_multiplier == pytest.approx(1.69)
    assert effects.hp_multiplier == pytest.approx(1.25)
    assert effects.regen_fraction_per_second == pytest.approx(0.02)
    assert effects.escorts == (("tank", 2),)
    assert effects.burrows is False
    assert endless_mutators.compose(["tunnelers", "siege", "siege"]).burrows is True
    assert endless_mutators.compose(["siege", "siege"]).breach_multiplier == pytest.approx(4.0)
    assert endless_mutators.compose(["gale"]).speed_multiplier == pytest.approx(1.15)
    assert endless_mutators.compose([]) == endless_mutators.MutatorEffects()


def test_swarm_scales_non_boss_counts_only():
    queue = endless_mutators.compose(["swarm"]).transform_composition({"grunt": 10, "boss": 1}, FLYING, BOSSES)
    assert queue.count("grunt") == 13
    assert queue.count("boss") == 1


def test_escort_adds_a_tank_per_spawn():
    queue = endless_mutators.compose(["escort"]).transform_composition({"grunt": 2}, FLYING, BOSSES)
    assert queue == ["grunt", "grunt", "tank"]


def test_skyborne_turns_every_fourth_ground_enemy_into_a_flyer():
    queue = endless_mutators.compose(["skyborne"]).transform_composition(
        {"grunt": 8, "flying": 2, "boss": 1}, FLYING, BOSSES,
    )
    assert queue.count("flying") == 2 + 2
    assert queue.count("grunt") == 6
    assert queue.count("boss") == 1


def test_shielded_ranks_skips_flyers_and_bosses():
    queue = endless_mutators.compose(["shielded_ranks"]).transform_composition(
        {"grunt": 4, "flying": 4, "boss": 4}, FLYING, BOSSES,
    )
    assert queue.count("shielded") == 1
    assert queue.count("flying") == 4 and queue.count("boss") == 4


def test_summary_names_folds_repeats():
    assert endless_mutators.summary_names(["swarm", "gale", "swarm"]) == ["Swarm x2", "Gale"]


# --- WaveManager -------------------------------------------------------------

def _manager(wave, mutator_keys):
    level = Level(id=1, name="T", path_cells=frozenset({(0, 0), (1, 0)}), spawn_cells=((0, 0),),
                  goal_cells=((1, 0),), wave_specs=[{(0, 0): dict(wave)}], branch_weights={})
    manager = WaveManager(level, lambda col, row: (col * 64, row * 64))
    manager.mutators = endless_mutators.compose(mutator_keys) if mutator_keys else None
    return manager


def _spawned_wave(manager):
    manager.skip_delay()
    manager.update(0.01, [])
    enemies = []
    while manager._has_queued_enemies():
        enemies.extend(manager._spawn_next_round())
    return enemies


@pytest.mark.parametrize("key", list(MUTATORS))
def test_every_mutator_changes_what_a_wave_spawns(key):
    wave = {"grunt": 8, "shielded": 2}
    baseline = _spawned_wave(_manager(wave, []))
    mutated = _spawned_wave(_manager(wave, [key]))

    def fingerprint(enemies):
        return sorted(
            (type(e).__name__, round(e.max_hp, 3), round(e.speed, 3), e.regen_fraction_per_second,
             e.BURROWS, e.BREACH_MULTIPLIER, round(getattr(e, "max_shield", 0), 3))
            for e in enemies
        )
    assert fingerprint(mutated) != fingerprint(baseline)


def test_mutator_stats_apply_on_top_of_the_floor_multipliers():
    manager = _manager({"grunt": 1, "shielded": 1, "flying": 1}, ["ironclad", "gale", "regrowth", "tunnelers", "siege"])
    manager.enemy_hp_multiplier = 2.0
    manager.enemy_regen_fraction_per_second = 0.03  # a boss affix's
    enemies = _spawned_wave(manager)
    grunt, shielded, flyer = (
        next(e for e in enemies if type(e) is cls) for cls in (GruntEnemy, ShieldedEnemy, FlyingEnemy)
    )
    base = GruntEnemy([(0, 0), (64, 0)], 1)
    assert grunt.max_hp == pytest.approx(base.max_hp * 2.0 * 1.25)
    assert grunt.speed == pytest.approx(min(base.speed * 1.15, base.max_speed))
    assert grunt.regen_fraction_per_second == pytest.approx(0.04)
    assert grunt.BURROWS is True and flyer.BURROWS is False
    assert grunt.BREACH_MULTIPLIER == pytest.approx(GruntEnemy.BREACH_MULTIPLIER * 2.0)
    assert shielded.max_shield == pytest.approx(ShieldedEnemy([(0, 0), (64, 0)], 1).max_shield * 2.0 * 1.25)


def test_next_wave_preview_shows_the_mutated_wave():
    manager = _manager({"grunt": 10}, ["swarm", "escort"])
    assert manager.next_wave_preview() == {"grunt": 13, "tank": 1}


def test_mutators_never_touch_the_stored_wave_specs():
    manager = _manager({"grunt": 10}, ["swarm"])
    _spawned_wave(manager)
    assert manager.level.wave_specs == [{(0, 0): {"grunt": 10}}]


# --- Game --------------------------------------------------------------------

def _final_boss(game, seed=1):
    game.active_run = RunState(
        seed=seed, map=make_linear_run_map(["combat", "boss"]), difficulty="normal",
        unlocked_towers=list(STARTER_TOWERS), act=ACT_COUNT - 1, lives=15, lives_captured=True,
        visited_node_ids=["0-0"],
    )
    game._enter_map()
    game._enter_node("1-0")
    return game.active_run


def _authored(game):
    return len(LEVELS[game.active_run.current_level_id].wave_specs)


def _clear_waves(game, count):
    """Clear `count` waves through Game.update()'s real wave-clear path."""
    for _ in range(count):
        game.wave_manager.state = WaveState.SPAWNING
        game.wave_manager._spawn_queues = []
        game.enemies = []
        game.update(dt=0.01)


def _reach_endless(game, endless_cleared):
    """Jump to the last authored wave, then clear it and `endless_cleared` more."""
    game.wave_manager.wave_index = _authored(game) - 1
    _clear_waves(game, endless_cleared + 1)


def test_ordinary_floors_have_no_mutators(game):
    game.active_run = RunState(seed=1, map=make_linear_run_map(["combat", "combat"]), difficulty="normal",
                               unlocked_towers=list(STARTER_TOWERS), lives=15, lives_captured=True)
    game._enter_map()
    game._enter_node("0-0")
    game.wave_manager.wave_index = 99
    game._update_endless_score()
    assert game.active_mutators == []
    assert game.wave_manager.mutators is None


def test_the_final_boss_draws_a_mutator_every_cadence_waves(game):
    run = _final_boss(game)
    _reach_endless(game, MUTATOR_CADENCE - 1)
    assert run.endless_waves_cleared == MUTATOR_CADENCE - 1
    assert game.active_mutators == []
    lives, gold = game.economy.lives, game.economy.gold
    toasts = len(game.achievement_toasts)
    _clear_waves(game, 1)
    assert run.endless_waves_cleared == MUTATOR_CADENCE
    expected = endless_mutators.roll_mutator(game._run_rng(run, "mutator", "1-0:0"), [])
    assert game.active_mutators == [expected]
    assert game.wave_manager.mutators == endless_mutators.compose([expected])
    assert game.economy.lives == lives + endless_mutators.BOUNTY_LIVES
    assert game.economy.gold == gold + endless_mutators.BOUNTY_GOLD
    texts = [toast.text for toast in game.achievement_toasts[toasts:]]
    assert any(MUTATORS[expected].display_name in text and "Endless mutator" in text for text in texts)
    assert any("Bounty" in text for text in texts)
    assert "endless_mutator" in ([game.hints.current] + list(game.hints.pending))


def test_mutators_stack_and_keep_their_draw_order(game):
    _final_boss(game)
    _reach_endless(game, MUTATOR_CADENCE)
    first = list(game.active_mutators)
    _clear_waves(game, MUTATOR_CADENCE)
    assert len(game.active_mutators) == 2
    assert game.active_mutators[:1] == first
    assert game.wave_manager.mutators == endless_mutators.compose(game.active_mutators)


def test_the_next_wave_spawns_with_the_new_mutator(game):
    _final_boss(game)
    _reach_endless(game, MUTATOR_CADENCE)
    preview = game.wave_manager.next_wave_preview()
    raw = {}
    for composition in game.level.wave_specs[game.wave_manager.wave_index].values():
        for name, count in composition.items():
            raw[name] = raw.get(name, 0) + count
    effects = game.wave_manager.mutators
    if effects.count_multiplier != 1.0 or effects.escorts or effects.swaps:
        assert preview != raw
    assert sum(preview.values()) >= sum(raw.values())


def test_resume_rederives_mutators_without_paying_the_bounty_again(game):
    run = _final_boss(game)
    _reach_endless(game, 2 * MUTATOR_CADENCE)
    keys = list(game.active_mutators)
    lives, gold = game.economy.lives, game.economy.gold
    game.save_run()
    game.active_mutators = []
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.active_mutators == keys
    assert game.wave_manager.mutators == endless_mutators.compose(keys)
    assert (game.economy.lives, game.economy.gold) == (lives, gold)
    assert game.active_run.endless_waves_cleared == run.endless_waves_cleared


def test_a_restart_starts_the_mutators_over(game):
    run = _final_boss(game)
    _reach_endless(game, MUTATOR_CADENCE)
    assert game.active_mutators
    game.reset()
    assert game.active_mutators == []
    assert game.wave_manager.mutators is None
    assert run.endless_waves_cleared == MUTATOR_CADENCE  # the run's best stays


def test_daily_runs_draw_the_same_mutators_for_everyone(tmp_path):
    def draws(prefix, seed):
        game = make_game(tmp_path, prefix=prefix)
        try:
            _final_boss(game, seed=seed)
            game.active_run.is_daily = True
            _reach_endless(game, 3 * MUTATOR_CADENCE)
            return list(game.active_mutators)
        finally:
            quit_pygame_keeping_the_mixer()
    seed = 20261016
    assert draws("a_", seed) == draws("b_", seed)
    assert len(draws("c_", seed)) == 3


def test_later_acts_fold_the_act_into_the_mutator_key(game):
    run = _final_boss(game)
    _reach_endless(game, MUTATOR_CADENCE)
    expected = endless_mutators.roll_mutator(random.Random(f"{run.seed}:mutator:act{run.act}:1-0:0"), [])
    assert game.active_mutators == [expected]


def test_the_sidebar_lists_active_mutators(game, tmp_path):
    _final_boss(game)
    game.active_mutators = ["swarm", "ironclad", "gale", "skyborne", "tunnelers", "siege",
                            "regrowth", "shielded_ranks", "escort", "swarm"]
    game.render()
    pygame.image.save(game.screen, str(tmp_path / "mutators.png"))
    lines = ui.mutator_list_lines(endless_mutators.summary_names(game.active_mutators), game.small_font, 10)
    assert lines[0] == "Endless mutators (10)"
    assert all(game.small_font.size(line)[0] <= settings.PANEL_WIDTH - 2 * ui.PANEL_PADDING for line in lines)
    # Worst case -- every mutator, the repeatables many times over -- still
    # stays below the stats panel's Sell/Move row.
    worst = endless_mutators.summary_names(list(MUTATORS) + [k for k in MUTATORS if MUTATORS[k].repeatable] * 9)
    worst_lines = ui.mutator_list_lines(worst, game.small_font, 99)
    top = ui.CHALLENGE_STATUS_Y + ui.PANEL_ROW_HEIGHT - (len(worst_lines) - 1) * ui.PANEL_ROW_HEIGHT
    assert top >= ui.SELL_BUTTON_TOP + ui.ACTION_BUTTON_HEIGHT
    assert ui.mutator_list_lines([], game.small_font) == []
    assert ui.mutator_list_lines(["Gale"], game.small_font)[0] == "Endless mutators (1)"


def test_a_hovered_potion_description_moves_above_the_mutator_list(game):
    _final_boss(game)
    potion = next(iter(POTIONS))
    names = endless_mutators.summary_names(list(MUTATORS))
    drawn = []
    real_render = game.small_font.render

    class SpyFont:
        def render(self, text, *args):
            drawn.append(text)
            return real_render(text, *args)

        def size(self, text):
            return game.small_font.size(text)

    blits = []
    real_blit = game.screen.blit

    class SpySurface:
        def blit(self, source, pos, *args):
            blits.append((drawn[-1] if drawn else None, pos))
            return real_blit(source, pos, *args)

    ui.draw_potion_belt(SpySurface(), game.font, SpyFont(), [potion], [], 0,
                        mutator_names=names, mutator_count=len(names))
    tops = {text: pos[1] for text, pos in blits}
    header_y = tops[f"Endless mutators ({len(names)})"]
    assert tops[POTIONS[potion].display_name] < header_y


def test_run_records_and_recaps_count_mutators_faced(game):
    run = _final_boss(game)
    run.endless_waves_cleared = 2 * MUTATOR_CADENCE + 1
    assert "2 mutators faced" in ui.run_summary_lines(run)[0]
    run.endless_waves_cleared = MUTATOR_CADENCE
    assert "1 mutator faced" in ui.run_summary_lines(run)[0]
    run.endless_waves_cleared = 2 * MUTATOR_CADENCE
    game.economy.lives = 0
    game.update(dt=0.01)
    records = run_history.load_run_records(game.run_history_path)
    assert records[0]["endless_mutators"] == 2
    assert "2 mutators" in ui.run_history_lines({}, records)[0]


def test_run_history_drops_a_record_with_a_bad_mutator_count(tmp_path):
    path = tmp_path / "history.json"
    run_history.record_run_result(1, 3, path, details={"commander": "", "endless_mutators": "lots"})
    assert run_history.load_run_records(path) == []
    run_history.record_run_result(2, 3, path, details={"commander": ""})
    assert len(run_history.load_run_records(path)) == 1


def test_mutator_species_are_real_enemy_types():
    for mutator in MUTATORS.values():
        if mutator.swap is not None:
            assert mutator.swap.to in ENEMY_TYPES
        if mutator.escort_per_spawn:
            assert mutator.escort_species in ENEMY_TYPES


def test_a_mutated_endless_wave_really_spawns(game):
    _final_boss(game)
    _reach_endless(game, 2 * MUTATOR_CADENCE)
    expected = game.wave_manager.next_wave_preview()
    wave_index = game.wave_manager.wave_index
    spawned = {}
    real_spawn = game.wave_manager._spawn_enemy

    def counting_spawn(spawn_cell, enemy_cls):
        name = next(key for key, cls in ENEMY_TYPES.items() if cls is enemy_cls)
        spawned[name] = spawned.get(name, 0) + 1
        return real_spawn(spawn_cell, enemy_cls)
    game.wave_manager._spawn_enemy = counting_spawn
    game.wave_manager.skip_delay()
    for _ in range(20000):
        game.update(dt=0.05)
        game.enemies = []  # keep the board clear so lives never run out
        if game.wave_manager.wave_index > wave_index:
            break
    assert spawned == expected
