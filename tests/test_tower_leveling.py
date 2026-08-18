import settings
from tower import TOWER_TYPES, BasicTower, CannonTower


def make_tower(tower_cls=BasicTower, col=0, row=0):
    pixel_pos = (col * settings.TILE_SIZE + settings.TILE_SIZE / 2, row * settings.TILE_SIZE + settings.TILE_SIZE / 2)
    return tower_cls(col=col, row=row, pixel_pos=pixel_pos)


def test_new_tower_starts_at_level_one_with_base_stats():
    tower = make_tower()
    assert tower.level == 1
    assert tower.damage == BasicTower.damage
    assert tower.range == BasicTower.range
    assert not tower.is_max_level


def test_upgrade_increases_damage_and_range():
    tower = make_tower()
    base_damage, base_range = tower.damage, tower.range

    assert tower.upgrade() is True

    assert tower.level == 2
    assert tower.damage > base_damage
    assert tower.range > base_range


def test_upgrades_recompute_from_base_rather_than_compounding():
    # Uses CannonTower (no LEVEL_STAT_MULTIPLIER_OVERRIDES) so this test
    # exercises the generic mechanism, not any one tower's special-cased
    # curve -- see test_basic_tower_damage_overrides_the_generic_curve
    # below for that.
    tower = make_tower(CannonTower)
    tower.upgrade()  # level 2
    level_2_damage = tower.damage
    tower.upgrade()  # level 3
    level_3_damage = tower.damage

    assert level_3_damage == CannonTower.damage * CannonTower.LEVEL_STAT_MULTIPLIERS[3]
    assert level_2_damage == CannonTower.damage * CannonTower.LEVEL_STAT_MULTIPLIERS[2]


def test_cannot_upgrade_past_max_level():
    tower = make_tower()
    for _ in range(BasicTower.MAX_LEVEL - 1):
        assert tower.upgrade() is True
    assert tower.is_max_level
    assert tower.level == BasicTower.MAX_LEVEL

    assert tower.upgrade() is False
    assert tower.level == BasicTower.MAX_LEVEL  # unchanged


def test_upgrade_cost_is_none_at_max_level():
    tower = make_tower()
    assert tower.upgrade_cost() is not None
    for _ in range(BasicTower.MAX_LEVEL - 1):
        tower.upgrade()
    assert tower.upgrade_cost() is None


def test_upgrade_cost_scales_with_base_cost():
    tower = make_tower()
    expected_level_2_cost = round(BasicTower.cost * BasicTower.UPGRADE_COST_MULTIPLIERS[2])
    assert tower.upgrade_cost() == expected_level_2_cost


def test_only_stats_in_level_scaled_stats_change_on_upgrade():
    tower = make_tower()
    base_fire_rate = tower.fire_rate
    tower.upgrade()
    assert tower.fire_rate == base_fire_rate  # not in LEVEL_SCALED_STATS


def test_every_registered_tower_can_reach_max_level():
    for name, tower_cls in TOWER_TYPES.items():
        tower = make_tower(tower_cls)
        for _ in range(tower_cls.MAX_LEVEL - 1):
            assert tower.upgrade() is True, name
        assert tower.is_max_level, name
        assert tower.upgrade() is False, name


def test_range_after_next_upgrade_matches_what_upgrading_would_actually_do():
    tower = make_tower()
    previewed = tower.range_after_next_upgrade()

    tower.upgrade()

    assert tower.range == previewed


def test_range_after_next_upgrade_does_not_itself_change_anything():
    tower = make_tower()
    base_range = tower.range
    tower.range_after_next_upgrade()
    tower.range_after_next_upgrade()
    assert tower.range == base_range
    assert tower.level == 1


def test_range_after_next_upgrade_is_bigger_than_current_range():
    tower = make_tower()
    assert tower.range_after_next_upgrade() > tower.range


def test_range_after_next_upgrade_equals_current_range_once_maxed():
    tower = make_tower()
    for _ in range(BasicTower.MAX_LEVEL - 1):
        tower.upgrade()
    assert tower.is_max_level
    assert tower.range_after_next_upgrade() == tower.range


def test_damage_after_next_upgrade_matches_what_upgrading_would_actually_do():
    tower = make_tower()
    previewed = tower.damage_after_next_upgrade()

    tower.upgrade()

    assert tower.damage == previewed


def test_damage_after_next_upgrade_equals_current_damage_once_maxed():
    tower = make_tower()
    for _ in range(BasicTower.MAX_LEVEL - 1):
        tower.upgrade()
    assert tower.is_max_level
    assert tower.damage_after_next_upgrade() == tower.damage


