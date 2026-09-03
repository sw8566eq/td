import pygame
import pytest

from enemy import (
    ENEMY_TYPES,
    BossEnemy,
    Enemy,
    FlyingEnemy,
    GruntEnemy,
    HealerEnemy,
    ScoutEnemy,
    ShieldedEnemy,
    SplitterEnemy,
    TankEnemy,
)

WAYPOINTS = [pygame.Vector2(0, 0), pygame.Vector2(100, 0)]
# A path far too long for any test's dt to actually finish crossing -- for
# tests that call update() with a substantial dt purely to advance timers
# (e.g. shield regen), where reaching the goal partway through would short-
# circuit the very thing being tested.
LONG_WAYPOINTS = [pygame.Vector2(0, 0), pygame.Vector2(10**7, 0)]


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


def test_scout_is_registered_as_fast_and_low_hp():
    assert ENEMY_TYPES["scout"] is ScoutEnemy


def test_tank_is_registered_as_slow_and_high_hp():
    assert ENEMY_TYPES["tank"] is TankEnemy


def test_boss_is_registered():
    assert ENEMY_TYPES["boss"] is BossEnemy


def test_boss_dwarfs_every_regular_species_in_hp_and_reward():
    boss = BossEnemy(WAYPOINTS, wave_number=1)
    for enemy_cls in (GruntEnemy, ScoutEnemy, TankEnemy):
        regular = enemy_cls(WAYPOINTS, wave_number=1)
        assert boss.max_hp > regular.max_hp * 2, enemy_cls
        assert boss.gold_reward > regular.gold_reward * 2, enemy_cls


def test_boss_is_slower_than_every_regular_species():
    boss = BossEnemy(WAYPOINTS, wave_number=1)
    for enemy_cls in (GruntEnemy, ScoutEnemy, TankEnemy):
        regular = enemy_cls(WAYPOINTS, wave_number=1)
        assert boss.speed < regular.speed, enemy_cls


def test_boss_enrages_once_hp_drops_to_the_threshold():
    boss = BossEnemy(WAYPOINTS, wave_number=1)  # max_hp=500, enrage at hp<=250
    base_speed = boss.speed
    boss.take_damage(250)  # hp == 250, exactly at the threshold

    assert boss.enraged is True
    assert boss.speed == pytest.approx(base_speed * BossEnemy.ENRAGE_SPEED_MULTIPLIER)

    # Further damage (still above 0) must not re-trigger/compound the boost.
    boss.take_damage(50)
    assert boss.speed == pytest.approx(base_speed * BossEnemy.ENRAGE_SPEED_MULTIPLIER)


def test_boss_enrage_speed_is_capped_at_max_speed():
    # A late-wave boss is already at (or near) max_speed before enraging --
    # the 1.5x multiplier must never push it past the cap every other
    # speed change in this codebase respects.
    boss = BossEnemy(WAYPOINTS, wave_number=26)  # speed already capped at max_speed
    assert boss.speed == BossEnemy.max_speed
    boss.take_damage(boss.max_hp * 0.6)  # crosses the enrage threshold without killing it
    assert boss.enraged is True
    assert boss.speed == BossEnemy.max_speed


def test_boss_enrage_threshold_uses_live_max_hp_not_a_cached_one():
    # Mirrors what WaveManager._spawn_enemy actually does: scale max_hp/hp
    # for difficulty *after* construction. A threshold baked in at
    # __init__ would silently fire at the wrong HP here.
    boss = BossEnemy(WAYPOINTS, wave_number=1)
    boss.max_hp *= 2.0  # e.g. difficulty's enemy_hp_multiplier
    boss.hp = boss.max_hp

    boss.take_damage(boss.max_hp * 0.6)  # leaves hp at 40% of the *new* max_hp
    assert boss.enraged is True


def test_boss_armor_phase_reduces_flat_damage_until_it_expires():
    boss = BossEnemy(LONG_WAYPOINTS, wave_number=1)  # max_hp=500, armor at hp<=100
    boss.take_damage(400)  # hp == 100 -- crosses both enrage and armor thresholds
    assert boss.armor_used is True
    assert boss.armor_timer == BossEnemy.ARMOR_DURATION

    applied = boss.take_damage(50)  # reduced by ARMOR_FLAT_REDUCTION while armor is active
    assert boss.hp == 100 - (50 - BossEnemy.ARMOR_FLAT_REDUCTION)
    # take_damage()'s return value is what Projectile credits to a tower's
    # damage_dealt stat -- it must reflect the armor-reduced amount that
    # actually landed, not the full nominal hit.
    assert applied == 50 - BossEnemy.ARMOR_FLAT_REDUCTION

    boss.update(dt=BossEnemy.ARMOR_DURATION)  # armor window fully elapses
    assert boss.armor_timer == 0

    hp_before = boss.hp
    applied = boss.take_damage(50)  # full damage now that armor has expired
    assert boss.hp == hp_before - 50
    assert applied == 50


