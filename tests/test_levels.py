import pytest

import settings
from enemy import ENEMY_TYPES
from levels import LEVELS, Level, _corridor_level, generate_default_waves
from run_map import BOSS_LEVEL_IDS


def test_all_registered_levels_have_in_bounds_path_cells():
    for level in LEVELS.values():
        for col, row in level.path_cells:
            assert 0 <= col < settings.GRID_COLS
            assert 0 <= row < settings.GRID_ROWS


def test_all_registered_levels_reference_known_enemy_types():
    for level in LEVELS.values():
        for wave in level.wave_specs:
            for composition in wave.values():
                for enemy_name in composition:
                    assert enemy_name in ENEMY_TYPES


def test_level_rejects_unknown_enemy_type_in_wave_specs():
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Bad Level",
            path_cells=frozenset({(0, 0), (1, 0)}),
            spawn_cells=((0, 0),),
            goal_cells=((1, 0),),
            wave_specs=[{(0, 0): {"not_a_real_enemy": 3}}],
        )


def test_level_rejects_a_wave_with_no_enemies_in_it():
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Empty Wave Level",
            path_cells=frozenset({(0, 0), (1, 0)}),
            spawn_cells=((0, 0),),
            goal_cells=((1, 0),),
            wave_specs=[{(0, 0): {"grunt": 3}}, {}],
        )


def test_level_rejects_a_wave_whose_spawn_has_no_enemies_in_it():
    # A wave dict that has a spawn key but nothing under it -- same
    # "nothing to spawn" problem as an empty wave dict entirely, just one
    # level of nesting deeper.
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Empty Spawn Composition Level",
            path_cells=frozenset({(0, 0), (1, 0)}),
            spawn_cells=((0, 0),),
            goal_cells=((1, 0),),
            wave_specs=[{(0, 0): {}}],
        )


def test_level_rejects_a_wave_referencing_a_spawn_not_in_spawn_cells():
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Orphaned Spawn Level",
            path_cells=frozenset({(0, 0), (1, 0)}),
            spawn_cells=((0, 0),),
            goal_cells=((1, 0),),
            wave_specs=[{(0, 0): {"grunt": 1}, (5, 5): {"grunt": 1}}],
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
            wave_specs=[{(0, 0): {"grunt": 1}}],
        )


def test_level_rejects_a_spawn_disconnected_from_the_rest_of_the_path():
    with pytest.raises(ValueError):
        Level(
            id=999,
            name="Disconnected Level",
            path_cells=frozenset({(0, 0), (1, 0), (2, 0), (10, 5)}),
            spawn_cells=((0, 0),),
            goal_cells=((2, 0),),
            wave_specs=[{(0, 0): {"grunt": 1}}],
        )


def test_level_accepts_different_compositions_per_spawn_in_the_same_wave():
    Level(
        id=999,
        name="Multi-spawn Level",
        path_cells=frozenset({(0, 0), (0, 1), (0, 2), (1, 1)}),
        spawn_cells=((0, 0), (0, 2)),
        goal_cells=((1, 1),),
        wave_specs=[{(0, 0): {"grunt": 3}, (0, 2): {"tank": 1}}],
    )  # must not raise


def test_generate_default_waves_ramps_enemy_count_per_wave():
    waves = generate_default_waves((0, 0), total_waves=3, enemy_type="grunt", base_count=5, count_step=2)
    assert waves == [
        {(0, 0): {"grunt": 5}},
        {(0, 0): {"grunt": 7}},
        {(0, 0): {"grunt": 9}},
    ]


def test_corridor_level_spawns_at_the_first_corner_and_goals_at_the_last():
    corners = [(0, 0), (3, 0), (3, 3)]
    level = _corridor_level(42, "Test Corridor", corners, [{(0, 0): {"grunt": 1}}])
    assert level.id == 42
    assert level.name == "Test Corridor"
    assert level.spawn_cells == ((0, 0),)
    assert level.goal_cells == ((3, 3),)
    assert level.path_cells == frozenset({(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (3, 2), (3, 3)})


def test_corridor_level_passes_wave_specs_through_unchanged():
    wave_specs = [{(0, 0): {"grunt": 2}}]
    level = _corridor_level(1, "Test", [(0, 0), (1, 0)], wave_specs)
    assert level.wave_specs == wave_specs


def test_corridor_level_defaults_gold_and_lives():
    level = _corridor_level(1, "Test", [(0, 0), (1, 0)], [{(0, 0): {"grunt": 1}}])
    assert level.starting_gold == 150
    assert level.starting_lives == 20


def test_corridor_level_accepts_overridden_gold_and_lives():
    level = _corridor_level(1, "Test", [(0, 0), (1, 0)], [{(0, 0): {"grunt": 1}}],
                             starting_gold=999, starting_lives=1)
    assert level.starting_gold == 999
    assert level.starting_lives == 1


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
    species_seen = {
        name
        for wave in level.wave_specs
        for composition in wave.values()
        for name in composition
    }
    # final_boss/final_boss_shielded are deliberately excluded -- reserved
    # for the run map's own boss-tier levels (16/17, see run_map.
    # BOSS_LEVEL_IDS), never an ordinary corridor level's final wave
    # (that's still plain "boss" -- see
    # test_every_levels_final_wave_includes_a_boss_or_final_boss below).
    assert species_seen == set(ENEMY_TYPES) - {"final_boss", "final_boss_shielded"}


def test_at_least_two_levels_are_registered():
    assert 1 in LEVELS
    assert 2 in LEVELS


def test_at_least_six_levels_are_registered():
    assert len(LEVELS) >= 6


def test_no_non_boss_level_exceeds_five_waves():
    # Regression: Levels 5 and 10 used to run a sixth, bigger-numbers-only
    # wave before their double-boss finale -- trimmed after playtesting
    # found a 6-wave fight dragged even when the fight itself was easy,
    # which it structurally can be: every non-boss-tier level (including
    # these two) is eligible to be drawn for a run's very first node (row
    # 0, before any relics/upgrades exist -- see
    # run_map._level_pool_for_row), so "the hardest corridor level"
    # having the most waves in the game made it the single worst possible
    # opening fight a new run could roll. Boss-tier levels are exempt --
    # they're the run's deliberately climactic final fights, never
    # reachable as an early encounter.
    for level_id, level in LEVELS.items():
        if level_id in BOSS_LEVEL_IDS:
            continue
        assert len(level.wave_specs) <= 5, level.name


def test_every_levels_path_is_distinct():
    # A copy-paste mistake while hand-authoring a new level's corner list is
    # much easier to make silently once there are several -- check every
    # pair, not just level 2 against level 1.
    ids = sorted(LEVELS)
    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1:]:
            assert LEVELS[id_a].path_cells != LEVELS[id_b].path_cells, (id_a, id_b)


