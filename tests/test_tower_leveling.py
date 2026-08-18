from tower import TOWER_TYPES, BasicTower


def make_tower(tower_cls=BasicTower):
    return tower_cls(col=0, row=0, pixel_pos=(0, 0))


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
    tower = make_tower()
    tower.upgrade()  # level 2
    level_2_damage = tower.damage
    tower.upgrade()  # level 3
    level_3_damage = tower.damage

    assert level_3_damage == BasicTower.damage * BasicTower.LEVEL_STAT_MULTIPLIERS[3]
    assert level_2_damage == BasicTower.damage * BasicTower.LEVEL_STAT_MULTIPLIERS[2]


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
        tower = tower_cls(col=0, row=0, pixel_pos=(0, 0))
        for _ in range(tower_cls.MAX_LEVEL - 1):
            assert tower.upgrade() is True, name
        assert tower.is_max_level, name
        assert tower.upgrade() is False, name
