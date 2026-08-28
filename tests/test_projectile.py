import pygame

from projectile import Projectile


class FakeEnemy:
    def __init__(self, pos, is_dead=False, reached_goal=False, speed=50.0):
        self.pos = pygame.Vector2(pos)
        self.is_dead = is_dead
        self.reached_goal = reached_goal
        self.speed = speed
        self.damage_taken = 0
        self.slow_applied = None
        self.knockback_applied = None
        self.poison_applied = None

    def take_damage(self, amount):
        self.damage_taken += amount

    def apply_slow(self, factor, duration):
        self.slow_applied = (factor, duration)

    def apply_knockback(self, distance):
        self.knockback_applied = distance

    def apply_poison(self, damage_per_tick, tick_interval, duration):
        self.poison_applied = (damage_per_tick, tick_interval, duration)


def test_direct_hit_damages_only_the_target():
    target = FakeEnemy((0, 0))
    bystander = FakeEnemy((1, 1))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10)

    projectile.update(dt=1.0, enemies=[target, bystander])

    assert target.damage_taken == 10
    assert bystander.damage_taken == 0
    assert projectile.dead


def test_projectile_homes_toward_target_before_impact():
    target = FakeEnemy((100, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=10, damage=10)

    projectile.update(dt=1.0, enemies=[target])

    assert not projectile.dead
    assert target.damage_taken == 0
    assert projectile.pos.x == 10


def test_splash_damages_everyone_within_radius_including_target():
    target = FakeEnemy((0, 0))
    in_radius = FakeEnemy((10, 0))
    out_of_radius = FakeEnemy((1000, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=15, splash_radius=20)

    projectile.update(dt=1.0, enemies=[target, in_radius, out_of_radius])

    assert target.damage_taken == 15
    assert in_radius.damage_taken == 15
    assert out_of_radius.damage_taken == 0


def test_splash_skips_an_enemy_that_reached_the_goal():
    target = FakeEnemy((0, 0))
    gone = FakeEnemy((10, 0), reached_goal=True)
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=15, splash_radius=20)

    projectile.update(dt=1.0, enemies=[target, gone])

    assert target.damage_taken == 15
    assert gone.damage_taken == 0


def test_slow_effect_applied_on_direct_hit():
    target = FakeEnemy((0, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=4, slow_effect=(0.5, 2.0),
    )

    projectile.update(dt=1.0, enemies=[target])

    assert target.slow_applied == (0.5, 2.0)


def test_poison_effect_applied_on_direct_hit():
    target = FakeEnemy((0, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=3, poison_effect=(4, 0.5, 3.0),
    )

    projectile.update(dt=1.0, enemies=[target])

    assert target.damage_taken == 3
    assert target.poison_applied == (4, 0.5, 3.0)


def test_no_poison_when_effect_is_none():
    target = FakeEnemy((0, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10)

    projectile.update(dt=1.0, enemies=[target])

    assert target.poison_applied is None


def test_update_on_an_already_dead_projectile_is_a_no_op():
    target = FakeEnemy((100, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=10, damage=10)
    projectile.dead = True

    projectile.update(dt=1.0, enemies=[target])

    assert projectile.pos == pygame.Vector2(0, 0)  # never moved
    assert target.damage_taken == 0


def test_target_dying_before_impact_makes_projectile_a_dud():
    target = FakeEnemy((100, 0), is_dead=True)
    projectile = Projectile(pos=(0, 0), target=target, speed=10, damage=10)

    projectile.update(dt=1.0, enemies=[target])

    assert projectile.dead
    assert target.damage_taken == 0


def test_target_reaching_the_goal_before_impact_makes_projectile_a_dud():
    # Regression test: a target's pos freezes once it reaches the goal
    # (Enemy.update returns early), so without this check an in-flight
    # projectile would keep homing in on wherever it stopped and "hit" an
    # enemy that's already left the level, instead of duding out like it
    # already does when the target dies before impact.
    target = FakeEnemy((100, 0), reached_goal=True)
    projectile = Projectile(pos=(0, 0), target=target, speed=10, damage=10)

    projectile.update(dt=1.0, enemies=[target])

    assert projectile.dead
    assert target.damage_taken == 0


def test_knockback_pushes_target_back_by_its_speed_times_duration():
    target = FakeEnemy((0, 0), speed=80.0)
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=6, knockback_duration=1.5,
    )

    projectile.update(dt=1.0, enemies=[target])

    assert target.knockback_applied == 80.0 * 1.5


def test_no_knockback_call_when_duration_is_zero():
    target = FakeEnemy((0, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=6)

    projectile.update(dt=1.0, enemies=[target])

    assert target.knockback_applied is None


def test_splash_knockback_applies_to_every_enemy_hit():
    target = FakeEnemy((0, 0), speed=50.0)
    in_radius = FakeEnemy((10, 0), speed=100.0)
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=5,
        splash_radius=20, knockback_duration=2.0,
    )

    projectile.update(dt=1.0, enemies=[target, in_radius])

    assert target.knockback_applied == 50.0 * 2.0
    assert in_radius.knockback_applied == 100.0 * 2.0


def test_chain_hits_the_nearest_unvisited_enemy_first():
    target = FakeEnemy((0, 0))
    near = FakeEnemy((10, 0))
    far = FakeEnemy((40, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=7,
        chain_range=50, max_chain_targets=2,
    )

    projectile.update(dt=1.0, enemies=[target, near, far])

    assert target.damage_taken == 7
    assert near.damage_taken == 7  # closer than far, so it's the one 2nd hit uses
    assert far.damage_taken == 0  # max_chain_targets used up before reaching it


def test_chain_jumps_from_the_newly_hit_enemy_not_the_original_target():
    target = FakeEnemy((0, 0))
    mid = FakeEnemy((40, 0))    # 40 from target -- in range of target
    far = FakeEnemy((90, 0))    # 90 from target (out of range), 50 from mid (in range)
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=5,
        chain_range=50, max_chain_targets=3,
    )

    projectile.update(dt=1.0, enemies=[target, mid, far])

    assert target.damage_taken == 5
    assert mid.damage_taken == 5
    assert far.damage_taken == 5  # only reachable because the anchor moved to mid


def test_chain_stops_at_max_chain_targets_even_with_more_in_range():
    target = FakeEnemy((0, 0))
    a = FakeEnemy((10, 0))
    b = FakeEnemy((20, 0))
    c = FakeEnemy((30, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=3,
        chain_range=100, max_chain_targets=2,
    )

    projectile.update(dt=1.0, enemies=[target, a, b, c])

    assert target.damage_taken == 3
    assert a.damage_taken == 3
    assert b.damage_taken == 0
    assert c.damage_taken == 0


def test_chain_with_no_cap_hits_every_reachable_enemy_in_a_line():
    target = FakeEnemy((0, 0))
    chain = [FakeEnemy((10 * i, 0)) for i in range(1, 21)]  # 20 enemies, 10 apart
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=2,
        chain_range=15, max_chain_targets=float("inf"),
    )

    projectile.update(dt=1.0, enemies=[target] + chain)

    assert target.damage_taken == 2
    assert all(e.damage_taken == 2 for e in chain)


def test_chain_stops_when_no_unvisited_enemy_is_in_range():
    target = FakeEnemy((0, 0))
    near = FakeEnemy((10, 0))
    far_away = FakeEnemy((10_000, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=4,
        chain_range=15, max_chain_targets=10,
    )

    projectile.update(dt=1.0, enemies=[target, near, far_away])

    assert target.damage_taken == 4
    assert near.damage_taken == 4
    assert far_away.damage_taken == 0


def test_chain_never_hits_the_same_enemy_twice():
    target = FakeEnemy((0, 0))
    only_neighbor = FakeEnemy((10, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=6,
        chain_range=100, max_chain_targets=10,  # far more than there are enemies to hit
    )

    projectile.update(dt=1.0, enemies=[target, only_neighbor])

    assert target.damage_taken == 6  # hit exactly once, not repeatedly
    assert only_neighbor.damage_taken == 6


def test_chain_skips_already_dead_enemies():
    target = FakeEnemy((0, 0))
    already_dead = FakeEnemy((10, 0), is_dead=True)
    alive = FakeEnemy((15, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=9,
        chain_range=100, max_chain_targets=3,
    )

    projectile.update(dt=1.0, enemies=[target, already_dead, alive])

    assert target.damage_taken == 9
    assert already_dead.damage_taken == 0
    assert alive.damage_taken == 9


def test_chain_skips_enemies_that_reached_the_goal():
    target = FakeEnemy((0, 0))
    gone = FakeEnemy((10, 0), reached_goal=True)
    alive = FakeEnemy((15, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=9,
        chain_range=100, max_chain_targets=3,
    )

    projectile.update(dt=1.0, enemies=[target, gone, alive])

    assert target.damage_taken == 9
    assert gone.damage_taken == 0
    assert alive.damage_taken == 9


def test_no_chain_when_chain_range_is_zero():
    target = FakeEnemy((0, 0))
    neighbor = FakeEnemy((5, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10)

    projectile.update(dt=1.0, enemies=[target, neighbor])

    assert target.damage_taken == 10
    assert neighbor.damage_taken == 0


# --- Source attribution (post-level results screen -- see ui.compute_tower_results) ---

class FakeTower:
    """Just the 4 counters Projectile writes into, plus nothing else --
    real attribution logic lives entirely in Projectile, not Tower."""
    def __init__(self):
        self.shots_fired = 0
        self.shots_hit = 0
        self.damage_dealt = 0.0
        self.kills = 0


class KillableFakeEnemy(FakeEnemy):
    """FakeEnemy doesn't track hp/death at all (its take_damage() just
    accumulates a counter) -- this variant actually flips is_dead once
    enough damage lands, so kill-counting can be tested against it."""
    def __init__(self, pos, hp, **kwargs):
        super().__init__(pos, **kwargs)
        self.hp = hp

    def take_damage(self, amount):
        super().take_damage(amount)
        self.hp -= amount
        if self.hp <= 0:
            self.is_dead = True


def test_source_none_is_never_touched_by_a_hit():
    target = FakeEnemy((0, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10, source=None)
    projectile.update(dt=1.0, enemies=[target])  # must not raise -- no source to update


def test_direct_hit_attributes_one_shot_hit_and_its_damage_to_the_source():
    source = FakeTower()
    target = FakeEnemy((0, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10, source=source)

    projectile.update(dt=1.0, enemies=[target])

    assert source.shots_hit == 1
    assert source.damage_dealt == 10
    assert source.kills == 0


def test_direct_hit_that_kills_increments_kills_once():
    source = FakeTower()
    target = KillableFakeEnemy((0, 0), hp=5)
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10, source=source)

    projectile.update(dt=1.0, enemies=[target])

    assert target.is_dead
    assert source.kills == 1
    assert source.damage_dealt == 10


def test_a_dud_that_never_connects_does_not_count_as_a_hit():
    source = FakeTower()
    target = FakeEnemy((100, 0), is_dead=True)  # already dead before impact
    projectile = Projectile(pos=(0, 0), target=target, speed=10, damage=10, source=source)

    projectile.update(dt=1.0, enemies=[target])

    assert source.shots_hit == 0
    assert source.damage_dealt == 0


def test_splash_counts_one_shot_hit_but_cumulative_damage_across_every_enemy_touched():
    source = FakeTower()
    target = FakeEnemy((0, 0))
    in_radius = FakeEnemy((10, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=15,
                             splash_radius=20, source=source)

    projectile.update(dt=1.0, enemies=[target, in_radius])

    assert source.shots_hit == 1  # one shot, not two, even though it hit two enemies
    assert source.damage_dealt == 30  # 15 to each


def test_splash_counts_a_kill_for_each_enemy_actually_killed():
    source = FakeTower()
    target = KillableFakeEnemy((0, 0), hp=5)
    in_radius = KillableFakeEnemy((10, 0), hp=5)
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=15,
                             splash_radius=20, source=source)

    projectile.update(dt=1.0, enemies=[target, in_radius])

    assert source.kills == 2


def test_chain_counts_one_shot_hit_but_cumulative_damage_across_every_link():
    source = FakeTower()
    target = FakeEnemy((0, 0))
    near = FakeEnemy((10, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=7,
                             chain_range=50, max_chain_targets=2, source=source)

    projectile.update(dt=1.0, enemies=[target, near])

    assert source.shots_hit == 1
    assert source.damage_dealt == 14  # 7 to target + 7 to the one chain link


# --- impact_events (drained by Game.update() into visual "juice" effects) ---

def test_direct_hit_records_one_impact_event_with_no_splash_radius():
    target = FakeEnemy((5, 5))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10)

    projectile.update(dt=1.0, enemies=[target])

    assert projectile.impact_events == [(pygame.Vector2(5, 5), None)]


def test_splash_hit_records_one_impact_event_with_its_splash_radius():
    target = FakeEnemy((5, 5))
    bystander = FakeEnemy((10, 5))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10, splash_radius=20)

    projectile.update(dt=1.0, enemies=[target, bystander])

    # Exactly one event -- once per projectile resolving, not once per
    # enemy actually touched (same counting shots_hit already uses).
    assert projectile.impact_events == [(pygame.Vector2(5, 5), 20)]


def test_chain_hit_records_one_impact_event_at_the_original_impact_point():
    target = FakeEnemy((5, 5))
    near = FakeEnemy((15, 5))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=7,
                             chain_range=50, max_chain_targets=2)

    projectile.update(dt=1.0, enemies=[target, near])

    assert projectile.impact_events == [(pygame.Vector2(5, 5), None)]


def test_a_dud_that_never_connects_records_no_impact_event():
    target = FakeEnemy((5, 5), is_dead=True)
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10)

    projectile.update(dt=1.0, enemies=[target])

    assert projectile.dead
    assert projectile.impact_events == []
