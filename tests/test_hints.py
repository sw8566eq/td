"""progression/hints.py -- the Field Notes registry, its seen-set file and
the one-at-a-time display queue (pure, no pygame)."""

import json

import pytest

from progression import hints
from progression.hints import (
    HINT_DISPLAY_SECONDS,
    HINTS,
    HintTracker,
    hints_for,
    load_seen,
    save_seen,
)

# Player-facing names only (see AGENTS.md's code-identifier table).
_CODE_NAMES = ("ascension", "Ascension", "Smith", "Compendium", "potion belt", "boss relic", "Blessing")


def test_registry_has_a_reasonable_number_of_short_hints():
    assert 15 <= len(HINTS) <= 35
    for key, hint in HINTS.items():
        assert hint.trigger and hint.title and hint.text, key
        assert len(hint.text) <= 160, key  # 1-2 lines on the board's panel


@pytest.mark.parametrize("key", sorted(HINTS))
def test_hint_text_uses_player_facing_names(key):
    text = f"{HINTS[key].title} {HINTS[key].text}"
    for name in _CODE_NAMES:
        assert name not in text, (key, name)


def test_hints_for_groups_by_trigger_and_ignores_unknown_triggers():
    assert "node_shop" in hints_for("node_shop")
    assert set(hints_for("wave_cleared")) == {"early_call", "move_towers"}
    assert hints_for("no_such_trigger") == ()


def test_load_seen_missing_file_is_empty(tmp_path):
    assert load_seen(str(tmp_path / "hints.json")) == set()


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '{"seen": 5}'])
def test_load_seen_falls_back_on_a_corrupt_file(tmp_path, content):
    path = tmp_path / "hints.json"
    path.write_text(content)
    assert load_seen(str(path)) == set()


def test_load_seen_drops_non_string_entries(tmp_path):
    path = tmp_path / "hints.json"
    path.write_text('{"seen": ["relic", 3, null]}')
    assert load_seen(str(path)) == {"relic"}


def test_save_then_load_round_trips(tmp_path):
    path = str(tmp_path / "hints.json")
    save_seen({"relic", "curse"}, path)
    assert load_seen(path) == {"relic", "curse"}
    with open(path) as f:
        assert json.load(f)["schema_version"] == hints.SCHEMA_VERSION


def make_tracker(tmp_path, **kwargs):
    return HintTracker.load(str(tmp_path / "hints.json"), **kwargs)


def test_notify_shows_a_hint_and_marks_it_seen_on_disk(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.notify("node_shop")
    assert tracker.current == "node_shop"
    assert load_seen(tracker.path) == {"node_shop"}


def test_a_seen_hint_never_shows_again_even_after_reloading(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.notify("node_shop")
    tracker.dismiss()
    tracker.notify("node_shop")
    assert tracker.current is None
    reloaded = make_tracker(tmp_path)
    reloaded.notify("node_shop")
    assert reloaded.current is None


def test_queue_shows_one_hint_at_a_time_in_order(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.notify("node_shop", "node_event")
    tracker.notify("node_rest", "node_event")  # already queued -- not doubled
    shown = []
    while tracker.current is not None:
        shown.append(tracker.current)
        assert len({tracker.current, *tracker.pending}) == 1 + len(tracker.pending)
        tracker.dismiss()
    assert shown == ["node_shop", "node_event", "node_rest"]


def test_a_queued_hint_is_not_marked_seen_until_shown(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.notify("node_shop", "node_event")
    assert load_seen(tracker.path) == {"node_shop"}
    assert make_tracker(tmp_path).seen == {"node_shop"}


def test_update_times_a_hint_out_and_advances_the_queue(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.update(1.0)  # nothing shown -- harmless
    tracker.notify("node_shop", "node_event")
    tracker.update(HINT_DISPLAY_SECONDS - 0.5)
    assert tracker.current == "node_shop"
    tracker.update(0.5)
    assert tracker.current == "node_event"
    assert tracker.elapsed == 0.0
    tracker.update(HINT_DISPLAY_SECONDS)
    assert tracker.current is None


def test_disabled_tracker_suppresses_and_never_marks_seen(tmp_path):
    tracker = make_tracker(tmp_path, enabled=False)
    tracker.notify("node_shop")
    assert tracker.current is None and tracker.pending == []
    assert tracker.seen == set()


def test_turning_hints_off_drops_the_queue_and_keeps_unseen_ones(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.notify("node_shop", "node_event")
    tracker.set_enabled(False)
    assert tracker.current is None and tracker.pending == []
    tracker.set_enabled(True)
    tracker.notify("node_event")
    assert tracker.current == "node_event"


def test_reset_forgets_every_seen_hint(tmp_path):
    tracker = make_tracker(tmp_path)
    tracker.notify("node_shop", "node_event")
    tracker.reset()
    assert tracker.current is None and tracker.pending == [] and tracker.seen == set()
    assert load_seen(tracker.path) == set()
    tracker.notify("node_shop")
    assert tracker.current == "node_shop"
