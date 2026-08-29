import settings
from tower import (
    TOWER_TYPES, BasicTower, CannonTower, FrostTower, KnockbackTower,
    LightningTower, PoisonTower, SniperTower, Tower,
)


def make_tower(tower_cls=BasicTower, anchor_col=0, anchor_row=0):
    pixel_pos = (
        anchor_col * settings.SUBTILE_SIZE + settings.TILE_SIZE / 2,
        anchor_row * settings.SUBTILE_SIZE + settings.TILE_SIZE / 2,
    )
    return tower_cls(anchor_col=anchor_col, anchor_row=anchor_row, pixel_pos=pixel_pos)


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


def test_sell_value_starts_as_a_fraction_of_base_cost():
    tower = make_tower()
    assert tower.total_invested == BasicTower.cost
    assert tower.sell_value() == round(BasicTower.cost * settings.SELL_REFUND_FRACTION)


def test_sell_value_grows_with_each_upgrade_paid_for():
    tower = make_tower()
    level_2_cost = tower.upgrade_cost()
    tower.upgrade()

    assert tower.total_invested == BasicTower.cost + level_2_cost
    assert tower.sell_value() == round(tower.total_invested * settings.SELL_REFUND_FRACTION)

    level_3_cost = tower.upgrade_cost()
    tower.upgrade()

    assert tower.total_invested == BasicTower.cost + level_2_cost + level_3_cost
    assert tower.sell_value() == round(tower.total_invested * settings.SELL_REFUND_FRACTION)


def test_sell_value_is_less_than_total_invested():
    # Otherwise build/sell would be a free way to reposition a tower.
    tower = make_tower()
    tower.upgrade()
    assert tower.sell_value() < tower.total_invested


# --- Specialization ---

def _max_out(tower):
    while not tower.is_max_level:
        tower.upgrade()
    return tower


def test_cannot_specialize_before_max_level():
    tower = make_tower()
    assert not tower.can_specialize
    assert tower.specialization_cost() is None
    assert tower.specialize("power") is False


def test_can_specialize_once_maxed():
    tower = _max_out(make_tower())
    assert tower.can_specialize
    assert tower.specialization_cost() == round(BasicTower.cost * BasicTower.SPECIALIZATION_COST_MULTIPLIER)


def test_specialize_applies_its_stat_multipliers():
    tower = _max_out(make_tower())
    base_damage = tower.damage
    spec = BasicTower.SPECIALIZATIONS["power"]

    assert tower.specialize("power") is True

    assert tower.damage == base_damage * spec["stat_multipliers"]["damage"]
    assert tower.specialization == "power"


def test_specialize_updates_total_invested():
    tower = _max_out(make_tower())
    invested_before = tower.total_invested
    cost = tower.specialization_cost()

    tower.specialize("power")

    assert tower.total_invested == invested_before + cost


def test_specialize_is_a_one_time_choice():
    tower = _max_out(make_tower())
    tower.specialize("power")
    assert not tower.can_specialize

    # A second call -- even with a different key -- is a no-op.
    damage_after_first = tower.damage
    assert tower.specialize("precision") is False
    assert tower.damage == damage_after_first
    assert tower.specialization == "power"


def test_specialize_rejects_an_unknown_key():
    tower = _max_out(make_tower())
    assert tower.specialize("not-a-real-specialization") is False
    assert tower.specialization is None
    assert tower.can_specialize


def test_every_registered_tower_has_exactly_two_specializations():
    # The UI offers exactly two choices -- see ui.build_specialize_button_rects.
    for name, tower_cls in TOWER_TYPES.items():
        assert len(tower_cls.SPECIALIZATIONS) == 2, name


def test_specialization_stat_multipliers_reference_real_attributes():
    for name, tower_cls in TOWER_TYPES.items():
        tower = make_tower(tower_cls)
        for key, spec in tower_cls.SPECIALIZATIONS.items():
            for stat_name in spec["stat_multipliers"]:
                assert hasattr(tower, stat_name), f"{name}: {key}: {stat_name}"


def test_lightning_tower_overrides_the_generic_specializations():
    # Its own mechanic-specific options, not the generic Power/Precision
    # every other tower currently falls back to.
    assert set(LightningTower.SPECIALIZATIONS.keys()) == {"arc_reach", "overcharge"}


def test_lightning_tower_arc_reach_boosts_chain_range_only():
    tower = _max_out(make_tower(LightningTower))
    base_chain_range = tower.chain_range
    base_damage = tower.damage
    multiplier = LightningTower.SPECIALIZATIONS["arc_reach"]["stat_multipliers"]["chain_range"]

    assert tower.specialize("arc_reach") is True

    assert tower.chain_range == base_chain_range * multiplier
    assert tower.damage == base_damage  # unaffected