def test_boss_armor_flat_reduction_never_makes_damage_negative():
    boss = BossEnemy(LONG_WAYPOINTS, wave_number=1)
    boss.take_damage(400)  # triggers armor phase
    hp_before = boss.hp
    boss.take_damage(1)  # far less than ARMOR_FLAT_REDUCTION
    assert boss.hp == hp_before  # clamped at 0 damage, not negative


def test_boss_armor_phase_is_a_one_time_effect():
    boss = BossEnemy(LONG_WAYPOINTS, wave_number=1)
    boss.take_damage(450)  # hp == 50, well past the armor threshold
    assert boss.armor_used is True
    boss.update(dt=BossEnemy.ARMOR_DURATION)  # armor window elapses
    assert boss.armor_timer == 0

    boss.take_damage(10)  # still below the armor threshold -- must not re-arm
    assert boss.armor_timer == 0
    assert boss.armor_used is True


def test_boss_take_damage_is_a_no_op_for_dead_or_finished_enemies():
    dead = BossEnemy(WAYPOINTS, wave_number=1)
    dead.take_damage(10_000)
    assert dead.is_dead
    assert dead.enraged is False  # a killing blow has no mechanic left to trigger
    dead.take_damage(1)  # guarded -- must not raise or change state
    assert dead.enraged is False

    finished = BossEnemy(WAYPOINTS, wave_number=1)
    finished.speed = 1000.0
    finished.update(dt=1.0)
    assert finished.reached_goal
    hp_before = finished.hp
    finished.take_damage(1)
    assert finished.hp == hp_before


def test_boss_update_does_not_tick_armor_timer_for_dead_or_finished_enemies():
    dead = BossEnemy(LONG_WAYPOINTS, wave_number=1)
    dead.take_damage(dead.max_hp)  # kill -- armor never triggers on a killing blow
    dead.armor_timer = 2.0  # force a timer as if it had (hypothetically) been armed
    dead.update(dt=10.0)
    assert dead.armor_timer == 2.0  # unchanged -- guarded before ever ticking


def test_boss_draw_shows_a_status_ring_once_enraged():
    from assets import AssetManager
    assets = AssetManager()
    surface = pygame.Surface((100, 100))
    surface.fill((0, 0, 0))

    boss = BossEnemy(WAYPOINTS, wave_number=1)
    boss.pos = pygame.Vector2(50, 50)
    boss.take_damage(300)  # hp == 200 -- past the enrage threshold

    boss.draw(surface, assets)

    ring_y = int(boss.pos.y - (boss.radius + 4))
    assert surface.get_at((int(boss.pos.x), ring_y)) != (0, 0, 0, 255)


def test_boss_draw_omits_the_status_ring_before_any_mechanic_triggers():
    from assets import AssetManager
    assets = AssetManager()
    surface = pygame.Surface((100, 100))
    surface.fill((0, 0, 0))

    boss = BossEnemy(WAYPOINTS, wave_number=1)
    boss.pos = pygame.Vector2(50, 50)

    boss.draw(surface, assets)

    ring_y = int(boss.pos.y - (boss.radius + 4))
    assert surface.get_at((int(boss.pos.x), ring_y)) == (0, 0, 0, 255)


def test_scout_is_faster_and_squishier_than_grunt():
    grunt = GruntEnemy(WAYPOINTS, wave_number=1)
    scout = ScoutEnemy(WAYPOINTS, wave_number=1)
    assert scout.speed > grunt.speed
    assert scout.max_hp < grunt.max_hp


def test_tank_is_slower_and_tougher_than_grunt():
    grunt = GruntEnemy(WAYPOINTS, wave_number=1)
    tank = TankEnemy(WAYPOINTS, wave_number=1)
    assert tank.speed < grunt.speed
    assert tank.max_hp > grunt.max_hp


def test_scout_and_tank_stats_still_scale_up_with_wave_number():
    for enemy_cls in (ScoutEnemy, TankEnemy):
        wave1 = enemy_cls(WAYPOINTS, wave_number=1)
        wave3 = enemy_cls(WAYPOINTS, wave_number=3)
        assert wave3.max_hp > wave1.max_hp, enemy_cls
        assert wave3.gold_reward > wave1.gold_reward, enemy_cls


