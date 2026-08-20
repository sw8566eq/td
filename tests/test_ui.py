import pygame

import settings
from editor import TOOL_ORDER
from enemy import ENEMY_TYPES
from tower import TOWER_TYPES
from ui import (
    EDITOR_ACTION_ORDER,
    PANEL_PADDING,
    WAVE_EDITOR_ACTION_ORDER,
    build_button_rects,
    build_editor_action_rects,
    build_editor_tool_rects,
    build_level_select_rects,
    build_sell_button_rect,
    build_skip_button_rect,
    build_specialize_button_rects,
    build_upgrade_button_rect,
    build_wave_editor_action_rects,
    build_wave_tab_rects,
    build_wave_unit_rects,
    get_clicked_editor_action,
    get_clicked_editor_tool,
    get_clicked_level_select_entry,
    get_clicked_tower_button,
    get_clicked_wave_editor_action,
    get_clicked_wave_tab,
    get_clicked_wave_unit_button,
)


def test_build_button_rects_has_one_entry_per_registered_tower():
    from tower import TOWER_TYPES

    rects = build_button_rects()
    assert set(rects.keys()) == set(TOWER_TYPES.keys())


def test_get_clicked_tower_button_returns_matching_name():
    rects = {"basic": pygame.Rect(0, 0, 50, 50), "cannon": pygame.Rect(60, 0, 50, 50)}
    assert get_clicked_tower_button((10, 10), rects) == "basic"
    assert get_clicked_tower_button((70, 10), rects) == "cannon"


def test_get_clicked_tower_button_returns_none_outside_all_buttons():
    rects = {"basic": pygame.Rect(0, 0, 50, 50)}
    assert get_clicked_tower_button((1000, 1000), rects) is None


def test_skip_button_sits_within_the_hud_and_the_play_area():
    rect = build_skip_button_rect()
    hud_top = settings.SCREEN_HEIGHT - settings.HUD_HEIGHT
    assert rect.top >= hud_top
    assert rect.bottom <= settings.SCREEN_HEIGHT
    assert rect.left >= 0
    # Anchored to PLAY_WIDTH, not the wider (panel-including) SCREEN_WIDTH,
    # so it stays under the grid rather than drifting under the stats panel.
    assert rect.right <= settings.PLAY_WIDTH


def test_skip_button_does_not_overlap_the_tower_build_buttons():
    skip_rect = build_skip_button_rect()
    for name, tower_rect in build_button_rects().items():
        assert not skip_rect.colliderect(tower_rect), name


def test_upgrade_and_sell_buttons_sit_within_the_stats_panel():
    for rect in (build_upgrade_button_rect(), build_sell_button_rect()):
        assert rect.left >= settings.PLAY_WIDTH
        assert rect.right <= settings.SCREEN_WIDTH
        assert rect.top >= 0
        assert rect.bottom <= settings.SCREEN_HEIGHT


def test_upgrade_button_sits_above_the_sell_button_without_overlapping():
    upgrade_rect = build_upgrade_button_rect()
    sell_rect = build_sell_button_rect()
    assert not upgrade_rect.colliderect(sell_rect)
    assert upgrade_rect.bottom <= sell_rect.top


def test_specialize_buttons_sit_within_the_stats_panel():
    for rect in build_specialize_button_rects():
        assert rect.left >= settings.PLAY_WIDTH
        assert rect.right <= settings.SCREEN_WIDTH
        assert rect.top >= 0
        assert rect.bottom <= settings.SCREEN_HEIGHT


def test_specialize_buttons_are_stacked_above_the_sell_button_without_overlapping():
    first, second = build_specialize_button_rects()
    sell_rect = build_sell_button_rect()

    assert not first.colliderect(second)
    assert first.bottom <= second.top

    for rect in (first, second):
        assert not rect.colliderect(sell_rect)
        assert rect.bottom <= sell_rect.top


def test_first_specialize_button_shares_the_upgrade_buttons_slot():
    # Intentional, not a layout bug: Upgrade (below MAX_LEVEL) and
    # Specialize (at MAX_LEVEL) are mutually exclusive states, so they
    # share the same top slot in the panel. Game._handle_click resolves a
    # click on this shared rect by the subject's actual state (upgradeable
    # vs. specializable) rather than by which check runs first -- see the
    # click-handling tests in test_game.py, including a regression test
    # for the bug that shape used to cause ("Power" looked dead), and the
    # ones that use the *second* specialize rect where that ambiguity
    # doesn't apply.
    assert build_specialize_button_rects()[0] == build_upgrade_button_rect()


# --- Map editor toolbar/actions ---

def test_build_editor_tool_rects_has_one_entry_per_editor_tool():
    rects = build_editor_tool_rects()
    assert set(rects.keys()) == set(TOOL_ORDER)


def test_get_clicked_editor_tool_returns_matching_name():
    rects = build_editor_tool_rects()
    for name, rect in rects.items():
        assert get_clicked_editor_tool(rect.center, rects) == name
    assert get_clicked_editor_tool((-1000, -1000), rects) is None


def test_editor_tool_buttons_do_not_overlap():
    rects = list(build_editor_tool_rects().values())
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b)


