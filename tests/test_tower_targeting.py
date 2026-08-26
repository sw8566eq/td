import pygame

from tower import BasicTower


class FakeEnemy:
    """A minimal stand-in with just the attributes Tower.acquire_target
    reads -- avoids needing a real path/waypoints for these tests.
    Deliberately has no is_flying attribute by default -- acquire_target's
    flying filter must use getattr(..., "is_flying", False), not a bare
    attribute access, so a plain enemy stand-in like this one doesn't
    raise."""

    def __init__(self, pos, distance_traveled=0.0, is_dead=False, reached_goal=False, hp=100):
        self.pos = pygame.Vector2(pos)
        self.distance_traveled = distance_traveled
        self.is_dead = is_dead
        self.reached_goal = reached_goal
        self.hp = hp


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


# --- Targeting modes ---

def test_default_targeting_mode_is_first():
    assert make_tower().targeting_mode == "first"


def test_targeting_mode_last_picks_least_progressed():
    tower = make_tower(range_=200)
    tower.targeting_mode = "last"
    least_progressed = FakeEnemy((10, 0), distance_traveled=1)
    most_progressed = FakeEnemy((150, 0), distance_traveled=500)
    assert tower.acquire_target([most_progressed, least_progressed]) is least_progressed


def test_targeting_mode_strongest_picks_highest_hp():
    tower = make_tower(range_=100)
    tower.targeting_mode = "strongest"
    weak = FakeEnemy((10, 0), hp=10)
    strong = FakeEnemy((10, 0), hp=500)
    assert tower.acquire_target([weak, strong]) is strong


def test_targeting_mode_closest_picks_nearest_to_the_tower():
    tower = make_tower(range_=200)
    tower.targeting_mode = "closest"
    near = FakeEnemy((20, 0))
    far = FakeEnemy((150, 0))
    assert tower.acquire_target([far, near]) is near


def test_cycle_targeting_mode_advances_through_every_mode_and_wraps():
    tower = make_tower()
    seen = [tower.targeting_mode]
    for _ in range(len(tower.TARGETING_MODES)):
        tower.cycle_targeting_mode()
        seen.append(tower.targeting_mode)
    assert seen == ["first", "last", "strongest", "closest", "first"]


def test_acquire_target_excludes_flying_enemy_when_tower_cannot_target_flying():
    tower = make_tower(range_=100)
    tower.can_target_flying = False
    flyer = FakeEnemy((10, 0), distance_traveled=999)
    flyer.is_flying = True
    grounded = FakeEnemy((10, 0), distance_traveled=1)
    assert tower.acquire_target([flyer, grounded]) is grounded


def test_acquire_target_includes_flying_enemy_when_tower_can_target_flying():
    tower = make_tower(range_=100)
    assert tower.can_target_flying is True  # default
    flyer = FakeEnemy((10, 0), distance_traveled=1)
    flyer.is_flying = True
    assert tower.acquire_target([flyer]) is flyer


def test_acquire_target_treats_a_missing_is_flying_attribute_as_not_flying():
    # FakeEnemy above deliberately has no is_flying attribute -- must not
    # raise even when the tower can't target flying enemies.
    tower = make_tower(range_=100)
    tower.can_target_flying = False
    grounded = FakeEnemy((10, 0), distance_traveled=1)
    assert tower.acquire_target([grounded]) is grounded