def test_scout_speed_still_caps_at_its_own_max_speed():
    far_future_wave = ScoutEnemy(WAYPOINTS, wave_number=1000)
    assert far_future_wave.speed == ScoutEnemy.max_speed


def test_every_registered_species_moves_and_can_be_damaged():
    # A light smoke test that every species -- not just the ones singled
    # out above -- behaves like a normal Enemy through the shared logic.
    # max_shield (0 for a species without one, e.g. via getattr's default)
    # has to be spent too -- a shielded species absorbs plain max_hp worth
    # of damage into its shield first and survives.
    for name, enemy_cls in ENEMY_TYPES.items():
        enemy = enemy_cls(WAYPOINTS, wave_number=1)
        enemy.update(dt=0.1)
        assert enemy.distance_traveled > 0, name
        enemy.take_damage(enemy.max_hp + getattr(enemy, "max_shield", 0))
        assert enemy.is_dead, name


def test_flying_enemy_is_flying_and_others_are_not():
    assert FlyingEnemy(WAYPOINTS, wave_number=1).is_flying is True
    for enemy_cls in (GruntEnemy, ScoutEnemy, TankEnemy, BossEnemy, ShieldedEnemy):
        assert enemy_cls(WAYPOINTS, wave_number=1).is_flying is False


def test_shielded_and_flying_are_registered():
    assert ENEMY_TYPES["shielded"] is ShieldedEnemy
    assert ENEMY_TYPES["flying"] is FlyingEnemy


def test_shielded_enemy_shield_absorbs_damage_before_hp():
    enemy = ShieldedEnemy(WAYPOINTS, wave_number=1)
    starting_hp, starting_shield = enemy.hp, enemy.shield

    applied = enemy.take_damage(5)

    assert enemy.shield == starting_shield - 5
    assert enemy.hp == starting_hp
    # A hit fully absorbed by the shield never reaches hp, so the amount
    # take_damage() reports as actually applied -- what Projectile credits
    # to a tower's damage_dealt stat -- must be zero, not the full 5.
    assert applied == 0


def test_shielded_enemy_overflow_damage_spills_into_hp():
    enemy = ShieldedEnemy(WAYPOINTS, wave_number=1)
    starting_hp, starting_shield = enemy.hp, enemy.shield

    applied = enemy.take_damage(starting_shield + 7)

    assert enemy.shield == 0
    assert enemy.hp == starting_hp - 7
    assert applied == 7  # only the overflow past the shield reached hp


def test_shielded_enemy_take_damage_after_shield_is_already_empty_hits_hp_directly():
    enemy = ShieldedEnemy(WAYPOINTS, wave_number=1)
    enemy.take_damage(enemy.max_shield)  # drains it exactly to 0
    assert enemy.shield == 0
    starting_hp = enemy.hp

    enemy.take_damage(9)  # shield already 0 -- skips straight to HP

    assert enemy.shield == 0
    assert enemy.hp == starting_hp - 9


def test_shielded_enemy_shield_regenerates_after_delay():
    enemy = ShieldedEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.take_damage(enemy.max_shield)  # drain the shield entirely
    assert enemy.shield == 0

    enemy.update(dt=enemy.shield_regen_delay - 0.01)
    assert enemy.shield == 0  # not yet -- still within the delay

    enemy.update(dt=0.02)  # crosses the delay threshold -- regen starts this frame
    enemy.update(dt=1.0)
    # Regen only accrues for the portion of elapsed time spent at/above the
    # delay threshold, i.e. these last two update() calls' own dt (0.02 and
    # 1.0) -- not the earlier, below-threshold waiting.
    assert enemy.shield == pytest.approx(enemy.shield_regen_rate * (0.02 + 1.0))


def test_shielded_enemy_shield_regen_resets_on_a_new_hit():
    enemy = ShieldedEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.take_damage(5)
    enemy.update(dt=enemy.shield_regen_delay - 0.01)  # almost ready to regen
    enemy.take_damage(1)  # resets the delay countdown

    enemy.update(dt=0.02)  # would have crossed the old threshold, not the new one

    assert enemy.shield == enemy.max_shield - 6  # unchanged since the second hit


def test_shielded_enemy_shield_never_regenerates_past_max():
    enemy = ShieldedEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.take_damage(1)
    enemy.update(dt=enemy.shield_regen_delay + 100.0)
    assert enemy.shield == enemy.max_shield


