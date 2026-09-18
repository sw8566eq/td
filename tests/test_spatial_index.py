import pygame

from spatial_index import EnemySpatialIndex


class FakeEnemy:
    def __init__(self, pos, is_dead=False, reached_goal=False):
        self.pos = pygame.Vector2(pos)
        self.is_dead = is_dead
        self.reached_goal = reached_goal


def test_near_finds_an_enemy_in_the_same_cell():
    enemy = FakeEnemy((10, 10))
    index = EnemySpatialIndex([enemy], cell_size=128)
    assert list(index.near(pygame.Vector2(0, 0), radius=50)) == [enemy]


def test_near_finds_an_enemy_in_a_neighboring_cell_within_radius():
    # Different cells at cell_size=128, but only 60px apart -- a query
    # centered between them with enough radius must still cross the cell
    # boundary to find it.
    enemy = FakeEnemy((130, 0))
    index = EnemySpatialIndex([enemy], cell_size=128)
    assert list(index.near(pygame.Vector2(70, 0), radius=100)) == [enemy]


def test_near_excludes_an_enemy_far_outside_every_queried_cell():
    enemy = FakeEnemy((2000, 2000))
    index = EnemySpatialIndex([enemy], cell_size=128)
    assert list(index.near(pygame.Vector2(0, 0), radius=50)) == []


def test_near_can_be_over_inclusive_at_cell_corners_by_design():
    # A tiny query radius still pulls in every enemy anywhere in a
    # queried cell, not just ones truly within the radius -- an enemy in
    # the far corner of a cell the query barely touches can come back far
    # outside the requested radius. Callers are expected to re-check the
    # exact distance themselves (see Tower.acquire_target()), so this is
    # documented slack, not a bug.
    far_corner_of_a_touched_cell = FakeEnemy((200, 90))  # cell (1, 0)
    index = EnemySpatialIndex([far_corner_of_a_touched_cell], cell_size=128)
    # Query sits just inside cell (0, 0)/(0, -1), radius 1 -- barely
    # crosses into cell (1, 0) too, which is enough to pull the whole
    # bucket in regardless of the enemy's actual distance from (127, 0).
    found = list(index.near(pygame.Vector2(127, 0), radius=1))
    assert far_corner_of_a_touched_cell in found
    assert pygame.Vector2(127, 0).distance_to(far_corner_of_a_touched_cell.pos) > 1


def test_dead_enemy_excluded_from_the_index():
    dead = FakeEnemy((0, 0), is_dead=True)
    index = EnemySpatialIndex([dead], cell_size=128)
    assert list(index.near(pygame.Vector2(0, 0), radius=500)) == []


def test_reached_goal_enemy_excluded_from_the_index():
    gone = FakeEnemy((0, 0), reached_goal=True)
    index = EnemySpatialIndex([gone], cell_size=128)
    assert list(index.near(pygame.Vector2(0, 0), radius=500)) == []


def test_an_enemy_killed_after_the_index_was_built_is_still_reflected_live():
    # Buckets hold the object itself, not a snapshot -- an enemy another
    # tower kills later in the same frame (Game.update() builds the index
    # once, before the whole tower loop runs) must disappear from a
    # caller's own is_dead re-check without needing the index rebuilt.
    enemy = FakeEnemy((0, 0))
    index = EnemySpatialIndex([enemy], cell_size=128)
    enemy.is_dead = True
    (found,) = index.near(pygame.Vector2(0, 0), radius=50)
    assert found.is_dead is True


def test_near_on_an_empty_index_returns_nothing():
    index = EnemySpatialIndex([], cell_size=128)
    assert list(index.near(pygame.Vector2(0, 0), radius=1000)) == []


def test_two_enemies_in_different_cells_both_found_by_a_wide_query():
    near_origin = FakeEnemy((0, 0))
    far_away = FakeEnemy((500, 500))
    index = EnemySpatialIndex([near_origin, far_away], cell_size=128)
    found = set(index.near(pygame.Vector2(0, 0), radius=1000))
    assert found == {near_origin, far_away}