def test_lightning_tower_overcharge_boosts_damage_only():
    tower = _max_out(make_tower(LightningTower))
    base_chain_range = tower.chain_range
    base_damage = tower.damage
    multiplier = LightningTower.SPECIALIZATIONS["overcharge"]["stat_multipliers"]["damage"]

    assert tower.specialize("overcharge") is True

    assert tower.damage == base_damage * multiplier
    assert tower.chain_range == base_chain_range  # unaffected


def test_basic_tower_specializations_are_tuned_differently_from_the_generic_placeholder():
    # Basic keeps the same "power"/"precision" *keys* as the generic
    # placeholder (see tower.py's comment on BasicTower.SPECIALIZATIONS for
    # why -- several tests above hardcode those key strings), but its own
    # values should no longer just be Tower's placeholder verbatim.
    assert set(BasicTower.SPECIALIZATIONS.keys()) == set(Tower.SPECIALIZATIONS.keys())
    assert BasicTower.SPECIALIZATIONS != Tower.SPECIALIZATIONS


def test_basic_tower_power_boosts_damage_only():
    tower = _max_out(make_tower(BasicTower))
    base_damage, base_fire_rate = tower.damage, tower.fire_rate
    multiplier = BasicTower.SPECIALIZATIONS["power"]["stat_multipliers"]["damage"]

    assert tower.specialize("power") is True

    assert tower.damage == base_damage * multiplier
    assert tower.fire_rate == base_fire_rate  # unaffected


def test_basic_tower_precision_boosts_fire_rate_only():
    tower = _max_out(make_tower(BasicTower))
    base_damage, base_fire_rate = tower.damage, tower.fire_rate
    multiplier = BasicTower.SPECIALIZATIONS["precision"]["stat_multipliers"]["fire_rate"]

    assert tower.specialize("precision") is True

    assert tower.fire_rate == base_fire_rate * multiplier
    assert tower.damage == base_damage  # unaffected


def test_sniper_tower_overrides_the_generic_specializations():
    assert set(SniperTower.SPECIALIZATIONS.keys()) == {"armor_piercing", "extended_scope"}


def test_sniper_tower_armor_piercing_boosts_damage_only():
    tower = _max_out(make_tower(SniperTower))
    base_damage, base_range = tower.damage, tower.range
    multiplier = SniperTower.SPECIALIZATIONS["armor_piercing"]["stat_multipliers"]["damage"]

    assert tower.specialize("armor_piercing") is True

    assert tower.damage == base_damage * multiplier
    assert tower.range == base_range  # unaffected


def test_sniper_tower_extended_scope_boosts_range_only():
    tower = _max_out(make_tower(SniperTower))
    base_damage, base_range = tower.damage, tower.range
    multiplier = SniperTower.SPECIALIZATIONS["extended_scope"]["stat_multipliers"]["range"]

    assert tower.specialize("extended_scope") is True

    assert tower.range == base_range * multiplier
    assert tower.damage == base_damage  # unaffected


def test_cannon_tower_overrides_the_generic_specializations():
    assert set(CannonTower.SPECIALIZATIONS.keys()) == {"bigger_blast", "heavier_payload"}


def test_cannon_tower_bigger_blast_boosts_splash_radius_only():
    tower = _max_out(make_tower(CannonTower))
    base_splash, base_damage = tower.splash_radius, tower.damage
    multiplier = CannonTower.SPECIALIZATIONS["bigger_blast"]["stat_multipliers"]["splash_radius"]

    assert tower.specialize("bigger_blast") is True

    assert tower.splash_radius == base_splash * multiplier
    assert tower.damage == base_damage  # unaffected


def test_cannon_tower_heavier_payload_boosts_damage_only():
    tower = _max_out(make_tower(CannonTower))
    base_splash, base_damage = tower.splash_radius, tower.damage
    multiplier = CannonTower.SPECIALIZATIONS["heavier_payload"]["stat_multipliers"]["damage"]

    assert tower.specialize("heavier_payload") is True

    assert tower.damage == base_damage * multiplier
    assert tower.splash_radius == base_splash  # unaffected


def test_frost_tower_overrides_the_generic_specializations():
    assert set(FrostTower.SPECIALIZATIONS.keys()) == {"deep_freeze", "lingering_frost"}


def test_frost_tower_deep_freeze_lowers_slow_factor_only():
    # Deep Freeze's multiplier is deliberately < 1.0 -- a lower slow_factor
    # is a *stronger* slow (see tower.py's comment on this override).
    tower = _max_out(make_tower(FrostTower))
    base_slow_factor, base_slow_duration = tower.slow_factor, tower.slow_duration
    multiplier = FrostTower.SPECIALIZATIONS["deep_freeze"]["stat_multipliers"]["slow_factor"]
    assert multiplier < 1.0

    assert tower.specialize("deep_freeze") is True

    assert tower.slow_factor == base_slow_factor * multiplier
    assert tower.slow_factor < base_slow_factor
    assert tower.slow_duration == base_slow_duration  # unaffected