def test_shielded_enemy_take_damage_is_a_no_op_for_dead_or_finished_enemies():
    # Mirrors the base Enemy guard test -- ShieldedEnemy's own take_damage
    # override has the identical guard, checked before it ever touches the
    # shield.
    dead = ShieldedEnemy(WAYPOINTS, wave_number=1)
    dead.take_damage(10_000)
    assert dead.is_dead
    shield_before = dead.shield
    dead.take_damage(1)
    assert dead.shield == shield_before

    finished = ShieldedEnemy(WAYPOINTS, wave_number=1)
    finished.speed = 1000.0
    finished.update(dt=1.0)
    assert finished.reached_goal
    shield_before = finished.shield
    finished.take_damage(1)
    assert finished.shield == shield_before


def test_shielded_enemy_update_is_a_no_op_for_dead_or_finished_enemies():
    # Mirrors the base Enemy guard -- shield regen must stop once dead or
    # finished, same as every other per-frame effect.
    dead = ShieldedEnemy(LONG_WAYPOINTS, wave_number=1)
    dead.take_damage(dead.max_shield + dead.max_hp)
    assert dead.is_dead
    dead.update(dt=1000.0)  # would fully regenerate the shield if not guarded
    assert dead.shield == 0

    finished = ShieldedEnemy(WAYPOINTS, wave_number=1)
    finished.speed = 1000.0
    finished.update(dt=1.0)
    assert finished.reached_goal
    finished.take_damage(1)  # dents the shield while still eligible
    shield_after_hit = finished.shield
    finished.update(dt=1000.0)
    assert finished.shield == shield_after_hit  # no regen after reaching the goal


def test_shielded_enemy_draw_shows_a_shield_bar_while_shield_remains():
    from assets import AssetManager
    assets = AssetManager()
    surface = pygame.Surface((100, 100))
    surface.fill((0, 0, 0))

    enemy = ShieldedEnemy(WAYPOINTS, wave_number=1)
    enemy.pos = pygame.Vector2(50, 50)
    enemy.take_damage(5)  # dents the shield, doesn't drain it -- bar still shows

    enemy.draw(surface, assets)  # must not raise, and should draw the shield bar

    bar_y = int(enemy.pos.y - enemy.radius - 4 - 2 - 3 - 2)
    assert surface.get_at((int(enemy.pos.x), bar_y)) != (0, 0, 0, 255)


def test_shielded_enemy_draw_omits_the_shield_bar_once_shield_is_gone():
    from assets import AssetManager
    assets = AssetManager()
    surface = pygame.Surface((100, 100))
    surface.fill((0, 0, 0))

    enemy = ShieldedEnemy(WAYPOINTS, wave_number=1)
    enemy.pos = pygame.Vector2(50, 50)
    enemy.take_damage(enemy.max_shield)  # drains the shield exactly to 0

    bar_y = int(enemy.pos.y - enemy.radius - 4 - 2 - 3 - 2)
    before = surface.get_at((int(enemy.pos.x), bar_y))
    enemy.draw(surface, assets)

    assert surface.get_at((int(enemy.pos.x), bar_y)) == before  # unchanged -- no bar drawn


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


def test_take_damage_records_a_damage_event_for_floating_text():
    # Game.update() drains this each frame into a floating damage number at
    # the enemy's position -- a killing blow still needs to record its own
    # amount (see the guard ordering in take_damage), which
    # test_dead_enemy_ignores_further_damage's follow-up hit above must NOT.
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.take_damage(10)
    enemy.take_damage(5)
    assert enemy.damage_events == [10, 5]

    enemy.take_damage(10_000)  # killing blow -- still recorded
    assert enemy.damage_events[-1] == 10_000

    enemy.take_damage(1)  # already dead -- not recorded
    assert enemy.damage_events[-1] == 10_000


def test_take_damage_is_a_no_op_for_an_enemy_that_reached_the_goal():
    # Matches apply_slow/apply_knockback's guard: every current caller
    # into take_damage (via Projectile) already excludes reached_goal
    # enemies upstream, so this is dormant today, but take_damage is a
    # normal public entry point (tests call it directly, and so could a
    # future hazard tile or damage-over-time effect) -- without this, a
    # direct call on an escaped enemy could flip is_dead to True, and
    # Game.update()'s alive-filter checks is_dead before reached_goal, so
    # it would award gold for an enemy that had already cost a life.
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.speed = 1000.0
    enemy.update(dt=1.0)
    assert enemy.reached_goal
    hp_before = enemy.hp

    enemy.take_damage(10_000)

    assert enemy.hp == hp_before
    assert not enemy.is_dead


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


