import pygame

from tower import BasicTower


class FakeEnemy:
    """A minimal stand-in with just the attributes Tower.acquire_target
    reads -- avoids needing a real path/waypoints for these tests."""

    def __init__(self, pos, distance_traveled=0.0, is_dead=False, reached_goal=False):
        self.pos = pygame.Vector2(pos)
        self.distance_traveled = distance_traveled
        self.is_dead = is_dead
        self.reached_goal = reached_goal


def make_tower(range_=100):
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.range = range_
    return tower


def test_in_range_true_within_radius_false_outside():
    tower = make_tower(range_=50)
    assert tower.in_range(FakeEnemy((30, 0)))
    assert not tower.in_range(FakeEnemy((51, 0)))


def test_acquire_target_returns_none_when_no_enemies_in_range():
    tower = make_tower(range_=50)
    assert tower.acquire_target([FakeEnemy((1000, 0))]) is None


def test_acquire_target_ignores_dead_enemies():
    tower = make_tower(range_=100)
    dead = FakeEnemy((10, 0), distance_traveled=999, is_dead=True)
    alive = FakeEnemy((10, 0), distance_traveled=1)
    assert tower.acquire_target([dead, alive]) is alive


def test_acquire_target_picks_furthest_progressed_not_nearest():
    tower = make_tower(range_=200)
    nearby_but_early = FakeEnemy((10, 0), distance_traveled=5)
    far_but_advanced = FakeEnemy((150, 0), distance_traveled=500)
    target = tower.acquire_target([nearby_but_early, far_but_advanced])
    assert target is far_but_advanced


def test_acquire_target_ignores_an_enemy_that_reached_the_goal():
    # Regression test: Game.update() runs every tower's update() before
    # it filters reached-goal enemies out of the live list for that same
    # frame, so acquire_target() must exclude them itself or a tower
    # could fire a brand-new shot at an enemy that's already gone.
    tower = make_tower(range_=100)
    gone = FakeEnemy((10, 0), distance_traveled=999, reached_goal=True)
    alive = FakeEnemy((10, 0), distance_traveled=1)
    assert tower.acquire_target([gone, alive]) is alive


def test_acquire_target_does_not_prefer_a_reached_goal_enemy_by_progress():
    # "Furthest along the path" is acquire_target's whole ranking, and an
    # enemy that just reached the goal necessarily has the *most*
    # distance_traveled of anything on the path -- so without the
    # reached_goal exclusion, it would always win over every real threat
    # still in range, not just occasionally slip through.
    tower = make_tower(range_=100)
    gone = FakeEnemy((10, 0), distance_traveled=10_000, reached_goal=True)
    real_threats = [FakeEnemy((10, 0), distance_traveled=d) for d in (1, 50, 99)]
    target = tower.acquire_target([gone] + real_threats)
    assert target in real_threats
