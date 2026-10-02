"""Tests for the run's opening blessing (events.BLESSING, Game._enter_blessing)."""

import random

import pygame
import pytest

from core.game import GameState
from run import events, potions
from run.events import BLESSING, EVENTS


def _blessed_run(game, seed=1):
    game.start_new_run(seed=seed)
    game._enter_blessing()
    return game.active_run


def test_blessing_is_never_an_ordinary_event():
    assert BLESSING.key not in EVENTS
    for seed in range(50):
        assert events.pick_event(random.Random(seed)) is not BLESSING


def test_choosing_a_blessing_then_continuing_goes_to_the_map_without_visiting_a_node(game):
    run = _blessed_run(game)
    game.render()
    game._handle_event_click(game.event_option_rects[1].center)  # supplies
    assert run.shop_currency == 15
    game.render()
    game._handle_keydown(pygame.K_SPACE)
    assert game.state == GameState.MAP
    assert run.visited_node_ids == [] and run.current_node_id is None
    assert game.event_is_blessing is False


def test_dark_bargain_grants_two_relics_and_a_curse(game):
    run = _blessed_run(game)
    starting = list(run.relics)
    game._resolve_event_choice(3)
    gained = [key for key in run.relics if key not in starting]
    from run.relics import RELICS
    assert sum(RELICS[key].is_curse for key in gained) == 1
    assert sum(not RELICS[key].is_curse for key in gained) == 2
    assert "extra_relic" in game.event_resolution


def test_forge_blessing_forges_and_gives_a_potion(game):
    run = _blessed_run(game)
    game._resolve_event_choice(2)
    assert len(run.forged_towers) == 1
    assert len(run.potions) == 1 and run.potions[0] in potions.POTIONS


def test_blessing_is_deterministic_per_seed(game):
    run = _blessed_run(game, seed=9)
    game._resolve_event_choice(0)
    first = list(run.relics)
    run = _blessed_run(game, seed=9)
    game._resolve_event_choice(0)
    assert run.relics == first


@pytest.mark.parametrize("leave", ["click", "key"])
def test_an_ordinary_event_still_marks_its_node_visited(game, leave):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "event"])
    game._enter_node("1-0")
    assert game.event_is_blessing is False
    game._resolve_event_choice(len(game.event_options) - 1)
    if leave == "click":
        game._handle_event_click((1, 1))
    else:
        game._handle_keydown(pygame.K_SPACE)
    assert game.active_run.visited_node_ids == ["1-0"]


def test_four_event_options_fit_on_screen_with_room_for_the_hint():
    from presentation import ui
    from support import settings

    rects = ui.build_event_option_rects(len(BLESSING.options))
    assert rects[-1].bottom + 60 < settings.SCREEN_HEIGHT
    assert rects[0].top > 200  # below the event's own prompt