def test_at_least_one_registered_level_has_more_than_one_spawn():
    # Levels 1-5 are all terse single-spawn corridors (see
    # _single_spawn_waves) -- at least one registered level should actually
    # exercise the full multi-spawn wave_specs shape a player can build in
    # the map editor too.
    assert any(len(level.spawn_cells) > 1 for level in LEVELS.values())


def _wave_species(wave):
    return {name for composition in wave.values() for name in composition}


# The run map's two boss-tier levels deliberately use two DIFFERENT
# final-boss species (see levels.py's own comment on Levels 16-17) rather
# than sharing one -- so every test below that needs "the final-boss
# species this level uses" looks it up per-level here instead of assuming
# a single shared string the way an earlier, single-boss-species version
# of this test file could.
_FINAL_BOSS_SPECIES_BY_LEVEL = {16: "final_boss", 17: "final_boss_shielded"}
_FINAL_BOSS_SPECIES = set(_FINAL_BOSS_SPECIES_BY_LEVEL.values())


def test_final_boss_species_by_level_covers_every_boss_level_id():
    # A regular test, not a bare module-level assert, so a mismatch (e.g.
    # BOSS_LEVEL_IDS growing without a matching entry added here) shows up
    # as a normal, individually-reportable test failure like every other
    # invariant check in this file, rather than a collection-time error.
    assert set(_FINAL_BOSS_SPECIES_BY_LEVEL) == set(BOSS_LEVEL_IDS)


def test_every_levels_final_wave_includes_a_boss_or_final_boss():
    # Levels 16/17 (run_map.BOSS_LEVEL_IDS) are the one exception: their
    # final wave uses their own final-boss species (see
    # _FINAL_BOSS_SPECIES_BY_LEVEL) instead of the ordinary "boss" every
    # other level's final wave still uses -- see
    # test_boss_tier_levels_use_the_final_boss_species below for the
    # positive assertion that they specifically do.
    for level_id, level in LEVELS.items():
        final_wave = level.wave_specs[-1]
        species = _wave_species(final_wave)
        boss_species = _FINAL_BOSS_SPECIES_BY_LEVEL.get(level_id, "boss")
        assert boss_species in species, level_id
        boss_count = sum(composition.get(boss_species, 0) for composition in final_wave.values())
        assert boss_count >= 1, level_id


def test_boss_tier_levels_use_the_final_boss_species_not_the_ordinary_one():
    for level_id in BOSS_LEVEL_IDS:
        final_wave = LEVELS[level_id].wave_specs[-1]
        assert "boss" not in _wave_species(final_wave), level_id


def test_boss_tier_levels_use_distinct_final_boss_species():
    # Level 16 and Level 17 are genuinely distinct fights, not just
    # different topology around an identical boss -- see levels.py's own
    # comment on why.
    assert len(set(_FINAL_BOSS_SPECIES_BY_LEVEL.values())) == len(_FINAL_BOSS_SPECIES_BY_LEVEL)


def test_non_boss_tier_levels_never_use_a_final_boss_species():
    for level_id, level in LEVELS.items():
        if level_id in BOSS_LEVEL_IDS:
            continue
        for wave in level.wave_specs:
            assert not (_wave_species(wave) & _FINAL_BOSS_SPECIES), level_id


def test_boss_does_not_appear_before_the_final_wave():
    for level_id, level in LEVELS.items():
        boss_species = _FINAL_BOSS_SPECIES_BY_LEVEL.get(level_id, "boss")
        for wave in level.wave_specs[:-1]:
            assert boss_species not in _wave_species(wave), level_id


def test_level_7_is_a_single_spawn_branching_into_two_goals():
    level = LEVELS[7]
    assert len(level.spawn_cells) == 1
    assert len(level.goal_cells) == 2


def test_level_8_merges_two_spawns_then_branches_into_two_goals():
    level = LEVELS[8]
    assert len(level.spawn_cells) == 2
    assert len(level.goal_cells) == 2


def test_level_9_merges_three_spawns_into_a_single_goal():
    level = LEVELS[9]
    assert len(level.spawn_cells) == 3
    assert len(level.goal_cells) == 1


def test_at_least_one_registered_level_branches_into_multiple_goals():
    # Levels 1-6 all funnel into exactly one goal each (even Confluence,
    # which merges spawns but still has a single goal) -- Level 7/8 are the
    # first to actually branch, the mirror image of the existing
    # multi-spawn-merge coverage above.
    assert any(len(level.goal_cells) > 1 for level in LEVELS.values())
