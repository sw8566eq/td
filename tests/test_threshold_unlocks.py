import json

from threshold_unlocks import (
    bump_counter,
    empty_counters_state,
    load_counters_state,
    parse_counters_state,
    save_counters_state,
    set_counter,
    unlock_crossed_thresholds,
)


class _FakeEntry:
    def __init__(self, counter, goal):
        self.counter = counter
        self.goal = goal


def test_empty_counters_state():
    assert empty_counters_state() == {"counters": {}, "unlocked": set()}


def test_empty_counters_state_returns_a_fresh_dict_each_call():
    # Regression guard: a shared mutable default would let mutating one
    # caller's "empty" state leak into another's.
    a = empty_counters_state()
    b = empty_counters_state()
    a["counters"]["x"] = 1
    a["unlocked"].add("y")
    assert b == {"counters": {}, "unlocked": set()}


def test_parse_counters_state_coerces_types():
    parsed = parse_counters_state({"counters": {"kills": "5"}, "unlocked": ["first_blood"]})
    assert parsed == {"counters": {"kills": 5}, "unlocked": {"first_blood"}}


def test_parse_counters_state_defaults_missing_keys():
    assert parse_counters_state({}) == {"counters": {}, "unlocked": set()}


def test_unlock_crossed_thresholds_returns_newly_crossed_keys():
    registry = {"a": _FakeEntry("kills", 1), "b": _FakeEntry("kills", 100)}
    state = {"counters": {"kills": 1}, "unlocked": set()}

    newly_unlocked = unlock_crossed_thresholds(registry, state, "kills")

    assert newly_unlocked == ["a"]
    assert state["unlocked"] == {"a"}


def test_unlock_crossed_thresholds_does_not_re_report_already_unlocked():
    registry = {"a": _FakeEntry("kills", 1)}
    state = {"counters": {"kills": 5}, "unlocked": {"a"}}

    assert unlock_crossed_thresholds(registry, state, "kills") == []


def test_unlock_crossed_thresholds_ignores_other_counters():
    registry = {"a": _FakeEntry("kills", 1)}
    state = {"counters": {"towers_built": 100}, "unlocked": set()}

    assert unlock_crossed_thresholds(registry, state, "towers_built") == []


def test_unlock_crossed_thresholds_can_cross_multiple_entries_at_once():
    registry = {"a": _FakeEntry("kills", 1), "b": _FakeEntry("kills", 5), "c": _FakeEntry("kills", 100)}
    state = {"counters": {"kills": 5}, "unlocked": set()}

    assert set(unlock_crossed_thresholds(registry, state, "kills")) == {"a", "b"}


# --- load_counters_state / save_counters_state / bump_counter / set_counter ---
#
# The shared load-mutate-save-return mechanics achievements.py/
# meta_progression.py's own load_*/save_*/bump()/set_counter() delegate to
# -- see this module's own docstring for why factoring these out here
# matters, not just unlock_crossed_thresholds above.

def test_load_counters_state_on_a_missing_file_returns_empty(tmp_path):
    assert load_counters_state(tmp_path / "does_not_exist.json") == {"counters": {}, "unlocked": set()}


def test_save_and_load_counters_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    state = {"counters": {"kills": 5}, "unlocked": {"a"}}

    save_counters_state(state, path, schema_version=1)

    assert load_counters_state(path) == state


def test_save_counters_state_writes_a_stable_sorted_unlocked_list(tmp_path):
    # sorted(), not whatever set iteration order happens to be -- so the
    # file diffs stably across saves with the same unlocked keys.
    path = tmp_path / "state.json"
    save_counters_state({"counters": {}, "unlocked": {"b", "a", "c"}}, path, schema_version=1)

    assert json.loads(path.read_text())["unlocked"] == ["a", "b", "c"]


def test_bump_counter_increments_and_returns_newly_unlocked_keys(tmp_path):
    path = tmp_path / "state.json"
    registry = {"a": _FakeEntry("kills", 1)}

    newly_unlocked = bump_counter(registry, "kills", amount=1, path=path, schema_version=1)

    assert newly_unlocked == ["a"]
    assert load_counters_state(path)["counters"]["kills"] == 1


def test_bump_counter_accumulates_across_calls(tmp_path):
    path = tmp_path / "state.json"
    registry = {}

    bump_counter(registry, "kills", amount=3, path=path, schema_version=1)
    bump_counter(registry, "kills", amount=4, path=path, schema_version=1)

    assert load_counters_state(path)["counters"]["kills"] == 7


def test_set_counter_takes_the_max_of_current_and_new_value(tmp_path):
    path = tmp_path / "state.json"
    registry = {}

    set_counter(registry, "distinct_levels_cleared", 5, path=path, schema_version=1)
    set_counter(registry, "distinct_levels_cleared", 2, path=path, schema_version=1)  # a worse count -- ignored

    assert load_counters_state(path)["counters"]["distinct_levels_cleared"] == 5


def test_set_counter_returns_newly_unlocked_keys(tmp_path):
    path = tmp_path / "state.json"
    registry = {"campaign_complete": _FakeEntry("distinct_levels_cleared", 11)}

    newly_unlocked = set_counter(registry, "distinct_levels_cleared", 11, path=path, schema_version=1)

    assert newly_unlocked == ["campaign_complete"]
