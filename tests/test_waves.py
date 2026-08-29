import random

import pytest

from enemy import GruntEnemy, ShieldedEnemy, TankEnemy
from levels import Level
from waves import WaveManager, WaveState


def cell_to_pixel(col, row):
    return (col * 64, row * 64)


def make_level(wave_specs, path_cells=None, spawn_cells=None, goal_cells=None, branch_weights=None):
    """wave_specs is given in the flat, single-wave-dict-per-wave shape
    ({enemy_name: count}, ...) and wrapped here under the level's first
    spawn cell -- convenient shorthand for the common single-spawn case.
    A test that actually wants different composition per spawn builds a
    Level directly instead -- see the "Multi-spawn" tests below."""
    spawn_cells = tuple(spawn_cells or ((0, 0),))
    return Level(
        id=1,
        name="Test Level",
        path_cells=frozenset(path_cells or {(0, 0), (1, 0)}),
        spawn_cells=spawn_cells,
        goal_cells=tuple(goal_cells or ((1, 0),)),
        wave_specs=[{spawn_cells[0]: dict(wave)} for wave in wave_specs],
        branch_weights=branch_weights or {},
    )


def test_starts_awaiting_start_on_wave_one():
    level = make_level([{"grunt": 3}])
    manager = WaveManager(level, cell_to_pixel)
    assert manager.state == WaveState.AWAITING_START
    assert manager.current_wave_number == 1
    assert manager.total_waves == 1


def test_wave_one_never_auto_starts_no_matter_how_much_time_passes():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, between_wave_delay=0.1)
    for _ in range(50):
        spawned = manager.update(dt=1.0, active_enemies=[])
        assert spawned == []
    assert manager.state == WaveState.AWAITING_START


def test_skip_delay_starts_the_first_wave_immediately():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, between_wave_delay=100.0)
    assert manager.state == WaveState.AWAITING_START
    manager.skip_delay()
    manager.update(dt=0.01, active_enemies=[])
    assert manager.state == WaveState.SPAWNING


