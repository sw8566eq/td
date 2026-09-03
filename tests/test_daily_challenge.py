import json
from datetime import date

import daily_challenge


def test_todays_seed_is_deterministic_for_a_given_date():
    assert daily_challenge.todays_seed(date(2026, 9, 3)) == 20260903
    assert daily_challenge.todays_seed(date(2026, 9, 3)) == daily_challenge.todays_seed(date(2026, 9, 3))


def test_todays_seed_differs_across_dates():
    assert daily_challenge.todays_seed(date(2026, 9, 3)) != daily_challenge.todays_seed(date(2026, 9, 4))


def test_level_id_for_seed_is_always_a_multi_lane_level():
    for seed in range(20260101, 20260101 + 30):
        assert daily_challenge.level_id_for_seed(seed) in daily_challenge.MULTI_LANE_LEVEL_IDS


def test_level_id_for_seed_is_deterministic():
    seed = daily_challenge.todays_seed(date(2026, 9, 3))
    assert daily_challenge.level_id_for_seed(seed) == daily_challenge.level_id_for_seed(seed)


def test_load_daily_challenge_on_a_missing_file_returns_empty():
    assert daily_challenge.load_daily_challenge(path="/does/not/exist.json") == {}


def test_save_and_load_daily_challenge_round_trips(tmp_path):
    path = tmp_path / "daily_challenge.json"
    daily_challenge.save_daily_challenge({20260903: 12, 20260904: 5}, path=path)

    assert daily_challenge.load_daily_challenge(path=path) == {20260903: 12, 20260904: 5}


def test_record_result_records_a_new_seed(tmp_path):
    path = tmp_path / "daily_challenge.json"
    best = daily_challenge.record_result(20260903, waves_survived=7, path=path)

    assert best == {20260903: 7}
    assert daily_challenge.load_daily_challenge(path=path) == {20260903: 7}


def test_record_result_keeps_the_best_result_across_repeat_attempts(tmp_path):
    path = tmp_path / "daily_challenge.json"
    daily_challenge.record_result(20260903, waves_survived=5, path=path)
    daily_challenge.record_result(20260903, waves_survived=12, path=path)  # a better run
    daily_challenge.record_result(20260903, waves_survived=3, path=path)  # a worse run -- ignored

    assert daily_challenge.load_daily_challenge(path=path) == {20260903: 12}


def test_record_result_tracks_separate_seeds_independently(tmp_path):
    path = tmp_path / "daily_challenge.json"
    daily_challenge.record_result(20260903, waves_survived=7, path=path)
    daily_challenge.record_result(20260904, waves_survived=4, path=path)

    assert daily_challenge.load_daily_challenge(path=path) == {20260903: 7, 20260904: 4}


def test_load_daily_challenge_on_a_corrupt_file_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "daily_challenge.json"
    path.write_text("{not valid json")

    assert daily_challenge.load_daily_challenge(path=path) == {}


def test_load_daily_challenge_on_an_unexpected_shape_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "daily_challenge.json"
    path.write_text(json.dumps({"best_waves": "not a dict"}))

    assert daily_challenge.load_daily_challenge(path=path) == {}
