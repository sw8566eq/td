"""Field Notes as driven by Game: each trigger fires its hint once, the
Settings toggle/reset, the queue's one-at-a-time display, and the panel's
click-to-dismiss and per-state drawing."""

import pygame
import pytest
from conftest import (
    find_buildable_anchor,
    finish_all_waves,
    make_game,
    make_linear_run_map,
    quit_pygame_keeping_the_mixer,
    start_first_floor,
)

from core.game import GameState
from entities.enemy import ENEMY_TYPES
from entities.tower import TOWER_TYPES
from presentation import ui
from progression import hints
from run import modules, potions, veterancy


def queued(game):
    """Every hint shown or waiting, in display order."""
    return ([game.hints.current] if game.hints.current else []) + list(game.hints.pending)


def drain(game):
    while game.hints.current is not None:
        game.hints.dismiss()


def assert_fires_once(game, key, trigger_again):
    assert key in queued(game)
    drain(game)
    trigger_again()
    assert key not in queued(game)
    assert key in hints.load_seen(game.hints_path)


def place(game, name="basic"):
    game.selected_tower_name = name
    if game.active_run is not None and name not in game.active_run.unlocked_towers:
        game.active_run.unlocked_towers.append(name)
        game._rebuild_button_rects()
    game.economy.gold = 10_000
    assert game.try_place_tower(*find_buildable_anchor(game))
    return game.towers[-1]


def practice(game):
    """Load a Practice level and run its first PLAYING frame, where the
    fight's Field Notes are notified."""
    game.load_level(1, sandbox=True)  # Practice shows hints too
    game.state = GameState.PLAYING
    game.update(0.0)


def path_anchor(game, tower_cls):
    n = game.grid.subtiles_per_tile
    for col in range(0, game.grid.sub_cols, n):
        for row in range(0, game.grid.sub_rows, n):
            if game._is_buildable_for(tower_cls, col, row):
                return col, row
    raise AssertionError("no path tile free")


def linear_run(game, node_types):
    start_first_floor(game)
    game.active_run.map = make_linear_run_map(node_types)
    game.active_run.current_node_id = None
    drain(game)
    return game.active_run


def test_a_fresh_game_shows_nothing_and_has_the_hint_path_pinned(game, tmp_path):
    assert game.hints.current is None
    assert str(game.hints_path).startswith(str(tmp_path))


def test_first_fight_start_hint(game):
    practice(game)
    assert_fires_once(game, "first_fight", lambda: practice(game))


def test_the_level_loaded_behind_the_menu_spends_no_hint(game):
    game.update(1.0)
    assert game.state == GameState.MENU
    assert game.hints.current is None and game.hints.seen == set()


@pytest.mark.parametrize("node_type", ["shop", "event", "rest", "treasure", "armory", "elite", "boss"])
def test_first_visit_to_each_node_type(game, node_type):
    linear_run(game, [node_type, node_type])
    game._enter_node("0-0")
    key = f"node_{node_type}"
    assert key in queued(game)
    assert_fires_once(game, key, lambda: game._enter_node("1-0"))


def test_reward_screen_hint(game):
    linear_run(game, ["combat", "combat", "combat"])
    game._enter_node("0-0")
    finish_all_waves(game)
    game.update(0.01)
    game._enter_reward_screen()
    assert game.state == GameState.REWARD
    assert_fires_once(game, "reward", game._enter_reward_screen)


def test_holding_a_potion_or_module_at_fight_start(game):
    run = linear_run(game, ["combat", "combat"])
    run.potions[:] = [next(iter(potions.POTIONS))]
    run.tower_modules["basic"] = next(iter(modules.MODULES))
    game._enter_node("0-0")
    game.update(0.0)
    assert {"potion", "module"} <= set(queued(game))
    assert_fires_once(game, "potion", lambda: (game._enter_node("1-0"), game.update(0.0)))


def test_tower_built_and_barricade_and_harpoon_hints(game):
    start_first_floor(game)
    drain(game)
    place(game)
    assert "coverage" in queued(game)
    assert_fires_once(game, "coverage", lambda: place(game))
    game.selected_tower_name = "barricade"
    game.active_run.unlocked_towers.append("barricade")
    assert game.try_place_tower(*path_anchor(game, TOWER_TYPES["barricade"]))
    assert "barricade" in queued(game)
    place(game, "harpoon")
    assert "harpoon" in queued(game)