def test_between_wave_delay_gates_the_second_waves_spawn():
    level = make_level([{"grunt": 1}, {"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.01, between_wave_delay=1.0)

    manager.skip_delay()  # player clicks "Start" for wave 1
    manager.update(dt=0.01, active_enemies=[])  # begins wave 1
    manager.update(dt=0.01, active_enemies=[])  # spawns wave 1's one grunt
    manager.update(dt=0.01, active_enemies=[])  # sees it "cleared" -> advances to wave 2
    assert manager.state == WaveState.BETWEEN_WAVES
    assert manager.current_wave_number == 2

    spawned = manager.update(dt=0.5, active_enemies=[])
    assert spawned == []
    assert manager.state == WaveState.BETWEEN_WAVES

    manager.update(dt=0.6, active_enemies=[])
    assert manager.state == WaveState.SPAWNING


def test_skip_delay_during_an_actual_between_wave_countdown_starts_it_immediately():
    # Distinct from skip_delay()'s AWAITING_START branch (every other test
    # above only ever calls it once, for wave 1's initial "Start") -- this
    # is the player clicking "Skip" mid-countdown for a *later* wave.
    level = make_level([{"grunt": 1}, {"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.01, between_wave_delay=100.0)

    manager.skip_delay()
    manager.update(dt=0.01, active_enemies=[])  # begins wave 1
    manager.update(dt=0.01, active_enemies=[])  # spawns wave 1's one grunt
    manager.update(dt=0.01, active_enemies=[])  # sees it "cleared" -> advances to wave 2
    assert manager.state == WaveState.BETWEEN_WAVES
    assert manager.between_wave_timer == 100.0

    manager.skip_delay()
    assert manager.between_wave_timer == 0.0
    manager.update(dt=0.01, active_enemies=[])
    assert manager.state == WaveState.SPAWNING


def test_restore_sets_wave_index_state_and_timer():
    level = make_level([{"grunt": 1}, {"grunt": 1}, {"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel)

    manager.restore(wave_index=1, state=WaveState.BETWEEN_WAVES, between_wave_timer=2.5)

    assert manager.wave_index == 1
    assert manager.current_wave_number == 2
    assert manager.state == WaveState.BETWEEN_WAVES
    assert manager.between_wave_timer == 2.5


def test_restore_into_awaiting_start_is_accepted():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel)

    manager.restore(wave_index=0, state=WaveState.AWAITING_START, between_wave_timer=5.0)

    assert manager.state == WaveState.AWAITING_START


def test_restore_rejects_spawning():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel)

    with pytest.raises(ValueError):
        manager.restore(wave_index=0, state=WaveState.SPAWNING, between_wave_timer=0.0)


def test_restore_rejects_done():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel)

    with pytest.raises(ValueError):
        manager.restore(wave_index=0, state=WaveState.DONE, between_wave_timer=0.0)


def test_restored_wave_continues_normally_afterward():
    level = make_level([{"grunt": 1}, {"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.01, between_wave_delay=0.01)

    manager.restore(wave_index=1, state=WaveState.BETWEEN_WAVES, between_wave_timer=0.005)
    manager.update(dt=0.01, active_enemies=[])  # countdown elapses -> begins wave 2

    assert manager.state == WaveState.SPAWNING
    assert manager.current_wave_number == 2


def test_skip_delay_is_a_no_op_while_a_wave_is_actively_spawning():
    # The HUD's Skip button is only meant to be clickable in
    # AWAITING_START/BETWEEN_WAVES (see ui._draw_wave_countdown_and_skip's
    # `clickable` flag), but Game._handle_click's hit-test doesn't actually
    # gate on that -- so skip_delay() itself has to be a safe no-op here.
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=100.0)
    manager.skip_delay()
    manager.update(dt=0.01, active_enemies=[])  # begins wave 1 -> SPAWNING
    assert manager.state == WaveState.SPAWNING

    manager.skip_delay()

    assert manager.state == WaveState.SPAWNING  # unchanged


def test_spawns_the_exact_enemy_count_for_the_wave():
    level = make_level([{"grunt": 3}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.1, between_wave_delay=0.0)
    manager.skip_delay()  # player clicks "Start"

    all_spawned = []
    for _ in range(50):
        spawned = manager.update(dt=0.05, active_enemies=[])
        all_spawned.extend(spawned)
        if manager.all_waves_complete:
            break

    assert len(all_spawned) == 3
    assert all(isinstance(e, GruntEnemy) for e in all_spawned)
    assert manager.all_waves_complete


def test_wave_does_not_advance_while_spawned_enemies_are_still_active():
    level = make_level([{"grunt": 1}, {"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.01, between_wave_delay=0.0)
    manager.skip_delay()  # player clicks "Start"

    # Drive until the one enemy from wave 1 spawns, then simulate it as
    # still alive on the field.
    still_alive = []
    for _ in range(20):
        spawned = manager.update(dt=0.01, active_enemies=still_alive)
        still_alive.extend(spawned)
        if still_alive:
            break

    assert manager.current_wave_number == 1
    assert manager.state == WaveState.SPAWNING

    # As long as it's reported as still active, the wave must not advance.
    for _ in range(10):
        manager.update(dt=0.01, active_enemies=still_alive)
    assert manager.current_wave_number == 1


def test_progresses_through_multiple_waves_and_flags_completion_only_after_the_last():
    level = make_level([{"grunt": 1}, {"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.01, between_wave_delay=0.0)
    manager.skip_delay()  # player clicks "Start"

    spawned_total = 0
    saw_wave_two_start = False
    for _ in range(50):
        spawned = manager.update(dt=0.01, active_enemies=[])
        spawned_total += len(spawned)
        if manager.current_wave_number == 2:
            saw_wave_two_start = True
        if manager.all_waves_complete:
            break

    assert spawned_total == 2
    assert saw_wave_two_start
    assert manager.all_waves_complete
    assert manager.state == WaveState.DONE


# --- Branching routes (still random -- see pathing.sample_route) ---

def test_branch_weights_bias_which_fork_spawned_enemies_take():
    # A branch at (1, 0) toward two goals -- weight the route so every
    # enemy takes the (2, 0) fork and never the (1, 1) fork.
    level = make_level(
        [{"grunt": 20}],
        path_cells={(0, 0), (1, 0), (2, 0), (1, 1)},
        spawn_cells=((0, 0),),
        goal_cells=((2, 0), (1, 1)),
        branch_weights={((1, 0), (1, 1)): 0.0, ((1, 0), (2, 0)): 1.0},
    )
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0, rng=random.Random(0))
    manager.skip_delay()

    all_spawned = []
    for _ in range(200):
        spawned = manager.update(dt=0.01, active_enemies=[])
        all_spawned.extend(spawned)
        if manager.all_waves_complete:
            break

    assert len(all_spawned) == 20
    for enemy in all_spawned:
        assert enemy.waypoints[-1] == cell_to_pixel(2, 0)


# --- Multi-spawn: per-spawn composition (levels.py) and synchronized timing ---

def _drive_to_completion(manager):
    manager.skip_delay()
    all_spawned = []
    for _ in range(500):
        all_spawned.extend(manager.update(dt=0.01, active_enemies=[]))
        if manager.all_waves_complete:
            break
    return all_spawned


def test_next_wave_preview_aggregates_a_single_spawns_composition():
    level = make_level([{"grunt": 8, "tank": 3}])
    manager = WaveManager(level, cell_to_pixel)

    assert manager.next_wave_preview() == {"grunt": 8, "tank": 3}


def test_next_wave_preview_aggregates_across_multiple_spawns():
    level = Level(
        id=1,
        name="Test Level",
        path_cells=frozenset({(0, 0), (0, 1), (0, 2), (1, 1)}),
        spawn_cells=((0, 0), (0, 2)),
        goal_cells=((1, 1),),
        wave_specs=[{(0, 0): {"grunt": 3}, (0, 2): {"grunt": 2, "tank": 2}}],
    )
    manager = WaveManager(level, cell_to_pixel)

    assert manager.next_wave_preview() == {"grunt": 5, "tank": 2}


def test_next_wave_preview_still_reflects_the_current_wave_while_spawning():
    level = make_level([{"grunt": 3}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0)
    manager.skip_delay()
    manager.update(dt=0.01, active_enemies=[])  # begins wave 1 -> SPAWNING

    assert manager.state == WaveState.SPAWNING
    assert manager.next_wave_preview() == {"grunt": 3}


def test_next_wave_preview_is_none_once_all_waves_complete():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0)
    _drive_to_completion(manager)

    assert manager.all_waves_complete
    assert manager.next_wave_preview() is None


def test_each_spawns_wave_composition_is_honored_independently():
    # Two independent spawns, (0, 0) and (0, 2), merging at (0, 1) before a
    # shared run to the goal -- spawn (0, 0) sends 3 grunts, spawn (0, 2)
    # sends 2 tanks, in the same wave. Which spawn an enemy comes from is
    # decided by wave_specs itself now, not chosen randomly.
    level = Level(
        id=1,
        name="Test Level",
        path_cells=frozenset({(0, 0), (0, 1), (0, 2), (1, 1)}),
        spawn_cells=((0, 0), (0, 2)),
        goal_cells=((1, 1),),
        wave_specs=[{(0, 0): {"grunt": 3}, (0, 2): {"tank": 2}}],
    )
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0)

    all_spawned = _drive_to_completion(manager)

    starts = [enemy.waypoints[0] for enemy in all_spawned]
    assert starts.count(cell_to_pixel(0, 0)) == 3
    assert starts.count(cell_to_pixel(0, 2)) == 2
    assert sum(isinstance(e, GruntEnemy) for e in all_spawned) == 3
    assert sum(isinstance(e, TankEnemy) for e in all_spawned) == 2


def test_a_wave_can_draw_from_only_one_spawn_while_another_sits_it_out():
    # Wave 1 is (0, 0)-only, wave 2 is (0, 2)-only -- a spawn contributing
    # nothing to a given wave is a valid, deliberate level-design choice,
    # not something Level/WaveManager need to treat specially.
    level = Level(
        id=1,
        name="Test Level",
        path_cells=frozenset({(0, 0), (0, 1), (0, 2), (1, 1)}),
        spawn_cells=((0, 0), (0, 2)),
        goal_cells=((1, 1),),
        wave_specs=[{(0, 0): {"grunt": 2}}, {(0, 2): {"grunt": 2}}],
    )
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0)

    all_spawned = _drive_to_completion(manager)

    wave_1_starts = [e.waypoints[0] for e in all_spawned if e.wave_number == 1]
    wave_2_starts = [e.waypoints[0] for e in all_spawned if e.wave_number == 2]
    assert wave_1_starts == [cell_to_pixel(0, 0)] * 2
    assert wave_2_starts == [cell_to_pixel(0, 2)] * 2


def test_each_spawns_first_enemy_emerges_on_the_same_tick():
    # Both spawns have plenty queued -- the very first enemy from each
    # should come out of the same update() call, not one spawn's whole
    # queue draining before the other even starts.
    level = Level(
        id=1,
        name="Test Level",
        path_cells=frozenset({(0, 0), (0, 1), (0, 2), (1, 1)}),
        spawn_cells=((0, 0), (0, 2)),
        goal_cells=((1, 1),),
        wave_specs=[{(0, 0): {"grunt": 3}, (0, 2): {"tank": 3}}],
    )
    manager = WaveManager(level, cell_to_pixel, spawn_interval=1.0, between_wave_delay=0.0)
    manager.skip_delay()
    manager.update(dt=1.0, active_enemies=[])  # BETWEEN_WAVES -> SPAWNING transition; nothing spawns yet

    round_1 = manager.update(dt=1.0, active_enemies=[])

    assert len(round_1) == 2
    assert {e.waypoints[0] for e in round_1} == {cell_to_pixel(0, 0), cell_to_pixel(0, 2)}


def test_every_round_stays_in_lockstep_until_a_spawn_runs_out():
    # (0, 0) has 3 queued, (0, 2) has only 1 -- round 1 is both together,
    # round 2 is (0, 0) alone once (0, 2)'s single enemy has already gone
    # out, not delayed waiting for a round that will never need it again.
    level = Level(
        id=1,
        name="Test Level",
        path_cells=frozenset({(0, 0), (0, 1), (0, 2), (1, 1)}),
        spawn_cells=((0, 0), (0, 2)),
        goal_cells=((1, 1),),
        wave_specs=[{(0, 0): {"grunt": 3}, (0, 2): {"tank": 1}}],
    )
    manager = WaveManager(level, cell_to_pixel, spawn_interval=1.0, between_wave_delay=0.0)
    manager.skip_delay()
    manager.update(dt=1.0, active_enemies=[])  # transition only

    round_1 = manager.update(dt=1.0, active_enemies=[])
    assert len(round_1) == 2
    assert {e.waypoints[0] for e in round_1} == {cell_to_pixel(0, 0), cell_to_pixel(0, 2)}

    round_2 = manager.update(dt=1.0, active_enemies=round_1)
    assert len(round_2) == 1
    assert round_2[0].waypoints[0] == cell_to_pixel(0, 0)

    round_3 = manager.update(dt=1.0, active_enemies=round_1 + round_2)
    assert len(round_3) == 1
    assert round_3[0].waypoints[0] == cell_to_pixel(0, 0)


# --- Difficulty-mode multipliers (see difficulty.py / Game._load_level_object) ---

def test_default_multipliers_leave_a_spawned_enemys_stats_untouched():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0)
    unscaled = GruntEnemy([(0, 0), (64, 0)], wave_number=1)

    spawned = _drive_to_completion(manager)

    assert spawned[0].max_hp == unscaled.max_hp
    assert spawned[0].speed == unscaled.speed
    assert spawned[0].gold_reward == unscaled.gold_reward


def test_enemy_hp_multiplier_scales_a_spawned_enemys_max_hp_and_current_hp():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0,
                           enemy_hp_multiplier=2.0)
    unscaled = GruntEnemy([(0, 0), (64, 0)], wave_number=1)

    spawned = _drive_to_completion(manager)

    assert spawned[0].max_hp == unscaled.max_hp * 2.0
    assert spawned[0].hp == unscaled.max_hp * 2.0


def test_enemy_speed_and_gold_multipliers_scale_a_spawned_enemy():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0,
                           enemy_speed_multiplier=1.5, enemy_gold_multiplier=0.5)
    unscaled = GruntEnemy([(0, 0), (64, 0)], wave_number=1)

    spawned = _drive_to_completion(manager)

    assert spawned[0].speed == unscaled.speed * 1.5
    assert spawned[0].gold_reward == unscaled.gold_reward * 0.5


def test_enemy_speed_multiplier_never_exceeds_max_speed():
    # Regression guard: Enemy.__init__ already clamps its own pre-
    # difficulty speed to max_speed, but _spawn_enemy used to multiply by
    # enemy_speed_multiplier afterward with nothing left to re-clamp it --
    # a wave number high enough to have saturated speed (endless mode, or
    # a late wave) combined with a >1.0 multiplier (Hard) could push speed
    # past max_speed, which would then make a later speed change that
    # itself clamps to max_speed (e.g. BossEnemy's enrage) actually slow
    # the enemy down instead of speeding it up.
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0,
                           enemy_speed_multiplier=100.0)

    spawned = _drive_to_completion(manager)

    assert spawned[0].speed == spawned[0].max_speed


# --- Endless/Survival mode ---

def test_non_endless_still_reaches_done_and_all_waves_complete():
    # Regression guard: the default (endless=False) behavior must be
    # byte-identical to every pre-endless test above.
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0)
    _drive_to_completion(manager)
    assert manager.state == WaveState.DONE
    assert manager.all_waves_complete


def test_clearing_the_final_wave_still_advances_wave_index():
    # Regression guard: current_wave_number (wave_index + 1) must reflect
    # every wave actually cleared, the final one included -- Game.update()
    # relies on it rising to detect a survived wave for its
    # waves_survived achievement counter.
    level = make_level([{"grunt": 1}, {"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0)
    before_final_wave = manager.total_waves  # current_wave_number once wave 2 (the last) begins
    _drive_to_completion(manager)
    assert manager.current_wave_number > before_final_wave


def test_endless_never_reaches_done_or_all_waves_complete():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0, endless=True)
    manager.skip_delay()

    all_spawned = []
    for _ in range(300):
        all_spawned.extend(manager.update(dt=0.01, active_enemies=[]))
        if len(all_spawned) >= 10:
            break

    assert manager.state != WaveState.DONE
    assert manager.all_waves_complete is False
    assert len(all_spawned) >= 10


def test_endless_total_waves_grows_as_waves_are_appended():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0, endless=True)
    manager.skip_delay()
    starting_total = manager.total_waves

    all_spawned = []
    for _ in range(300):
        all_spawned.extend(manager.update(dt=0.01, active_enemies=[]))
        if manager.total_waves > starting_total:
            break

    assert manager.total_waves > starting_total


def test_endless_uses_an_injected_wave_generator():
    generated = []

    def fake_generator(level, wave_number):
        generated.append(wave_number)
        return {(0, 0): {"grunt": 1}}

    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0,
                           endless=True, endless_wave_generator=fake_generator)
    manager.skip_delay()

    for _ in range(50):
        manager.update(dt=0.01, active_enemies=[])
        if generated:
            break

    assert generated == [2]  # level's one authored wave was #1, so the next is #2


def test_default_endless_wave_grows_counts_relative_to_the_previous_wave():
    from waves import _default_endless_wave

    level = make_level([{"grunt": 8}])
    next_wave = _default_endless_wave(level, wave_number=2)
    assert next_wave == {(0, 0): {"grunt": 10}}  # 8 + max(1, 8 // 4) == 10


def test_default_endless_wave_bumps_a_small_count_by_at_least_one():
    from waves import _default_endless_wave

    level = make_level([{"grunt": 1}])
    next_wave = _default_endless_wave(level, wave_number=2)
    assert next_wave == {(0, 0): {"grunt": 2}}


def test_default_endless_wave_compounds_across_repeated_calls():
    from waves import _default_endless_wave

    level = make_level([{"grunt": 8}])
    level.wave_specs.append(_default_endless_wave(level, wave_number=2))  # {"grunt": 10}
    level.wave_specs.append(_default_endless_wave(level, wave_number=3))  # {"grunt": 12}
    assert level.wave_specs[-1] == {(0, 0): {"grunt": 12}}


def test_enemy_hp_multiplier_also_scales_a_shielded_enemys_shield():
    level = make_level([{"shielded": 1}])
    manager = WaveManager(level, cell_to_pixel, spawn_interval=0.0, between_wave_delay=0.0,
                           enemy_hp_multiplier=2.0)
    unscaled = ShieldedEnemy([(0, 0), (64, 0)], wave_number=1)

    spawned = _drive_to_completion(manager)

    assert spawned[0].max_shield == unscaled.max_shield * 2.0
    assert spawned[0].shield == unscaled.max_shield * 2.0
