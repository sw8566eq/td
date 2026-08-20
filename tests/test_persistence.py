import json

import persistence
from levels import Level


def make_branching_level(name="Test Level", **overrides):
    kwargs = dict(
        id="custom",
        name=name,
        path_cells=frozenset({(0, 0), (0, 1), (0, 2), (1, 1)}),
        spawn_cells=((0, 0), (0, 2)),
        goal_cells=((1, 1),),
        # Deliberately a different composition per spawn, and one wave
        # where (0, 2) sits out entirely -- exercises the per-spawn
        # wave_specs shape's round-trip through JSON, not just a
        # single-spawn level's.
        wave_specs=[{(0, 0): {"grunt": 3}}, {(0, 0): {"grunt": 2}, (0, 2): {"tank": 3}}],
        starting_gold=200,
        starting_lives=15,
        blocked_cells=frozenset({(5, 5)}),
        branch_weights={((0, 1), (1, 1)): 2.0},
    )
    kwargs.update(overrides)
    return Level(**kwargs)


def test_level_round_trips_through_to_dict_and_from_dict():
    level = make_branching_level()
    restored = persistence.level_from_dict(persistence.level_to_dict(level))

    assert restored.id == level.id
    assert restored.name == level.name
    assert restored.path_cells == level.path_cells
    assert set(restored.spawn_cells) == set(level.spawn_cells)
    assert set(restored.goal_cells) == set(level.goal_cells)
    assert restored.blocked_cells == level.blocked_cells
    assert restored.branch_weights == level.branch_weights
    assert restored.wave_specs == level.wave_specs
    assert restored.starting_gold == level.starting_gold
    assert restored.starting_lives == level.starting_lives


def test_to_dict_is_plain_json_serializable():
    level = make_branching_level()
    # Must not raise -- every value has to be a plain JSON type (no
    # frozensets/tuples-as-dict-keys survive a real json.dumps).
    json.dumps(persistence.level_to_dict(level))


def test_save_level_writes_a_json_file_and_list_custom_levels_finds_it(tmp_path):
    level = make_branching_level(name="Winding Canyon")
    path = persistence.save_level(level, directory=tmp_path)

    assert path.endswith(".json")
    assert (tmp_path / "winding-canyon.json").exists()

    [loaded] = persistence.list_custom_levels(directory=tmp_path)
    assert loaded.name == "Winding Canyon"
    assert loaded.path_cells == level.path_cells


def test_save_level_assigns_the_slug_as_the_saved_levels_id(tmp_path):
    level = make_branching_level(name="Winding Canyon")
    assert level.id == "custom"  # the in-memory placeholder id from Editor.to_level()

    persistence.save_level(level, directory=tmp_path)
    [loaded] = persistence.list_custom_levels(directory=tmp_path)
    assert loaded.id == "winding-canyon"


def test_save_level_avoids_filename_collisions_on_repeated_names(tmp_path):
    persistence.save_level(make_branching_level(name="Same Name"), directory=tmp_path)
    persistence.save_level(make_branching_level(name="Same Name"), directory=tmp_path)

    levels = persistence.list_custom_levels(directory=tmp_path)
    assert len(levels) == 2
    assert {level.id for level in levels} == {"same-name", "same-name-2"}


def test_list_custom_levels_on_a_missing_directory_returns_an_empty_list(tmp_path):
    assert persistence.list_custom_levels(directory=tmp_path / "does-not-exist") == []


def test_list_custom_levels_skips_a_corrupt_file_instead_of_raising(tmp_path):
    persistence.save_level(make_branching_level(name="Good Level"), directory=tmp_path)
    (tmp_path / "broken.json").write_text("{not valid json")
    (tmp_path / "wrong-shape.json").write_text(json.dumps({"unexpected": "shape"}))
    (tmp_path / "not-even-a-level.txt").write_text("ignored, not .json")

    levels = persistence.list_custom_levels(directory=tmp_path)
    assert [level.name for level in levels] == ["Good Level"]


def test_list_custom_levels_skips_a_file_whose_level_fails_its_own_validation(tmp_path):
    # A hand-edited file with a cyclic path -- syntactically fine JSON,
    # but Level.__post_init__ rejects it (via validate_topology, or
    # possibly its own wave/spawn-consistency checks first -- either way,
    # some ValueError, which is all this test actually cares about).
    bad_data = persistence.level_to_dict(make_branching_level(name="Good Level"))
    bad_data["path_cells"] = [[0, 0], [1, 0], [1, 1], [0, 1]]
    bad_data["spawn_cells"] = [[0, 0]]
    bad_data["goal_cells"] = [[1, 1]]
    (tmp_path / "cyclic.json").write_text(json.dumps(bad_data))
    persistence.save_level(make_branching_level(name="Good Level"), directory=tmp_path)

    levels = persistence.list_custom_levels(directory=tmp_path)
    assert [level.name for level in levels] == ["Good Level"]
