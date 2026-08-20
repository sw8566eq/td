import pytest

import settings
from enemy import ENEMY_TYPES
from levels import LEVELS, Level, generate_default_waves


def test_all_registered_levels_have_in_bounds_path_cells():
    for level in LEVELS.values():
        for col, row in level.path_cells:
            assert 0 <= col < settings.GRID_COLS
            assert 0 <= row < settings.GRID_ROWS


def test_all_registered_levels_reference_known_enemy_types():
    for level in LEVELS.values():
        for wave in level.wave_specs:
            for enemy_name in wave:
                assert enemy_name in ENEMY_TYPES


def test_level_rejects_unknown_enemy_type_in_wave_specs():
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Bad Level",
            path_cells=frozenset({(0, 0), (1, 0)}),
            spawn_cells=((0, 0),),
            goal_cells=((1, 0),),
            wave_specs=[{"not_a_real_enemy": 3}],
        )


def test_level_rejects_a_wave_with_no_enemies_in_it():
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Empty Wave Level",
            path_cells=frozenset({(0, 0), (1, 0)}),
            spawn_cells=((0, 0),),
            goal_cells=((1, 0),),
            wave_specs=[{"grunt": 3}, {}],
        )


def test_level_rejects_empty_wave_specs():
    # WaveManager assumes at least one wave -- _begin_wave() indexes
    # wave_specs[0] unconditionally the moment the first wave starts, so
    # this must fail clearly here rather than crash deep inside
    # WaveManager the first time a level with no waves is played.
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Empty Level",
            path_cells=frozenset({(0, 0), (1, 0)}),
            spawn_cells=((0, 0),),
            goal_cells=((1, 0),),
            wave_specs=[],
        )


def test_level_rejects_a_cyclic_path():
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Loopy Level",
            path_cells=frozenset({(0, 0), (1, 0), (1, 1), (0, 1)}),
            spawn_cells=((0, 0),),
            goal_cells=((1, 1),),
            wave_specs=[{"grunt": 1}],
        )


def test_level_rejects_a_spawn_disconnected_from_the_rest_of_the_path():
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Disconnected Level",
            path_cells=frozenset({(0, 0), (1, 0), (2, 0), (10, 5)}),
            spawn_cells=((0, 0),),
            goal_cells=((2, 0),),
            wave_specs=[{"grunt": 1}],
        )


def test_generate_default_waves_ramps_enemy_count_per_wave():
    waves = generate_default_waves(total_waves=3, enemy_type="grunt", base_count=5, count_step=2)
    assert waves == [{"grunt": 5}, {"grunt": 7}, {"grunt": 9}]


def test_level_1_is_registered_and_playable():
    level = LEVELS[1]
    assert len(level.path_cells) >= 2
    assert len(level.spawn_cells) >= 1
    assert len(level.goal_cells) >= 1
    assert len(level.wave_specs) > 0
    assert level.starting_gold > 0
    assert level.starting_lives > 0


def test_level_1_introduces_every_enemy_species_across_its_waves():
    level = LEVELS[1]
    species_seen = {name for wave in level.wave_specs for name in wave}
    assert species_seen == set(ENEMY_TYPES)


def test_at_least_two_levels_are_registered():
    assert 1 in LEVELS
    assert 2 in LEVELS


def test_level_2_has_a_distinct_path_from_level_1():
    assert LEVELS[2].path_cells != LEVELS[1].path_cells


def test_every_levels_final_wave_includes_a_boss():
    for level_id, level in LEVELS.items():
        final_wave = level.wave_specs[-1]
        assert "boss" in final_wave, level_id
        assert final_wave["boss"] >= 1, level_id


def test_boss_does_not_appear_before_the_final_wave():
    for level_id, level in LEVELS.items():
        for wave in level.wave_specs[:-1]:
            assert "boss" not in wave, level_id
