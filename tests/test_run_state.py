from run_state import RunState


def _run(**overrides):
    kwargs = dict(
        seed=1234, floor_sequence=(1, 4, 7), difficulty="normal",
        unlocked_towers=["basic", "cannon", "frost"],
    )
    kwargs.update(overrides)
    return RunState(**kwargs)


def test_defaults():
    run = _run()
    assert run.floor_index == 0
    assert run.lives == 0
    assert run.gold == 0
    assert run.floors_cleared == 0
    assert run.relics == []
    assert run.is_daily is False


def test_relics_default_is_not_shared_across_instances():
    # Regression guard: a plain `relics: list = []` default would share one
    # mutable list across every RunState -- field(default_factory=list) is
    # what run_state.py actually uses, this just proves it.
    a = _run()
    b = _run()
    a.relics.append("something")
    assert b.relics == []


def test_current_level_id_reads_floor_sequence_at_floor_index():
    run = _run(floor_sequence=(2, 5, 9))
    assert run.current_level_id == 2
    run.floor_index = 2
    assert run.current_level_id == 9


def test_is_final_floor_true_only_on_the_last_index():
    run = _run(floor_sequence=(2, 5, 9))
    assert run.is_final_floor is False
    run.floor_index = 1
    assert run.is_final_floor is False
    run.floor_index = 2
    assert run.is_final_floor is True


def test_is_final_floor_true_for_a_single_floor_sequence():
    run = _run(floor_sequence=(3,))
    assert run.is_final_floor is True


def test_floors_cleared_tracks_floor_index():
    run = _run(floor_sequence=(2, 5, 9))
    assert run.floors_cleared == 0
    run.floor_index = 2
    assert run.floors_cleared == 2
