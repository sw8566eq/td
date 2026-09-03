from threshold_unlocks import empty_counters_state, parse_counters_state, unlock_crossed_thresholds


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