def test_apply_slow_is_a_no_op_for_dead_or_finished_enemies():
    # Matches apply_knockback's guard: a hit that kills its target still
    # runs the rest of Projectile._apply_hit_effects, so without this an
    # already-dead enemy's slow state would still get mutated.
    dead = GruntEnemy(WAYPOINTS, wave_number=1)
    dead.take_damage(10_000)
    dead.apply_slow(factor=0.1, duration=5.0)
    assert dead.slow_multiplier == 1.0
    assert dead.slow_timer == 0.0

    finished = GruntEnemy(WAYPOINTS, wave_number=1)
    finished.speed = 1000.0
    finished.update(dt=1.0)
    assert finished.reached_goal
    finished.apply_slow(factor=0.1, duration=5.0)
    assert finished.slow_multiplier == 1.0
    assert finished.slow_timer == 0.0


def test_slow_expires_after_its_duration():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.apply_slow(factor=0.5, duration=1.0)
    enemy.update(dt=0.6)
    assert enemy.slow_multiplier == 0.5
    enemy.update(dt=0.6)
    assert enemy.slow_multiplier == 1.0
    assert enemy.slow_timer == 0.0


def test_apply_poison_first_tick_fires_on_the_very_next_update():
    # tick_timer starts at 0 on a fresh application, not tick_interval --
    # so the first tick lands immediately rather than waiting a full
    # interval, regardless of how long that interval is.
    enemy = GruntEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.apply_poison(damage_per_tick=4, tick_interval=10.0, duration=30.0)
    starting_hp = enemy.hp

    enemy.update(dt=0.01)

    assert enemy.hp == starting_hp - 4


def test_apply_poison_ticks_damage_at_interval():
    enemy = GruntEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.apply_poison(damage_per_tick=4, tick_interval=1.0, duration=3.0)
    starting_hp = enemy.hp

    enemy.update(dt=0.1)  # immediate first tick
    assert enemy.hp == starting_hp - 4

    enemy.update(dt=0.5)  # tick_timer 0.9 -> 0.4, not due yet
    assert enemy.hp == starting_hp - 4

    enemy.update(dt=0.5)  # tick_timer 0.4 -> -0.1, due again
    assert enemy.hp == starting_hp - 8


def test_apply_poison_expires_after_duration():
    enemy = GruntEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.apply_poison(damage_per_tick=4, tick_interval=1.0, duration=1.0)
    starting_hp = enemy.hp

    enemy.update(dt=1.5)  # crosses both the tick and the duration in one frame

    assert enemy.hp == starting_hp - 4  # exactly the one tick before it expired
    assert enemy.poison_time_remaining == 0.0
    assert enemy.poison_damage_per_tick == 0.0

    enemy.update(dt=1.0)  # nothing left to tick
    assert enemy.hp == starting_hp - 4


def test_apply_poison_keeps_the_stronger_tick_and_extends_duration():
    # Follows apply_slow's precedent, not apply_knockback's -- see
    # apply_poison's docstring.
    enemy = GruntEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.apply_poison(damage_per_tick=4, tick_interval=1.0, duration=3.0)
    assert enemy.poison_damage_per_tick == 4
    assert enemy.poison_time_remaining == 3.0

    # A weaker tick with a longer duration should extend the duration but
    # keep the stronger (higher) damage_per_tick.
    enemy.apply_poison(damage_per_tick=2, tick_interval=1.0, duration=5.0)
    assert enemy.poison_damage_per_tick == 4
    assert enemy.poison_time_remaining == 5.0

    # A stronger tick should override damage_per_tick.
    enemy.apply_poison(damage_per_tick=10, tick_interval=1.0, duration=1.0)
    assert enemy.poison_damage_per_tick == 10
    assert enemy.poison_time_remaining == 5.0  # shorter duration doesn't shrink it


def test_reapplying_poison_does_not_reset_the_tick_timer():
    # Only a genuinely fresh application (nothing currently active) should
    # zero the tick timer -- a re-hit while already poisoned must not delay
    # a tick that's already due.
    enemy = GruntEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.apply_poison(damage_per_tick=4, tick_interval=1.0, duration=3.0)
    enemy.update(dt=0.9)  # immediate first tick; tick_timer now 1.0 - 0.9 = 0.1
    starting_hp = enemy.hp

    enemy.apply_poison(damage_per_tick=2, tick_interval=1.0, duration=5.0)
    enemy.update(dt=0.05)  # would re-fire immediately if the timer had been reset

    assert enemy.hp == starting_hp  # no new tick yet