def test_specialize_ready_hint_when_a_tower_maxes(game):
    start_first_floor(game)
    tower = place(game)
    drain(game)
    while not tower.is_max_level:
        game.try_upgrade_tower(tower)
    assert_fires_once(game, "specialize", lambda: [game.try_upgrade_tower(place(game)) for _ in range(5)])


def test_resonance_hint(game):
    start_first_floor(game)
    game._announced_resonances = set()
    lightning = place(game, "lightning")
    lightning.resonance_keys = ["superconductor"]
    lightning.set_nearby_tower_bonus = lambda towers: None  # keep the forced key
    game._recompute_tower_density_bonuses()
    assert "resonance" in queued(game)
    game._announced_resonances = set()
    assert_fires_once(game, "resonance", game._recompute_tower_density_bonuses)


@pytest.mark.parametrize("enemy", ["burrower", "flying", "shielded", "sapper"])
def test_first_enemy_of_a_type_spawning(game, enemy):
    start_first_floor(game)
    drain(game)
    spawn_cell = game.wave_manager.level.spawn_cells[0]

    def spawn():
        game.wave_manager.update = lambda dt, active: [
            game.wave_manager._spawn_enemy(spawn_cell, ENEMY_TYPES[enemy])]
        game.update(0.01)

    spawn()
    assert_fires_once(game, f"enemy_{enemy}", spawn)


def test_wave_cleared_queues_early_call_then_move_towers(game):
    start_first_floor(game)
    game.update(0.0)  # the fight-start hints
    drain(game)

    def clear_a_wave(dt, active):
        game.wave_manager.wave_index += 1  # what WaveManager does when a wave clears
        return []

    game.wave_manager.update = clear_a_wave
    game.update(0.01)
    assert queued(game) == ["early_call", "move_towers"]


def test_low_lives_hint_fires_at_five_but_not_on_death(game):
    start_first_floor(game)
    drain(game)
    game.economy.lives = 1
    game._lose_a_life()
    assert "low_lives" not in queued(game)
    game.economy.lives = 6
    game._lose_a_life()
    assert_fires_once(game, "low_lives", game._lose_a_life)


def test_run_lost_hint_on_game_over(game):
    start_first_floor(game)
    drain(game)
    game.economy.lives = 0
    game.update(0.01)
    assert game.state == GameState.GAME_OVER
    assert "run_lost" in queued(game)


def test_act_cleared_hint_on_an_earlier_acts_boss(game):
    from run.run_state import RunState

    start_first_floor(game)
    drain(game)
    run = game.active_run
    run.map = make_linear_run_map(["combat", "boss"])
    run.current_node_id = "1-0"
    # Not the last act, so the boss is a finite fight that clears.
    assert isinstance(run, RunState)
    game._advance_run_floor()
    assert "act_cleared" in queued(game)


def test_veterancy_hint_on_a_promotion(game):
    start_first_floor(game)
    tower = place(game)
    drain(game)
    tower.kills = veterancy.RANKS[0].xp_required
    finish_all_waves(game)
    game.update(0.01)
    assert "veterancy" in queued(game)


def test_relic_and_curse_hints(game):
    start_first_floor(game)
    drain(game)
    game._grant_relic("prospectors_charm")
    assert queued(game) == ["relic"]
    game._grant_relic("rusted_gears")
    assert queued(game) == ["relic", "curse"]


def test_blessing_and_gauntlet_hints(game):
    game.start_new_run(seed=1)
    game._enter_blessing()
    assert "blessing" in queued(game)
    game.highest_ascension = 0
    game.active_run.ascension = 0
    game._unlock_next_ascension()
    assert "gauntlet" in queued(game)


# --- Settings: toggle and reset ---


