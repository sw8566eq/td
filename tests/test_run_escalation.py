from run_escalation import escalation_for_floor


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
