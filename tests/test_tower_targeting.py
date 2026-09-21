import pygame

from spatial_index import EnemySpatialIndex
from tower import BasicTower, CannonTower, KnockbackTower


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


def test_targeting_mode_weakest_picks_lowest_hp():
    tower = make_tower(range_=100)
    tower.targeting_mode = "weakest"
    weak = FakeEnemy((10, 0), hp=10)
    strong = FakeEnemy((10, 0), hp=500)
    assert tower.acquire_target([weak, strong]) is weak


def test_cycle_targeting_mode_advances_through_every_mode_and_wraps():
    tower = make_tower()
    seen = [tower.targeting_mode]
    for _ in range(len(tower.TARGETING_MODES)):
        tower.cycle_targeting_mode()
        seen.append(tower.targeting_mode)
    assert seen == ["first", "last", "strongest", "closest", "weakest", "first"]


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


def test_acquire_target_with_an_enemy_index_matches_the_raw_list_scan():
    # The enemy_index is a pure performance path (see spatial_index.py) --
    # passing one must never change what a tower actually targets.
    tower = make_tower(range_=100)
    nearby_but_early = FakeEnemy((10, 0), distance_traveled=1)
    far_but_advanced = FakeEnemy((90, 0), distance_traveled=50)
    out_of_range = FakeEnemy((5000, 0), distance_traveled=999)
    enemies = [nearby_but_early, far_but_advanced, out_of_range]
    index = EnemySpatialIndex(enemies)
    assert tower.acquire_target(enemies, index) is tower.acquire_target(enemies) is far_but_advanced


def test_acquire_target_with_an_enemy_index_still_excludes_dead_and_reached_goal():
    tower = make_tower(range_=100)
    dead = FakeEnemy((10, 0), is_dead=True, distance_traveled=999)
    gone = FakeEnemy((10, 0), reached_goal=True, distance_traveled=500)
    alive = FakeEnemy((10, 0), distance_traveled=1)
    enemies = [dead, gone, alive]
    index = EnemySpatialIndex(enemies)
    assert tower.acquire_target(enemies, index) is alive


def test_acquire_target_with_an_enemy_index_still_excludes_flying_when_disallowed():
    tower = make_tower(range_=100)
    tower.can_target_flying = False
    flyer = FakeEnemy((10, 0), distance_traveled=999)
    flyer.is_flying = True
    grounded = FakeEnemy((10, 0), distance_traveled=1)
    enemies = [flyer, grounded]
    index = EnemySpatialIndex(enemies)
    assert tower.acquire_target(enemies, index) is grounded


def test_acquire_target_with_an_enemy_index_returns_none_when_nothing_in_range():
    tower = make_tower(range_=50)
    enemies = [FakeEnemy((1000, 0))]
    index = EnemySpatialIndex(enemies)
    assert tower.acquire_target(enemies, index) is None


def test_acquire_target_with_an_enemy_index_finds_a_target_beyond_one_cell():
    # cell_size defaults to 128px -- placing the enemy several cells away
    # from the tower (but still within its own effective_range) exercises
    # near()'s multi-cell span, not just the trivial same-cell case.
    tower = make_tower(range_=400)
    far_cell_but_in_range = FakeEnemy((380, 0), distance_traveled=1)
    enemies = [far_cell_but_in_range]
    index = EnemySpatialIndex(enemies)
    assert tower.acquire_target(enemies, index) is far_cell_but_in_range


def test_cannon_tower_without_the_relic_still_excludes_flying_enemies():
    # Regression: CannonTower.can_target_flying used to be a plain class
    # attribute (always False); it's now a property reading relic_cannon_
    # targets_flying (see tower.py), which Tower.__init__ defaults to
    # False -- confirms that default alone still reproduces Cannon's
    # original, relic-less behavior with no other change needed.
    tower = CannonTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.range = 100
    assert tower.relic_cannon_targets_flying is False
    flyer = FakeEnemy((10, 0), distance_traveled=999)
    flyer.is_flying = True
    grounded = FakeEnemy((10, 0), distance_traveled=1)
    assert tower.acquire_target([flyer, grounded]) is grounded


def test_aerial_targeting_array_relic_lets_cannon_tower_target_flying_enemies():
    tower = CannonTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.range = 100
    tower.relic_cannon_targets_flying = True  # aerial_targeting_array, granted
    flyer = FakeEnemy((10, 0), distance_traveled=1)
    flyer.is_flying = True
    assert tower.acquire_target([flyer]) is flyer


def test_aerial_targeting_array_relic_field_does_not_affect_other_towers():
    # Proves true exclusivity, not just presence of the mechanic: setting
    # the same relic field on a tower whose own can_target_flying is still
    # the plain, untouched class attribute (KnockbackTower's own, never
    # converted to a property -- see tower.py) must never let it target
    # flying enemies. Any other non-Cannon tower would behave identically,
    # since only CannonTower's own can_target_flying property ever reads
    # this field at all.
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.range = 100
    tower.relic_cannon_targets_flying = True
    assert tower.can_target_flying is False
    flyer = FakeEnemy((10, 0), distance_traveled=999)
    flyer.is_flying = True
    grounded = FakeEnemy((10, 0), distance_traveled=1)
    assert tower.acquire_target([flyer, grounded]) is grounded
