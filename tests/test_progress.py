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
