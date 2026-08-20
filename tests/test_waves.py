import random

from enemy import GruntEnemy, TankEnemy
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