def test_frost_tower_lingering_frost_boosts_slow_duration_only():
    tower = _max_out(make_tower(FrostTower))
    base_slow_factor, base_slow_duration = tower.slow_factor, tower.slow_duration
    multiplier = FrostTower.SPECIALIZATIONS["lingering_frost"]["stat_multipliers"]["slow_duration"]

    assert tower.specialize("lingering_frost") is True

    assert tower.slow_duration == base_slow_duration * multiplier
    assert tower.slow_factor == base_slow_factor  # unaffected


def test_knockback_tower_overrides_the_generic_specializations():
    assert set(KnockbackTower.SPECIALIZATIONS.keys()) == {"wrecking_ball", "concussive_force"}


def test_knockback_tower_wrecking_ball_boosts_splash_radius_only():
    tower = _max_out(make_tower(KnockbackTower))
    base_splash, base_knockback = tower.splash_radius, tower.knockback_duration
    multiplier = KnockbackTower.SPECIALIZATIONS["wrecking_ball"]["stat_multipliers"]["splash_radius"]

    assert tower.specialize("wrecking_ball") is True

    assert tower.splash_radius == base_splash * multiplier
    assert tower.knockback_duration == base_knockback  # unaffected


def test_knockback_tower_concussive_force_boosts_knockback_duration_only():
    tower = _max_out(make_tower(KnockbackTower))
    base_splash, base_knockback = tower.splash_radius, tower.knockback_duration
    multiplier = KnockbackTower.SPECIALIZATIONS["concussive_force"]["stat_multipliers"]["knockback_duration"]

    assert tower.specialize("concussive_force") is True

    assert tower.knockback_duration == base_knockback * multiplier
    assert tower.splash_radius == base_splash  # unaffected


def test_poison_tower_overrides_the_generic_specializations():
    assert set(PoisonTower.SPECIALIZATIONS.keys()) == {"virulent_strain", "lingering_toxin"}


def test_poison_tower_virulent_strain_boosts_tick_damage_only():
    tower = _max_out(make_tower(PoisonTower))
    base_tick, base_duration = tower.poison_damage_per_tick, tower.poison_duration
    multiplier = PoisonTower.SPECIALIZATIONS["virulent_strain"]["stat_multipliers"]["poison_damage_per_tick"]

    assert tower.specialize("virulent_strain") is True

    assert tower.poison_damage_per_tick == base_tick * multiplier
    assert tower.poison_duration == base_duration  # unaffected


def test_poison_tower_lingering_toxin_boosts_duration_only():
    tower = _max_out(make_tower(PoisonTower))
    base_tick, base_duration = tower.poison_damage_per_tick, tower.poison_duration
    multiplier = PoisonTower.SPECIALIZATIONS["lingering_toxin"]["stat_multipliers"]["poison_duration"]

    assert tower.specialize("lingering_toxin") is True

    assert tower.poison_duration == base_duration * multiplier
    assert tower.poison_damage_per_tick == base_tick  # unaffected


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
    tower = make_tower(anchor_col=2, anchor_row=3)
    cx, cy = tower.upgrade_badge_center()

    tile_left, tile_top = 2 * settings.SUBTILE_SIZE, 3 * settings.SUBTILE_SIZE
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
    tower = make_tower(anchor_col=2, anchor_row=3)
    tile_left, tile_top = 2 * settings.SUBTILE_SIZE, 3 * settings.SUBTILE_SIZE

    # The tile's center is nowhere near the badge (top-right corner), but
    # hovering it should still count for showing stats/range.
    center_of_tile = (tile_left + settings.TILE_SIZE / 2, tile_top + settings.TILE_SIZE / 2)
    assert not tower.contains_upgrade_badge(center_of_tile)
    assert tower.contains_point(center_of_tile)


def test_contains_point_is_false_outside_the_tile():
    tower = make_tower(anchor_col=2, anchor_row=3)
    assert not tower.contains_point((10_000, 10_000))


def test_contains_point_still_true_when_maxed_even_though_badge_is_gone():
    tower = make_tower()
    for _ in range(BasicTower.MAX_LEVEL - 1):
        tower.upgrade()
    assert tower.is_max_level

    center_of_tile = (settings.TILE_SIZE / 2, settings.TILE_SIZE / 2)
    assert not tower.contains_upgrade_badge(center_of_tile)
    assert tower.contains_point(center_of_tile)
