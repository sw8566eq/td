import json

import meta_progression
from card_pool import STARTER_TOWERS
from tower import TOWER_TYPES


def test_load_meta_progression_on_a_missing_file_returns_empty_state():
    state = meta_progression.load_meta_progression(path="/does/not/exist.json")
    assert state == {"counters": {}, "unlocked": set()}


def test_save_and_load_meta_progression_round_trips(tmp_path):
    path = tmp_path / "meta_progression.json"
    state = {"counters": {"total_floors_cleared": 5}, "unlocked": {"unlock_knockback"}}
    meta_progression.save_meta_progression(state, path=path)

    assert meta_progression.load_meta_progression(path=path) == state


def test_load_meta_progression_on_a_corrupt_file_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "meta_progression.json"
    path.write_text("{not valid json")

    assert meta_progression.load_meta_progression(path=path) == {"counters": {}, "unlocked": set()}


def test_load_meta_progression_on_an_unexpected_shape_returns_empty_instead_of_raising(tmp_path):
    path = tmp_path / "meta_progression.json"
    path.write_text(json.dumps({"counters": "not a dict"}))

    assert meta_progression.load_meta_progression(path=path) == {"counters": {}, "unlocked": set()}


def test_bump_increments_the_named_counter(tmp_path):
    path = tmp_path / "meta_progression.json"
    meta_progression.bump("total_floors_cleared", amount=2, path=path)
    meta_progression.bump("total_floors_cleared", amount=1, path=path)

    assert meta_progression.load_meta_progression(path=path)["counters"]["total_floors_cleared"] == 3


def test_bump_defaults_to_incrementing_by_one(tmp_path):
    path = tmp_path / "meta_progression.json"
    meta_progression.bump("runs_played", path=path)
    meta_progression.bump("runs_played", path=path)

    assert meta_progression.load_meta_progression(path=path)["counters"]["runs_played"] == 2


def test_bump_returns_newly_crossed_unlock_keys(tmp_path):
    path = tmp_path / "meta_progression.json"
    newly_unlocked = meta_progression.bump("total_floors_cleared", amount=1, path=path)

    assert newly_unlocked == ["unlock_knockback"]
    assert meta_progression.load_meta_progression(path=path)["unlocked"] == {"unlock_knockback"}


def test_bump_does_not_re_report_an_already_unlocked_entry(tmp_path):
    path = tmp_path / "meta_progression.json"
    meta_progression.bump("total_floors_cleared", amount=1, path=path)  # unlocks unlock_knockback

    newly_unlocked = meta_progression.bump("total_floors_cleared", amount=1, path=path)  # 2, still < 3

    assert newly_unlocked == []


def test_bump_can_cross_multiple_thresholds_in_one_call(tmp_path):
    path = tmp_path / "meta_progression.json"
    newly_unlocked = meta_progression.bump("total_floors_cleared", amount=5, path=path)

    assert set(newly_unlocked) == {"unlock_knockback", "unlock_poison", "unlock_lightning"}


def test_bump_ignores_other_counters_thresholds(tmp_path):
    path = tmp_path / "meta_progression.json"
    newly_unlocked = meta_progression.bump("runs_played", amount=10, path=path)

    # runs_played crossing 10 must never unlock unlock_lightning
    # (total_floors_cleared, 10) just because the raw numbers line up.
    assert set(newly_unlocked) == {"unlock_sniper", "unlock_support"}


def test_every_meta_unlock_targets_a_real_non_starter_tower():
    for key, unlock in meta_progression.META_UNLOCKS.items():
        assert unlock.tower_name in TOWER_TYPES, key
        assert unlock.tower_name not in STARTER_TOWERS, key


def test_every_tower_is_either_a_starter_or_exactly_one_meta_unlock():
    # Regression guard: every registered tower must be reachable somehow --
    # either it's always available (STARTER_TOWERS) or exactly one
    # META_UNLOCKS entry grants it, never both and never neither.
    unlockable = [unlock.tower_name for unlock in meta_progression.META_UNLOCKS.values()]
    assert len(unlockable) == len(set(unlockable))  # no tower unlocked by two different entries
    assert set(STARTER_TOWERS) | set(unlockable) == set(TOWER_TYPES.keys())


def test_unlocked_tower_pool_is_empty_with_no_progress(tmp_path):
    path = tmp_path / "meta_progression.json"
    assert meta_progression.unlocked_tower_pool(path=path) == set()


def test_unlocked_tower_pool_reflects_crossed_thresholds(tmp_path):
    path = tmp_path / "meta_progression.json"
    meta_progression.bump("total_floors_cleared", amount=1, path=path)

    assert meta_progression.unlocked_tower_pool(path=path) == {"knockback"}
