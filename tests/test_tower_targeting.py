import pygame

from tower import BasicTower


class FakeEnemy:
    """A minimal stand-in with just the attributes Tower.acquire_target
    reads -- avoids needing a real path/waypoints for these tests."""

    def __init__(self, pos, distance_traveled=0.0, is_dead=False):
        self.pos = pygame.Vector2(pos)
        self.distance_traveled = distance_traveled
        self.is_dead = is_dead


def make_tower(range_=100):
    tower = BasicTower(col=0, row=0, pixel_pos=(0, 0))
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
