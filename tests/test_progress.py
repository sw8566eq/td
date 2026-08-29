import json

import progress


def test_load_progress_on_a_missing_file_returns_empty():
    assert progress.load_progress(path="/does/not/exist.json") == {}


def test_save_and_load_progress_round_trips(tmp_path):
    path = tmp_path / "progress.json"
    progress.save_progress({1: 15, 2: 8}, path=path)

    assert progress.load_progress(path=path) == {1: 15, 2: 8}


def test_mark_level_cleared_records_a_new_level(tmp_path):
    path = tmp_path / "progress.json"
    cleared = progress.mark_level_cleared(1, lives_remaining=12, path=path)

    assert cleared == {1: 12}
    assert progress.load_progress(path=path) == {1: 12}


def test_mark_level_cleared_keeps_the_best_result_across_repeat_clears(tmp_path):
    path = tmp_path / "progress.json"
    progress.mark_level_cleared(1, lives_remaining=5, path=path)
    progress.mark_level_cleared(1, lives_remaining=20, path=path)  # a better run
    progress.mark_level_cleared(1, lives_remaining=2, path=path)  # a worse run -- ignored

    assert progress.load_progress(path=path) == {1: 20}


def test_load_progress_on_a_corrupt_file_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("{not valid json")

    assert progress.load_progress(path=path) == {}


def test_load_progress_on_an_unexpected_shape_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps({"cleared": "not a dict"}))

    assert progress.load_progress(path=path) == {}


def test_is_unlocked_the_lowest_id_is_always_unlocked():
    levels = {1: "level one", 2: "level two"}
    assert progress.is_unlocked(1, levels, cleared={}) is True


def test_is_unlocked_a_later_level_needs_its_predecessor_cleared():
    levels = {1: "level one", 2: "level two", 3: "level three"}
    assert progress.is_unlocked(2, levels, cleared={}) is False
    assert progress.is_unlocked(2, levels, cleared={1: 10}) is True
    # Level 3 needs level 2 specifically, not just "some earlier level".
    assert progress.is_unlocked(3, levels, cleared={1: 10}) is False
    assert progress.is_unlocked(3, levels, cleared={1: 10, 2: 5}) is True
