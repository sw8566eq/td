import pygame

from enemy import Enemy, GruntEnemy

WAYPOINTS = [pygame.Vector2(0, 0), pygame.Vector2(100, 0)]


def test_stats_scale_up_with_wave_number():
    wave1 = GruntEnemy(WAYPOINTS, wave_number=1)
    wave3 = GruntEnemy(WAYPOINTS, wave_number=3)
    assert wave3.max_hp > wave1.max_hp
    assert wave3.gold_reward > wave1.gold_reward
    assert wave3.max_hp == wave1.max_hp + Enemy.hp_per_wave * 2
    assert wave3.gold_reward == wave1.gold_reward + Enemy.reward_per_wave * 2


def test_speed_is_capped_at_max_speed():
    far_future_wave = GruntEnemy(WAYPOINTS, wave_number=1000)
    assert far_future_wave.speed == Enemy.max_speed


def test_take_damage_reduces_hp_and_marks_dead_at_zero():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    starting_hp = enemy.hp
    enemy.take_damage(10)
    assert enemy.hp == starting_hp - 10
    assert not enemy.is_dead

    enemy.take_damage(10_000)
    assert enemy.hp == 0
    assert enemy.is_dead


def test_dead_enemy_ignores_further_damage():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.take_damage(10_000)
    assert enemy.is_dead
    enemy.take_damage(1)
    assert enemy.hp == 0


def test_apply_slow_keeps_stronger_of_current_and_new():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.apply_slow(factor=0.7, duration=1.0)
    assert enemy.slow_multiplier == 0.7
    assert enemy.slow_timer == 1.0

    # A weaker slow with a longer duration should refresh the duration but
    # keep the stronger (lower) multiplier.
    enemy.apply_slow(factor=0.9, duration=3.0)
    assert enemy.slow_multiplier == 0.7
    assert enemy.slow_timer == 3.0

    # A stronger slow should override the multiplier.
    enemy.apply_slow(factor=0.3, duration=0.5)
    assert enemy.slow_multiplier == 0.3
    assert enemy.slow_timer == 3.0


def test_slow_expires_after_its_duration():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.apply_slow(factor=0.5, duration=1.0)
    enemy.update(dt=0.6)
    assert enemy.slow_multiplier == 0.5
    enemy.update(dt=0.6)
    assert enemy.slow_multiplier == 1.0
    assert enemy.slow_timer == 0.0


def test_enemy_moves_toward_next_waypoint_and_tracks_distance():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.speed = 50.0
    enemy.update(dt=1.0)
    assert enemy.pos.x == 50.0
    assert enemy.distance_traveled == 50.0
    assert not enemy.reached_goal


def test_enemy_reaches_goal_after_last_waypoint():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.speed = 1000.0  # far more than needed to cross in one tick
    enemy.update(dt=1.0)
    assert enemy.reached_goal
    assert enemy.pos.x == 100.0
