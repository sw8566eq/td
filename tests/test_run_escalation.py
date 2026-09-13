import pytest

from run_escalation import (
    EARLY_GRACE_GOLD_BONUS,
    EARLY_GRACE_HP_DISCOUNT,
    EARLY_GRACE_ROWS,
    EARLY_GRACE_SPEED_DISCOUNT,
    ELITE_GOLD_MULTIPLIER,
    ELITE_HP_MULTIPLIER,
    ELITE_SPEED_MULTIPLIER,
    FloorEscalation,
    apply_boss_multiplier,
    apply_elite_multiplier,
    escalation_for_floor,
)


def test_floor_zero_gets_the_full_early_grace_discount():
    escalation = escalation_for_floor(0)
    assert escalation.enemy_hp_multiplier == pytest.approx(1.0 - EARLY_GRACE_HP_DISCOUNT)
    assert escalation.enemy_speed_multiplier == pytest.approx(1.0 - EARLY_GRACE_SPEED_DISCOUNT)
    assert escalation.starting_gold_multiplier == pytest.approx(1.0 + EARLY_GRACE_GOLD_BONUS)
    # Kill-gold reward isn't part of the grace period -- see
    # run_escalation.py's own docstring for why only starting_gold is
    # bumped, not this.
    assert escalation.enemy_gold_multiplier == 1.0


def test_early_grace_fades_completely_by_early_grace_rows():
    # Rejoins the plain growth-only formula exactly at EARLY_GRACE_ROWS --
    # no discount, no gold bonus, identical to what the formula produced
    # before the grace period existed.
    escalation = escalation_for_floor(EARLY_GRACE_ROWS)
    assert escalation.enemy_hp_multiplier == pytest.approx(1.0 + 0.12 * EARLY_GRACE_ROWS)
    assert escalation.enemy_speed_multiplier == pytest.approx(1.0 + 0.02 * EARLY_GRACE_ROWS)
    assert escalation.starting_gold_multiplier == 1.0
    # And every later row stays exactly there -- the taper never goes
    # negative/re-applies past the grace window.
    later = escalation_for_floor(EARLY_GRACE_ROWS + 5)
    assert later.starting_gold_multiplier == 1.0


def test_escalation_grows_monotonically_with_floor_index():
    # Subsumes "floor 5 > floor 0" as one step of this same chain -- no
    # separate test needed for that special case. Holds even across the
    # early-grace taper (rows 0-1): each step's discount shrinks by more
    # than the underlying growth formula gains, so hp/speed still climb
    # every step, not just from EARLY_GRACE_ROWS onward.
    previous = escalation_for_floor(0)
    for floor_index in range(1, 20):
        current = escalation_for_floor(floor_index)
        assert current.enemy_hp_multiplier > previous.enemy_hp_multiplier
        assert current.enemy_speed_multiplier > previous.enemy_speed_multiplier
        assert current.enemy_gold_multiplier > previous.enemy_gold_multiplier
        previous = current


def test_starting_gold_multiplier_shrinks_monotonically_to_one():
    # The inverse shape from enemy_hp/speed/gold above -- starts high,
    # decreases every row until it settles at the neutral 1.0.
    previous = escalation_for_floor(0).starting_gold_multiplier
    for floor_index in range(1, EARLY_GRACE_ROWS + 3):
        current = escalation_for_floor(floor_index).starting_gold_multiplier
        assert current <= previous
        previous = current
    assert previous == 1.0


def test_elite_and_boss_multipliers_never_touch_starting_gold():
    base = escalation_for_floor(0)
    assert apply_elite_multiplier(base).starting_gold_multiplier == base.starting_gold_multiplier
    assert apply_boss_multiplier(base).starting_gold_multiplier == base.starting_gold_multiplier


def test_escalation_is_deterministic():
    assert escalation_for_floor(7) == escalation_for_floor(7)


def test_apply_elite_multiplier_composes_on_top_never_replaces():
    base = escalation_for_floor(3)
    elite = apply_elite_multiplier(base)
    assert elite.enemy_hp_multiplier > base.enemy_hp_multiplier
    assert elite.enemy_speed_multiplier > base.enemy_speed_multiplier
    assert elite.enemy_gold_multiplier > base.enemy_gold_multiplier


def test_apply_elite_multiplier_multiplies_an_arbitrary_escalation():
    # Not just "bigger than floor 0" -- proves it multiplies whatever
    # FloorEscalation it's handed by its own fixed constants, rather than a
    # formula that only happens to look right for escalation_for_floor's
    # own outputs (which are all >= 1.0, so a bug that e.g. added instead of
    # multiplied could still coincidentally satisfy the ">" checks above).
    arbitrary = FloorEscalation(enemy_hp_multiplier=2.0, enemy_speed_multiplier=1.5, enemy_gold_multiplier=3.0)
    elite = apply_elite_multiplier(arbitrary)
    assert elite.enemy_hp_multiplier == pytest.approx(2.0 * ELITE_HP_MULTIPLIER)
    assert elite.enemy_speed_multiplier == pytest.approx(1.5 * ELITE_SPEED_MULTIPLIER)
    assert elite.enemy_gold_multiplier == pytest.approx(3.0 * ELITE_GOLD_MULTIPLIER)
