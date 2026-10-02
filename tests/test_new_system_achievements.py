"""Achievements for the run systems added after v1.0: forging, Ascension,
and curses -- each counter bumped from Game, sandbox-gated."""

import random

from progression import achievements
from run import events


def _counters(game):
    return achievements.load_achievements(game.achievements_path)["counters"]


def test_forging_at_rest_counts(game):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "rest"])
    game._enter_node("1-0")
    game._choose_rest_option(1)
    game._forge_tower(game.rest_smith_choices[0])
    assert _counters(game)["towers_forged"] == 1
    assert "apprentice_smith" in achievements.load_achievements(game.achievements_path)["unlocked"]


def test_event_forge_and_curse_count(game):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "event"], lives=10, shop_currency=50, relics=["leaky_coffers", "warped_lenses"])
    game.active_run.current_node_id = "1-0"
    game.current_event = events.EVENTS["ancient_forge"]
    game.event_options = list(game.current_event.options)
    game._resolve_event_choice(1)
    assert _counters(game)["towers_forged"] == 1

    game.current_event = events.EVENTS["gilded_coffer"]
    game.event_options = list(game.current_event.options)
    game._resolve_event_choice(0)
    assert _counters(game)["curses_held_at_once"] == 3
    assert "cursebearer" in achievements.load_achievements(game.achievements_path)["unlocked"]


def test_ascension_unlock_records_the_highest_level(game):
    from test_ascension import _ascended_run

    _ascended_run(game, ["combat", "boss"], 4)
    game.highest_ascension = game.selected_ascension = 4
    game._handle_boss_defeated()
    assert _counters(game)["ascension_reached"] == 5
    assert "ascendant" in achievements.load_achievements(game.achievements_path)["unlocked"]


def test_max_counters_never_record_in_sandbox(game):
    game.sandbox = True
    game._record_achievement_max("ascension_reached", 9)
    assert "ascension_reached" not in _counters(game)
    random.seed(0)