def test_basic_tower_damage_overrides_the_generic_curve():
    tower = make_tower(BasicTower)
    override = BasicTower.LEVEL_STAT_MULTIPLIER_OVERRIDES["damage"]

    tower.upgrade()  # level 2
    assert tower.damage == BasicTower.damage * override[2]
    tower.upgrade()  # level 3
    assert tower.damage == BasicTower.damage * override[3]


def test_basic_tower_damage_scales_more_steeply_than_the_generic_curve():
    override = BasicTower.LEVEL_STAT_MULTIPLIER_OVERRIDES["damage"]
    assert override[2] > BasicTower.LEVEL_STAT_MULTIPLIERS[2]
    assert override[3] > BasicTower.LEVEL_STAT_MULTIPLIERS[3]


def test_basic_tower_range_still_uses_the_generic_curve():
    # Only damage is special-cased -- range should scale exactly like any
    # other tower's, unaffected by the damage override.
    tower = make_tower(BasicTower)
    tower.upgrade()  # level 2
    assert tower.range == BasicTower.range * BasicTower.LEVEL_STAT_MULTIPLIERS[2]


def test_other_towers_have_no_multiplier_overrides():
    for name, tower_cls in TOWER_TYPES.items():
        if name == "basic":
            continue
        assert tower_cls.LEVEL_STAT_MULTIPLIER_OVERRIDES == {}, name


def test_every_registered_towers_extra_stats_reference_real_attributes():
    for name, tower_cls in TOWER_TYPES.items():
        tower = make_tower(tower_cls)
        for label, attr_name, format_fn in tower_cls.EXTRA_STATS:
            assert hasattr(tower, attr_name), f"{name}: {attr_name}"
            # The formatter should produce a non-empty string for the
            # tower's actual value without raising.
            formatted = format_fn(getattr(tower, attr_name))
            assert isinstance(formatted, str) and formatted, f"{name}: {label}"


def test_basic_tower_has_no_extra_stats():
    assert BasicTower.EXTRA_STATS == ()


def test_upgrade_badge_sits_in_the_tiles_top_right_corner():
    tower = make_tower(col=2, row=3)
    cx, cy = tower.upgrade_badge_center()

    tile_left, tile_top = 2 * settings.TILE_SIZE, 3 * settings.TILE_SIZE
    assert tile_left < cx < tile_left + settings.TILE_SIZE
    assert tile_top < cy < tile_top + settings.TILE_SIZE
    # top-right, not centered or bottom-left
    assert cx > tile_left + settings.TILE_SIZE / 2
    assert cy < tile_top + settings.TILE_SIZE / 2


def test_clicking_the_badge_center_hits_it():
    tower = make_tower()
    center = tower.upgrade_badge_center()
    assert tower.contains_upgrade_badge(center)


def test_clicking_far_from_the_badge_misses_it():
    tower = make_tower()
    assert not tower.contains_upgrade_badge((10_000, 10_000))


def test_maxed_out_tower_has_no_clickable_badge():
    tower = make_tower()
    for _ in range(BasicTower.MAX_LEVEL - 1):
        tower.upgrade()
    assert tower.is_max_level

    center = tower.upgrade_badge_center()
    assert not tower.contains_upgrade_badge(center)


def test_contains_point_is_true_anywhere_on_the_tile_not_just_the_badge():
    tower = make_tower(col=2, row=3)
    tile_left, tile_top = 2 * settings.TILE_SIZE, 3 * settings.TILE_SIZE

    # The tile's center is nowhere near the badge (top-right corner), but
    # hovering it should still count for showing stats/range.
    center_of_tile = (tile_left + settings.TILE_SIZE / 2, tile_top + settings.TILE_SIZE / 2)
    assert not tower.contains_upgrade_badge(center_of_tile)
    assert tower.contains_point(center_of_tile)


def test_contains_point_is_false_outside_the_tile():
    tower = make_tower(col=2, row=3)
    assert not tower.contains_point((10_000, 10_000))


def test_contains_point_still_true_when_maxed_even_though_badge_is_gone():
    tower = make_tower()
    for _ in range(BasicTower.MAX_LEVEL - 1):
        tower.upgrade()
    assert tower.is_max_level

    center_of_tile = (settings.TILE_SIZE / 2, settings.TILE_SIZE / 2)
    assert not tower.contains_upgrade_badge(center_of_tile)
    assert tower.contains_point(center_of_tile)
