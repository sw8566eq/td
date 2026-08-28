import json

import achievements


def test_load_achievements_on_a_missing_file_returns_empty_state():
    state = achievements.load_achievements(path="/does/not/exist.json")
    assert state == {"counters": {}, "unlocked": set()}


def test_save_and_load_achievements_round_trips(tmp_path):
    path = tmp_path / "achievements.json"
    state = {"counters": {"kills": 5}, "unlocked": {"first_blood"}}
    achievements.save_achievements(state, path=path)

    assert achievements.load_achievements(path=path) == state


def test_load_achievements_on_a_corrupt_file_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "achievements.json"
    path.write_text("{not valid json")

    assert achievements.load_achievements(path=path) == {"counters": {}, "unlocked": set()}


def test_load_achievements_on_an_unexpected_shape_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "achievements.json"
    path.write_text(json.dumps({"counters": "not a dict"}))

    assert achievements.load_achievements(path=path) == {"counters": {}, "unlocked": set()}


def test_bump_increments_the_named_counter(tmp_path):
    path = tmp_path / "achievements.json"
    achievements.bump("kills", amount=3, path=path)
    achievements.bump("kills", amount=4, path=path)

    assert achievements.load_achievements(path=path)["counters"]["kills"] == 7


def test_bump_defaults_to_incrementing_by_one(tmp_path):
    path = tmp_path / "achievements.json"
    achievements.bump("towers_built", path=path)
    achievements.bump("towers_built", path=path)

    assert achievements.load_achievements(path=path)["counters"]["towers_built"] == 2


def test_bump_returns_newly_crossed_achievement_keys(tmp_path):
    path = tmp_path / "achievements.json"
    newly_unlocked = achievements.bump("kills", amount=1, path=path)

    assert newly_unlocked == ["first_blood"]
    assert achievements.load_achievements(path=path)["unlocked"] == {"first_blood"}


def test_bump_does_not_re_report_an_already_unlocked_achievement(tmp_path):
    path = tmp_path / "achievements.json"
    achievements.bump("kills", amount=1, path=path)  # unlocks first_blood

    newly_unlocked = achievements.bump("kills", amount=1, path=path)  # kills == 2, still not centurion

    assert newly_unlocked == []


def test_bump_can_cross_multiple_thresholds_in_one_call(tmp_path):
    path = tmp_path / "achievements.json"
    newly_unlocked = achievements.bump("kills", amount=100, path=path)

    assert set(newly_unlocked) == {"first_blood", "centurion"}


def test_bump_ignores_other_counters_thresholds(tmp_path):
    path = tmp_path / "achievements.json"
    newly_unlocked = achievements.bump("towers_built", amount=1000, path=path)

    # towers_built crossing 1000 must never unlock "exterminator" (kills, 1000)
    # just because the raw numbers happen to line up.
    assert newly_unlocked == ["groundbreaker"]


def test_every_achievements_counter_is_a_real_registered_counter_name():
    # Guards against a typo'd counter name in the registry that Game would
    # then never actually bump anywhere.
    known_counters = {
        "kills", "towers_built", "towers_maxed", "towers_specialized",
        "levels_cleared", "waves_survived",
    }
    for key, achievement in achievements.ACHIEVEMENTS.items():
        assert achievement.counter in known_counters, key


def test_campaign_complete_goal_matches_the_live_levels_registry():
    from levels import LEVELS
    assert achievements.ACHIEVEMENTS["campaign_complete"].goal == len(LEVELS)