def test_toggle_off_suppresses_and_persists(tmp_path):
    game = make_game(tmp_path)
    try:
        game.set_hints_enabled(False)
        practice(game)
        assert game.hints.current is None
    finally:
        quit_pygame_keeping_the_mixer()
    reloaded = make_game(tmp_path)
    try:
        assert reloaded.hints.enabled is False
        reloaded.set_hints_enabled(True)
        practice(reloaded)
        assert reloaded.hints.current == "first_fight"
    finally:
        quit_pygame_keeping_the_mixer()


def test_reset_hints_shows_them_again(game):
    practice(game)
    drain(game)
    game.reset_hints()
    assert hints.load_seen(game.hints_path) == set()
    practice(game)
    assert game.hints.current == "first_fight"


def test_corrupt_hints_file_falls_back_to_showing_hints(tmp_path):
    (tmp_path / "hints.json").write_text("{definitely not json")
    game = make_game(tmp_path)
    try:
        assert game.hints.seen == set()
        practice(game)
        assert game.hints.current == "first_fight"
    finally:
        quit_pygame_keeping_the_mixer()


def test_settings_screen_hint_buttons(game):
    game.state = GameState.SETTINGS
    game._handle_settings_click(game.hint_settings_rects["hints"].center)
    assert game.hints.enabled is False
    game._handle_settings_click(game.hint_settings_rects["hints"].center)
    assert game.hints.enabled is True
    game.hints.seen.add("relic")
    game._handle_settings_click(game.hint_settings_rects["reset_hints"].center)
    assert game.hints.seen == set()
    game.render()  # draws both buttons


def test_hint_buttons_stay_on_screen_and_clear_the_settings_column():
    rects = ui.build_hint_settings_rects()
    column = ui.build_settings_rects()
    for rect in rects.values():
        assert rect.left >= 0
        assert not any(rect.colliderect(other) for other in column.values())


# --- Display: one at a time, dismiss, timeout, per-state drawing ---


def test_queueing_never_shows_two_at_once(game):
    linear_run(game, ["shop", "event", "rest"])
    game._enter_node("0-0")
    game.hints.notify("node_event", "node_rest", "relic")
    seen_current = []
    while game.hints.current is not None:
        seen_current.append(game.hints.current)
        assert game.hints.current not in game.hints.pending
        game.update(hints.HINT_DISPLAY_SECONDS)
    assert seen_current == ["node_shop", "node_event", "node_rest", "relic"]


def test_hints_hold_while_paused_or_off_the_run(game):
    practice(game)
    game.state = GameState.PAUSED
    game.update(hints.HINT_DISPLAY_SECONDS * 2)
    assert game.hints.current == "first_fight"
    assert game._hint_panel_rect() is None  # not drawn while paused
    game.state = GameState.PLAYING
    game.update(hints.HINT_DISPLAY_SECONDS)
    assert game.hints.current is None


def test_clicking_the_panel_dismisses_without_passing_the_click_through(game):
    linear_run(game, ["treasure", "combat"])
    game._enter_node("0-0")
    assert game.state == GameState.TREASURE and game.hints.current == "node_treasure"
    rect = game._hint_panel_rect()
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
    game.handle_events()
    assert game.hints.current == "relic"  # the Treasure's own relic, queued next
    assert game.state == GameState.TREASURE  # a click on a Treasure screen would otherwise continue
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(5, 5)))
    game.handle_events()
    assert game.state == GameState.MAP


@pytest.mark.parametrize("state, placement", [
    (GameState.PLAYING, "board"), (GameState.GAME_OVER, "board"), (GameState.MAP, "map"),
    (GameState.DRAFT, "screen"), (GameState.REST, "screen"), (GameState.TREASURE, "screen"),
])
def test_panel_draws_in_its_corner_for_every_state(game, state, placement):
    start_first_floor(game)
    game._enter_map()
    game.state = state
    for key in hints.HINTS:
        game.hints.current = key
        rect = game._hint_panel_rect()
        assert game._hint_placement() == placement
        assert game.screen.get_rect().contains(rect), key
        if placement == "board":
            assert rect.right <= ui.settings.PLAY_WIDTH
            assert rect.bottom <= ui.settings.SCREEN_HEIGHT - ui.settings.HUD_HEIGHT
    if state == GameState.MAP:
        for node_rect in game.map_node_rects.values():
            assert not rect.colliderect(node_rect)
    game.render()
