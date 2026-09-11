import pytest

from run_escalation import (
    ELITE_GOLD_MULTIPLIER,
    ELITE_HP_MULTIPLIER,
    ELITE_SPEED_MULTIPLIER,
    FloorEscalation,
    apply_elite_multiplier,
    escalation_for_floor,
)


def test_floor_zero_is_a_no_op():
    escalation = escalation_for_floor(0)
    assert escalation.enemy_hp_multiplier == 1.0
    assert escalation.enemy_speed_multiplier == 1.0
    assert escalation.enemy_gold_multiplier == 1.0


def test_escalation_grows_monotonically_with_floor_index():
    # Subsumes "floor 5 > floor 0" as one step of this same chain -- no
    # separate test needed for that special case.
    previous = escalation_for_floor(0)
    for floor_index in range(1, 20):
        current = escalation_for_floor(floor_index)
        assert current.enemy_hp_multiplier > previous.enemy_hp_multiplier
        assert current.enemy_speed_multiplier > previous.enemy_speed_multiplier
        assert current.enemy_gold_multiplier > previous.enemy_gold_multiplier
        previous = current


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
