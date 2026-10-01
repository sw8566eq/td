"""Tests for Commanders -- run/commanders.py's registry, their meta-
progression unlocks, the Commander select screen, and what each one
actually starts a run with."""

import pygame
import pytest
from conftest import clear_mouse_mock, mock_mouse_pos

from core.game import GameState
from entities.tower import TOWER_TYPES
from persistence import save_state
from progression import meta_progression
from run import commanders
from run.commanders import COMMANDER_ORDER, COMMANDERS, DEFAULT_COMMANDER
from run.potions import POTIONS
from run.relics import RELICS


def test_every_commander_references_real_content():
    for key, commander in COMMANDERS.items():
        assert commander.key == key
        assert len(commander.starter_towers) == 3
        assert all(name in TOWER_TYPES for name in commander.starter_towers + commander.forged_towers)
        assert set(commander.forged_towers) <= set(commander.starter_towers)
        assert all(relic in RELICS for relic in commander.starting_relics)
        assert all(potion in POTIONS for potion in commander.starting_potions)
        # A starting relic must not need _apply_one_time_relic_bonus: the
        # run's lives are only captured on its first node, after this.
        assert all(RELICS[relic].starting_lives_bonus == 0 for relic in commander.starting_relics)


def test_every_non_default_commander_has_exactly_one_unlock():
    gated = [unlock.commander_key for unlock in meta_progression.COMMANDER_META_UNLOCKS.values()]
    assert sorted(gated) == sorted(key for key in COMMANDERS if key != DEFAULT_COMMANDER)


def test_unlocked_commanders_reads_recorded_unlocks_and_already_crossed_counters(tmp_path):
    path = str(tmp_path / "meta.json")
    assert meta_progression.unlocked_commanders(DEFAULT_COMMANDER, path) == {DEFAULT_COMMANDER}
    meta_progression.bump("runs_played", path=path)
    assert "alchemist" in meta_progression.unlocked_commanders(DEFAULT_COMMANDER, path)

    state = meta_progression.load_meta_progression(path)
    state["counters"]["bosses_defeated"] = 3  # crossed before the registry entry existed
    meta_progression.save_meta_progression(state, path)
    assert "engineer" in meta_progression.unlocked_commanders(DEFAULT_COMMANDER, path)


def test_a_locked_commander_cannot_be_picked(game):
    game._enter_commander_select()
    assert game.commander_unlocked == {DEFAULT_COMMANDER}
    game._choose_commander(COMMANDER_ORDER.index("engineer"))
    assert game.state == GameState.COMMANDER_SELECT
    assert game.active_run is None


def test_escape_backs_out_of_commander_select(game):
    game._enter_commander_select()
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU
    assert game.running


def test_click_off_any_card_does_nothing(game):
    game._enter_commander_select()
    game._handle_commander_select_click((1, 1))
    assert game.state == GameState.COMMANDER_SELECT


@pytest.mark.parametrize("key", COMMANDER_ORDER)
def test_each_commander_starts_the_run_with_its_own_kit(game, key):
    game.start_new_run(seed=1, commander=key)
    run, commander = game.active_run, COMMANDERS[key]
    assert run.commander == key
    assert run.unlocked_towers == list(commander.starter_towers)
    assert run.relics == list(commander.starting_relics)
    assert run.potions == list(commander.starting_potions)
    assert run.forged_towers == list(commander.forged_towers)


def test_picking_an_unlocked_commander_starts_that_run(game):
    meta_progression.bump("runs_played", path=game.meta_progression_path)
    game._enter_commander_select()
    game._handle_commander_select_click(game.commander_rects[COMMANDER_ORDER.index("alchemist")].center)
    assert game.state == GameState.MAP
    assert game.active_run.commander == "alchemist"


def test_daily_run_always_uses_the_default_commander(game):
    game.start_new_run(seed=1, is_daily=True, commander="engineer")
    assert game.active_run.commander == DEFAULT_COMMANDER


def test_engineer_places_a_forged_basic_at_level_two(game):
    from conftest import find_buildable_anchor

    game.start_new_run(seed=1, commander="engineer")
    game._enter_node(game.active_run.map.start_node_ids[0])
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    assert game.towers[0].level == 2


def test_commander_survives_save_and_resume(game):
    game.start_new_run(seed=1, commander="marksman")
    game._enter_node(game.active_run.map.start_node_ids[0])
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.active_run.commander == "marksman"


def test_a_save_with_an_unknown_commander_is_not_resumable(game):
    game.start_new_run(seed=1)
    game._enter_node(game.active_run.map.start_node_ids[0])
    game.active_run.commander = "nobody"
    game.save_run()
    assert save_state.load_run(game.save_path) is None


def test_commander_unlock_queues_a_toast(game):
    game._queue_meta_unlock_toasts(["unlock_marksman"])
    assert any("New commander unlocked: The Marksman" in toast.text for toast in game.achievement_toasts)


def test_render_commander_select_with_locked_and_hovered_cards(game):
    game._enter_commander_select()
    mock_mouse_pos(game.commander_rects[0].center)
    try:
        assert game._hovered_commander() == 0
        game.render()
    finally:
        clear_mouse_mock()
    game.commander_unlocked = set(COMMANDER_ORDER)
    game.render()


def test_commander_cards_fit_on_screen():
    from presentation import ui
    from support import settings

    for rect in ui.build_commander_card_rects(len(commanders.COMMANDER_ORDER)):
        assert 0 <= rect.left and rect.right <= settings.SCREEN_WIDTH
        assert rect.height == ui.COMMANDER_CARD_HEIGHT and rect.bottom < settings.SCREEN_HEIGHT - 60