def test_build_editor_action_rects_has_one_entry_per_action_and_sits_in_the_sidebar():
    rects = build_editor_action_rects()
    assert set(rects.keys()) == set(EDITOR_ACTION_ORDER)
    for rect in rects.values():
        assert rect.left >= settings.PLAY_WIDTH
        assert rect.right <= settings.SCREEN_WIDTH
        assert rect.top >= 0
        assert rect.bottom <= settings.SCREEN_HEIGHT


def test_editor_action_buttons_are_stacked_without_overlapping():
    rects = list(build_editor_action_rects().values())
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b)


def test_get_clicked_editor_action_returns_matching_name():
    rects = build_editor_action_rects()
    for name, rect in rects.items():
        assert get_clicked_editor_action(rect.center, rects) == name
    assert get_clicked_editor_action((-1000, -1000), rects) is None


# --- Level select ---

def test_build_level_select_rects_has_one_entry_per_entry_and_they_dont_overlap():
    entries = [(1, "Winding Road"), (2, "Serpentine Pass"), ("custom-slug", "My Level (custom)")]
    rects = build_level_select_rects(entries)
    assert set(rects.keys()) == {1, 2, "custom-slug"}

    ordered = list(rects.values())
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            assert not a.colliderect(b)


def test_get_clicked_level_select_entry_returns_matching_key():
    entries = [(1, "Winding Road"), ("custom-slug", "My Level (custom)")]
    rects = build_level_select_rects(entries)
    for key, rect in rects.items():
        assert get_clicked_level_select_entry(rect.center, rects) == key
    assert get_clicked_level_select_entry((-1000, -1000), rects) is None


def test_build_level_select_rects_handles_an_empty_entry_list():
    assert build_level_select_rects([]) == {}


# --- Wave editor ---

def test_build_wave_tab_rects_has_one_tab_per_wave_plus_add_and_remove():
    rects = build_wave_tab_rects(3)
    assert set(rects.keys()) == {0, 1, 2, "add", "remove"}


def test_build_wave_tab_rects_handles_zero_waves():
    rects = build_wave_tab_rects(0)
    assert set(rects.keys()) == {"add", "remove"}


def test_wave_tabs_do_not_overlap():
    rects = list(build_wave_tab_rects(4).values())
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b)


def test_get_clicked_wave_tab_returns_matching_key():
    rects = build_wave_tab_rects(2)
    for key, rect in rects.items():
        assert get_clicked_wave_tab(rect.center, rects) == key
    assert get_clicked_wave_tab((-1000, -1000), rects) is None


def test_build_wave_unit_rects_has_a_minus_and_plus_per_enemy_type():
    rects = build_wave_unit_rects()
    expected_keys = {(name, suffix) for name in ENEMY_TYPES for suffix in ("minus", "plus")}
    assert set(rects.keys()) == expected_keys


def test_wave_unit_rects_sit_within_the_sidebar_and_do_not_overlap():
    rects = list(build_wave_unit_rects().values())
    for rect in rects:
        assert rect.left >= settings.PLAY_WIDTH
        assert rect.right <= settings.SCREEN_WIDTH
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b)


def test_get_clicked_wave_unit_button_returns_matching_key():
    rects = build_wave_unit_rects()
    for key, rect in rects.items():
        assert get_clicked_wave_unit_button(rect.center, rects) == key
    assert get_clicked_wave_unit_button((-1000, -1000), rects) is None


def test_build_wave_editor_action_rects_has_one_entry_per_action_and_sits_in_the_sidebar():
    rects = build_wave_editor_action_rects()
    assert set(rects.keys()) == set(WAVE_EDITOR_ACTION_ORDER)
    for rect in rects.values():
        assert rect.left >= settings.PLAY_WIDTH
        assert rect.right <= settings.SCREEN_WIDTH
        assert rect.top >= 0
        assert rect.bottom <= settings.SCREEN_HEIGHT


def test_wave_editor_action_buttons_are_stacked_without_overlapping():
    rects = list(build_wave_editor_action_rects().values())
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b)


def test_get_clicked_wave_editor_action_returns_matching_name():
    rects = build_wave_editor_action_rects()
    for name, rect in rects.items():
        assert get_clicked_wave_editor_action(rect.center, rects) == name
    assert get_clicked_wave_editor_action((-1000, -1000), rects) is None


def test_wave_unit_rects_do_not_overlap_the_wave_editor_action_rects():
    unit_rects = list(build_wave_unit_rects().values())
    action_rects = list(build_wave_editor_action_rects().values())
    for unit_rect in unit_rects:
        for action_rect in action_rects:
            assert not unit_rect.colliderect(action_rect)


def test_specialization_descriptions_fit_the_panel_width():
    # draw_tower_stats_panel shows a hovered specialize option's
    # description on one line at this same font/width -- catches a
    # description that's been edited long enough to overflow, silently
    # spilling into (or past) the panel's edge rather than erroring.
    pygame.font.init()
    small_font = pygame.font.SysFont(None, 22)  # matches Game.small_font
    usable_width = settings.PANEL_WIDTH - 2 * PANEL_PADDING
    for name, tower_cls in TOWER_TYPES.items():
        for key, spec in tower_cls.SPECIALIZATIONS.items():
            width = small_font.size(spec["description"])[0]
            assert width <= usable_width, (
                f"{name}/{key}: {spec['description']!r} is {width}px, panel fits {usable_width}px"
            )