def test_apply_poison_is_a_no_op_for_dead_or_finished_enemies():
    dead = GruntEnemy(WAYPOINTS, wave_number=1)
    dead.take_damage(10_000)
    dead.apply_poison(damage_per_tick=4, tick_interval=1.0, duration=3.0)
    assert dead.poison_time_remaining == 0.0
    assert dead.poison_damage_per_tick == 0.0

    finished = GruntEnemy(WAYPOINTS, wave_number=1)
    finished.speed = 1000.0
    finished.update(dt=1.0)
    assert finished.reached_goal
    finished.apply_poison(damage_per_tick=4, tick_interval=1.0, duration=3.0)
    assert finished.poison_time_remaining == 0.0


def test_poison_tick_on_a_shielded_enemy_is_absorbed_by_shield_first():
    # apply_poison's tick calls take_damage() polymorphically, so
    # ShieldedEnemy's own override absorbs poison the same as any other
    # hit, with no extra code needed for the interaction.
    enemy = ShieldedEnemy(LONG_WAYPOINTS, wave_number=1)
    starting_hp, starting_shield = enemy.hp, enemy.shield
    enemy.apply_poison(damage_per_tick=4, tick_interval=1.0, duration=1.0)

    enemy.update(dt=0.1)  # immediate first tick

    assert enemy.shield == starting_shield - 4
    assert enemy.hp == starting_hp


def test_poison_tick_can_kill_and_stops_further_movement_that_frame():
    enemy = GruntEnemy(LONG_WAYPOINTS, wave_number=1)
    enemy.apply_poison(damage_per_tick=enemy.hp, tick_interval=1.0, duration=1.0)

    enemy.update(dt=0.1)

    assert enemy.is_dead
    assert enemy.hp == 0


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


def test_apply_knockback_does_not_move_the_enemy_instantly():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.speed = 40.0
    enemy.update(dt=1.0)  # pos (40, 0), distance_traveled 40

    enemy.apply_knockback(15)

    # Queued, not applied yet -- the slide plays out over update() calls.
    assert enemy.distance_traveled == 40
    assert enemy.pos.x == pytest.approx(40.0)
    assert enemy.knockback_remaining == 15


def test_apply_knockback_animates_the_slide_over_multiple_ticks():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.speed = 40.0
    enemy.knockback_speed = 100.0  # px/sec, chosen so this needs >1 tick
    enemy.update(dt=1.0)  # distance_traveled 40

    enemy.apply_knockback(15)
    enemy.update(dt=0.05)  # one small tick: 100 * 0.05 = 5px of the slide

    assert enemy.distance_traveled == pytest.approx(35.0)
    assert enemy.knockback_remaining == pytest.approx(10.0)

    enemy.update(dt=0.05)  # another 5px
    assert enemy.distance_traveled == pytest.approx(30.0)
    assert enemy.knockback_remaining == pytest.approx(5.0)

    enemy.update(dt=0.05)  # final 5px -- slide finishes
    assert enemy.distance_traveled == pytest.approx(25.0)
    assert enemy.knockback_remaining == pytest.approx(0.0)
    assert enemy.pos.x == pytest.approx(25.0)
    assert enemy.wp_index == 1


def test_enemy_does_not_advance_forward_while_a_knockback_is_playing_out():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.speed = 40.0
    enemy.update(dt=1.0)  # distance_traveled 40

    enemy.apply_knockback(15)
    distance_before = enemy.distance_traveled
    enemy.update(dt=0.01)  # still knocking back, not walking forward

    assert enemy.distance_traveled < distance_before  # moved back, not forward


def test_apply_knockback_can_cross_back_over_a_waypoint_boundary():
    waypoints = [pygame.Vector2(0, 0), pygame.Vector2(100, 0), pygame.Vector2(200, 0)]
    enemy = GruntEnemy(waypoints, wave_number=1)
    enemy.speed = 40.0
    enemy.update(dt=1.0)  # (40, 0)
    enemy.update(dt=1.0)  # (80, 0)
    enemy.update(dt=0.5)  # snaps to waypoint 1: (100, 0), distance 100, wp_index 2
    enemy.update(dt=1.0)  # (140, 0), distance 140, into segment 2

    enemy.apply_knockback(60)  # will rewind to distance 80 -- back on segment 1
    enemy.update(dt=60.0 / enemy.knockback_speed)  # let the whole slide play out

    assert enemy.distance_traveled == pytest.approx(80.0)
    assert enemy.pos.x == pytest.approx(80.0)
    assert enemy.wp_index == 1


