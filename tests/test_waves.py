from enemy import GruntEnemy
from levels import Level
from waves import WaveManager, WaveState


def make_level(wave_specs, waypoints_tiles=None):
    return Level(
        id=1,
        name="Test Level",
        waypoints_tiles=waypoints_tiles or [(0, 0), (1, 0)],
        wave_specs=wave_specs,
    )


def test_starts_between_waves_on_wave_one():
    level = make_level([{"grunt": 3}])
    manager = WaveManager(level, waypoints_px=[(0, 0), (64, 0)])
    assert manager.state == WaveState.BETWEEN_WAVES
    assert manager.current_wave_number == 1
    assert manager.total_waves == 1


def test_between_wave_delay_gates_the_first_spawn():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, waypoints_px=[(0, 0), (64, 0)], between_wave_delay=1.0)

    spawned = manager.update(dt=0.5, active_enemies=[])
    assert spawned == []
    assert manager.state == WaveState.BETWEEN_WAVES

    manager.update(dt=0.6, active_enemies=[])
    assert manager.state == WaveState.SPAWNING


def test_skip_delay_starts_the_wave_immediately():
    level = make_level([{"grunt": 1}])
    manager = WaveManager(level, waypoints_px=[(0, 0), (64, 0)], between_wave_delay=100.0)
    manager.skip_delay()
    manager.update(dt=0.01, active_enemies=[])
    assert manager.state == WaveState.SPAWNING


def test_spawns_the_exact_enemy_count_for_the_wave():
    level = make_level([{"grunt": 3}])
    manager = WaveManager(level, waypoints_px=[(0, 0), (64, 0)], spawn_interval=0.1, between_wave_delay=0.0)

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
    manager = WaveManager(level, waypoints_px=[(0, 0), (64, 0)], spawn_interval=0.01, between_wave_delay=0.0)

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
    manager = WaveManager(level, waypoints_px=[(0, 0), (64, 0)], spawn_interval=0.01, between_wave_delay=0.0)

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
