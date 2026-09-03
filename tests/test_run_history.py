import json

import run_history


def test_load_run_history_on_a_missing_file_returns_empty():
    assert run_history.load_run_history(path="/does/not/exist.json") == {}


def test_save_and_load_run_history_round_trips(tmp_path):
    path = tmp_path / "run_history.json"
    run_history.save_run_history({123: 4, 456: 2}, path=path)

    assert run_history.load_run_history(path=path) == {123: 4, 456: 2}


def test_record_run_result_records_a_new_seed(tmp_path):
    path = tmp_path / "run_history.json"
    best = run_history.record_run_result(123, floors_cleared=3, path=path)

    assert best == {123: 3}
    assert run_history.load_run_history(path=path) == {123: 3}


def test_record_run_result_keeps_the_best_result_across_repeat_attempts(tmp_path):
    path = tmp_path / "run_history.json"
    run_history.record_run_result(123, floors_cleared=2, path=path)
    run_history.record_run_result(123, floors_cleared=5, path=path)  # a better run
    run_history.record_run_result(123, floors_cleared=1, path=path)  # a worse run -- ignored

    assert run_history.load_run_history(path=path) == {123: 5}


def test_record_run_result_tracks_separate_seeds_independently(tmp_path):
    path = tmp_path / "run_history.json"
    run_history.record_run_result(123, floors_cleared=3, path=path)
    run_history.record_run_result(456, floors_cleared=1, path=path)

    assert run_history.load_run_history(path=path) == {123: 3, 456: 1}


def test_load_run_history_on_a_corrupt_file_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "run_history.json"
    path.write_text("{not valid json")

    assert run_history.load_run_history(path=path) == {}


def test_load_run_history_on_an_unexpected_shape_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "run_history.json"
    path.write_text(json.dumps({"best_floors_cleared": "not a dict"}))

    assert run_history.load_run_history(path=path) == {}