def test_apply_knockback_can_rewind_across_more_than_one_earlier_segment():
    # A short first segment (50) followed by a much longer second one (150)
    # -- landing back in the second segment means _seek_to_distance's walk
    # has to pass all the way through (and past) the first segment without
    # stopping there, exercising its "keep walking" branch, not just the
    # "stop here" one every other knockback test happens to land on.
    waypoints = [pygame.Vector2(0, 0), pygame.Vector2(50, 0), pygame.Vector2(200, 0)]
    enemy = GruntEnemy(waypoints, wave_number=1)
    enemy.speed = 50.0
    enemy.update(dt=1.0)  # snaps to waypoint 1: (50, 0), distance 50, wp_index 2
    enemy.update(dt=1.0)  # (100, 0), distance 100, into segment 2
    enemy.update(dt=1.0)  # (150, 0), distance 150

    enemy.apply_knockback(50)  # rewind to distance 100 -- still on segment 2
    enemy.update(dt=50.0 / enemy.knockback_speed)  # let the whole slide play out

    assert enemy.distance_traveled == pytest.approx(100.0)
    assert enemy.pos.x == pytest.approx(100.0)
    assert enemy.wp_index == 2


def test_apply_knockback_on_a_single_waypoint_path_has_nowhere_to_go():
    # _seek_to_distance's degenerate fallback: a one-waypoint "path" (never
    # produced by a real level, but not something apply_knockback itself
    # assumes can't happen) has no segment to walk at all.
    enemy = GruntEnemy([pygame.Vector2(5, 5)], wave_number=1)
    enemy.apply_knockback(10)

    enemy.update(dt=1.0)

    assert enemy.pos == pygame.Vector2(5, 5)
    assert enemy.wp_index == 1
    assert enemy.knockback_remaining == 0.0


def test_apply_knockback_clamps_at_the_start_of_the_path_and_drops_the_rest():
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.speed = 40.0
    enemy.update(dt=1.0)  # distance_traveled 40

    enemy.apply_knockback(1000)
    enemy.update(dt=1.0)  # far more than enough time to reach the start

    assert enemy.distance_traveled == 0
    assert enemy.pos.x == pytest.approx(0.0)
    assert enemy.wp_index == 1
    assert enemy.knockback_remaining == 0.0  # leftover shove discarded, not stuck pending


def test_apply_knockback_is_a_no_op_for_dead_or_finished_enemies():
    dead = GruntEnemy(WAYPOINTS, wave_number=1)
    dead.take_damage(10_000)
    dead.apply_knockback(50)
    assert dead.knockback_remaining == 0.0
    dead.update(dt=1.0)
    assert dead.distance_traveled == 0  # never moved, knockback ignored

    finished = GruntEnemy(WAYPOINTS, wave_number=1)
    finished.speed = 1000.0
    finished.update(dt=1.0)
    assert finished.reached_goal
    finished.apply_knockback(50)
    assert finished.knockback_remaining == 0.0
    finished.update(dt=1.0)
    assert finished.pos.x == 100.0  # unchanged, still at the goal


# --- Splitter enemy ---

def test_splitter_is_registered():
    assert ENEMY_TYPES["splitter"] is SplitterEnemy


def test_splitter_starts_with_no_pending_spawns():
    splitter = SplitterEnemy(WAYPOINTS, wave_number=1)
    assert splitter.pending_spawns == []


def test_splitter_death_queues_its_children_as_pending_spawns():
    splitter = SplitterEnemy(WAYPOINTS, wave_number=1)
    splitter.take_damage(splitter.max_hp)  # a killing blow
    assert splitter.is_dead
    assert len(splitter.pending_spawns) == SplitterEnemy.SPLIT_COUNT
    for child in splitter.pending_spawns:
        assert not isinstance(child, SplitterEnemy)  # no further splitting
        assert not child.is_dead


def test_splitter_children_continue_from_the_same_point_along_the_route():
    splitter = SplitterEnemy(LONG_WAYPOINTS, wave_number=1)
    splitter.update(dt=1.0)  # walk partway down the route first
    distance_at_death = splitter.distance_traveled
    splitter.take_damage(splitter.max_hp)

    for child in splitter.pending_spawns:
        assert child.distance_traveled == pytest.approx(distance_at_death)
        assert tuple(child.pos) == pytest.approx(tuple(splitter.pos))


def test_splitter_does_not_split_twice_from_a_multi_hit_killing_blow():
    # A splash/chain hit can call take_damage() again on an enemy that's
    # already dead but not yet pruned from Game.enemies within the same
    # frame -- must not queue a second batch of children.
    splitter = SplitterEnemy(WAYPOINTS, wave_number=1)
    splitter.take_damage(splitter.max_hp)
    splitter.take_damage(10)  # already dead -- take_damage() itself is a no-op
    assert len(splitter.pending_spawns) == SplitterEnemy.SPLIT_COUNT


def test_non_splitter_enemies_never_queue_pending_spawns():
    for name, enemy_cls in ENEMY_TYPES.items():
        if name == "splitter":
            continue
        enemy = enemy_cls(WAYPOINTS, wave_number=1)
        enemy.take_damage(enemy.max_hp + getattr(enemy, "max_shield", 0))
        assert enemy.pending_spawns == [], name


# --- Healer enemy ---

def test_healer_is_registered():
    assert ENEMY_TYPES["healer"] is HealerEnemy


def test_healer_heals_a_damaged_ally_in_range():
    healer = HealerEnemy(WAYPOINTS, wave_number=1)
    ally = GruntEnemy(WAYPOINTS, wave_number=1)
    ally.hp = ally.max_hp - 20
    ally.pos = pygame.Vector2(healer.pos)  # well within heal_range

    healer.update(dt=1.0, enemies=[healer, ally])

    assert ally.hp == pytest.approx(ally.max_hp - 20 + HealerEnemy.heal_rate * 1.0)


def test_healer_never_heals_past_max_hp():
    # LONG_WAYPOINTS, not WAYPOINTS: super().update() moves the healer
    # itself before the heal loop runs, both because a large dt on a short
    # path would walk it off the end into reached_goal (short-circuiting
    # the heal loop before it runs at all) and because moving too far from
    # where ally.pos was fixed beforehand would carry it out of heal_range.
    # dt=1.0 keeps that movement (speed * dt = 50px) well inside
    # heal_range (90px) while still granting far more healing (heal_rate *
    # dt = 6hp) than ally's 1hp deficit, so the cap is what's under test.
    healer = HealerEnemy(LONG_WAYPOINTS, wave_number=1)
    ally = GruntEnemy(WAYPOINTS, wave_number=1)
    ally.hp = ally.max_hp - 1
    ally.pos = pygame.Vector2(healer.pos)

    healer.update(dt=1.0, enemies=[healer, ally])

    assert ally.hp == ally.max_hp


def test_healer_does_not_heal_an_ally_out_of_range():
    healer = HealerEnemy(WAYPOINTS, wave_number=1)
    ally = GruntEnemy(WAYPOINTS, wave_number=1)
    ally.hp = ally.max_hp - 20
    ally.pos = pygame.Vector2(healer.pos.x + HealerEnemy.heal_range * 10, healer.pos.y)

    healer.update(dt=1.0, enemies=[healer, ally])

    assert ally.hp == ally.max_hp - 20


def test_healer_never_heals_itself_via_the_aura_loop():
    healer = HealerEnemy(WAYPOINTS, wave_number=1)
    healer.hp = healer.max_hp - 20

    healer.update(dt=1.0, enemies=[healer])

    assert healer.hp == healer.max_hp - 20  # its own update() only moves/ages it, never heals it


def test_healer_does_not_heal_dead_or_escaped_allies():
    healer = HealerEnemy(WAYPOINTS, wave_number=1)
    dead_ally = GruntEnemy(WAYPOINTS, wave_number=1)
    dead_ally.pos = pygame.Vector2(healer.pos)
    dead_ally.take_damage(dead_ally.max_hp)  # is_dead, hp already 0

    escaped_ally = GruntEnemy(WAYPOINTS, wave_number=1)
    escaped_ally.speed = 1000.0
    escaped_ally.update(dt=1.0)
    assert escaped_ally.reached_goal
    escaped_ally.pos = pygame.Vector2(healer.pos)
    escaped_ally.hp = escaped_ally.max_hp - 20

    healer.update(dt=1.0, enemies=[healer, dead_ally, escaped_ally])

    assert dead_ally.hp == 0
    assert escaped_ally.hp == escaped_ally.max_hp - 20


def test_receive_heal_is_a_no_op_for_dead_or_finished_enemies():
    dead = GruntEnemy(WAYPOINTS, wave_number=1)
    dead.take_damage(dead.max_hp)
    dead.receive_heal(1000)
    assert dead.hp == 0

    finished = GruntEnemy(WAYPOINTS, wave_number=1)
    finished.speed = 1000.0
    finished.update(dt=1.0)
    assert finished.reached_goal
    hp_before = finished.hp
    finished.receive_heal(1000)
    assert finished.hp == hp_before


def test_enemy_update_still_works_with_no_enemies_argument():
    # Every direct enemy.update(dt) call elsewhere in this suite (and in
    # game code outside Game.update()'s own two-pass loop) relies on
    # enemies defaulting to None rather than being required.
    enemy = GruntEnemy(WAYPOINTS, wave_number=1)
    enemy.update(dt=0.1)
    assert enemy.distance_traveled > 0
