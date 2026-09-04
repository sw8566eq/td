import pygame

import settings
from editor import TOOL_ORDER
from enemy import ENEMY_TYPES
from levels import Level
from tower import TOWER_TYPES
from ui import (
    ACHIEVEMENTS_TOP,
    ACHIEVEMENT_ROW_HEIGHT,
    EDITOR_ACTION_ORDER,
    HELP_LINE_HEIGHT,
    HELP_LINES,
    HELP_TOP,
    HUD_TOP_STRIP_HEIGHT,
    LEVEL_SELECT_BOTTOM,
    LEVEL_SELECT_ROW_GAP,
    LEVEL_SELECT_ROW_HEIGHT,
    LEVEL_SELECT_TOP,
    LEVEL_THUMBNAIL_HEIGHT,
    LEVEL_THUMBNAIL_WIDTH,
    PANEL_PADDING,
    WAVE_EDITOR_ACTION_ORDER,
    WAVE_UNIT_ROWS_BOTTOM,
    WAVE_UNIT_ROWS_TOP,
    WAVE_UNIT_ROW_HEIGHT,
    _draw_centered_overlay,
    _wrap_text,
    build_achievements_back_rect,
    build_button_rects,
    build_draft_choice_rects,
    build_help_back_rect,
    build_editor_action_rects,
    build_editor_tool_rects,
    build_level_select_rects,
    build_level_thumbnail,
    build_sell_button_rect,
    build_settings_rects,
    build_skip_button_rect,
    build_speed_button_rect,
    build_specialize_button_rects,
    build_targeting_button_rect,
    build_upgrade_button_rect,
    build_wave_editor_action_rects,
    build_wave_tab_rects,
    build_wave_unit_rects,
    compute_tower_results,
    draw_achievements_screen,
    draw_draft_screen,
    draw_floor_cleared_screen,
    draw_game_over_screen,
    draw_help_screen,
    draw_level_select_screen,
    draw_results_table,
    draw_victory_screen,
    get_clicked_draft_choice,
    get_clicked_editor_action,
    get_clicked_editor_tool,
    get_clicked_level_select_entry,
    get_clicked_settings_option,
    get_clicked_tower_button,
    get_clicked_wave_editor_action,
    get_clicked_wave_tab,
    get_clicked_wave_unit_button,
    level_select_content_height,
    level_select_max_scroll,
    menu_options,
    wave_unit_content_height,
    wave_unit_max_scroll,
    _format_wave_label,
    _format_wave_preview,
)


# --- Main menu ---
#
# menu_options() is the pure, directly-testable half of draw_menu_screen
# (same split as compute_tower_results()/draw_results_table() below --
# draw_menu_screen itself only gets a "does not crash" smoke test in
# test_game.py, since reading rendered text back out of pixels isn't done
# anywhere in this suite). It exists because it used to be an options list
# inlined straight into draw_menu_screen with nothing pinning its contents
# down at all -- which is exactly how "L -- Level Browser" went missing
# from the title screen for a while despite the L key always having
# worked; see test_game.py's test_every_special_cased_menu_key_has_an_on_
# screen_hint for the complementary check that ties this list back to what
# Game._handle_keydown's GameState.MENU branch actually does.

def test_menu_options_lists_every_key_in_documented_order():
    assert menu_options(has_saved_run=False) == [
        "Press any key to start a run",
        "E -- Map Editor",
        "L -- Level Browser",
        "S -- Settings",
        "A -- Achievements",
        "H -- How to Play",
        "D -- Daily Challenge",
    ]


def test_menu_options_adds_continue_only_with_a_saved_run():
    without = menu_options(has_saved_run=False)
    assert "C -- Continue" not in without
    assert menu_options(has_saved_run=True) == without + ["C -- Continue"]


def test_build_button_rects_has_one_entry_per_registered_tower():
    from tower import TOWER_TYPES

    rects = build_button_rects()
    assert set(rects.keys()) == set(TOWER_TYPES.keys())


def test_build_button_rects_respects_a_custom_tower_names_list():
    # A roguelike run's own restricted pool (see Game._active_tower_names) --
    # the whole point of the tower_names param.
    rects = build_button_rects(tower_names=("basic", "cannon"))
    assert set(rects.keys()) == {"basic", "cannon"}


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


def test_speed_button_sits_within_the_hud_top_strip():
    rect = build_speed_button_rect()
    hud_top = settings.SCREEN_HEIGHT - settings.HUD_HEIGHT
    assert rect.top >= hud_top
    assert rect.bottom <= hud_top + HUD_TOP_STRIP_HEIGHT
    assert rect.right <= settings.PLAY_WIDTH


def test_speed_button_does_not_overlap_the_skip_button_or_tower_buttons():
    speed_rect = build_speed_button_rect()
    assert not speed_rect.colliderect(build_skip_button_rect())
    for name, tower_rect in build_button_rects().items():
        assert not speed_rect.colliderect(tower_rect), name


def test_settings_rects_has_one_entry_per_option():
    from ui import SETTINGS_OPTION_ORDER

    rects = build_settings_rects()
    assert set(rects.keys()) == set(SETTINGS_OPTION_ORDER)


def test_settings_rects_do_not_overlap():
    rects = list(build_settings_rects().values())
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b)


def test_get_clicked_settings_option_returns_matching_key():
    rects = build_settings_rects()
    assert get_clicked_settings_option(rects["fullscreen"].center, rects) == "fullscreen"
    assert get_clicked_settings_option(rects["hard"].center, rects) == "hard"


def test_get_clicked_settings_option_returns_none_outside_all_buttons():
    rects = build_settings_rects()
    assert get_clicked_settings_option((0, 0), rects) is None


# --- Achievements screen ---

def test_build_achievements_back_rect_sits_below_the_last_achievement_row():
    from achievements import ACHIEVEMENT_ORDER
    rect = build_achievements_back_rect()
    last_row_bottom = ACHIEVEMENTS_TOP + len(ACHIEVEMENT_ORDER) * ACHIEVEMENT_ROW_HEIGHT
    assert rect.top >= last_row_bottom


def test_draw_achievements_screen_does_not_crash_with_nothing_unlocked():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    back_rect = build_achievements_back_rect()

    draw_achievements_screen(surface, font, small_font, unlocked_keys=set(), counters={}, back_rect=back_rect)


def test_draw_achievements_screen_shows_unlocked_and_in_progress_entries():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    back_rect = build_achievements_back_rect()

    # Exercises both branches (unlocked vs. still-locked-with-progress)
    # without needing to read pixels back.
    draw_achievements_screen(
        surface, font, small_font,
        unlocked_keys={"first_blood"}, counters={"kills": 1, "towers_built": 0},
        back_rect=back_rect,
    )


# --- Help / How to Play screen ---

def test_build_help_back_rect_sits_below_the_last_help_line():
    rect = build_help_back_rect()
    last_line_bottom = HELP_TOP + len(HELP_LINES) * HELP_LINE_HEIGHT
    assert rect.top >= last_line_bottom


def test_draw_help_screen_does_not_crash():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    back_rect = build_help_back_rect()

    draw_help_screen(surface, font, small_font, back_rect)


class _FakeWaveManager:
    def __init__(self, all_waves_complete=False, endless=False, current_wave_number=1, total_waves=1):
        self.all_waves_complete = all_waves_complete
        self.endless = endless
        self.current_wave_number = current_wave_number
        self.total_waves = total_waves


def test_format_wave_label_shows_x_of_n_normally():
    assert _format_wave_label(_FakeWaveManager(current_wave_number=2, total_waves=5)) == "Wave 2/5"


def test_format_wave_label_shows_all_cleared_once_complete():
    assert _format_wave_label(_FakeWaveManager(all_waves_complete=True)) == "All waves cleared!"


def test_format_wave_label_shows_endless_with_no_denominator():
    label = _format_wave_label(_FakeWaveManager(endless=True, current_wave_number=12, total_waves=99))
    assert label == "Wave 12 (Endless)"
    assert "/" not in label


def test_format_wave_label_prefers_all_cleared_over_endless():
    # all_waves_complete is checked first -- defensive ordering only
    # (endless mode never actually sets all_waves_complete=True in
    # practice, see WaveManager._advance_after_clear).
    label = _format_wave_label(_FakeWaveManager(all_waves_complete=True, endless=True))
    assert label == "All waves cleared!"


# --- Post-level results (per-tower damage/kills/accuracy) ---

class _FakeTowerResult:
    def __init__(self, display_name, shots_fired, shots_hit, damage_dealt, kills):
        self.display_name = display_name
        self.shots_fired = shots_fired
        self.shots_hit = shots_hit
        self.damage_dealt = damage_dealt
        self.kills = kills


def test_compute_tower_results_sorts_by_damage_dealt_descending():
    low = _FakeTowerResult("Basic", shots_fired=5, shots_hit=5, damage_dealt=50, kills=1)
    high = _FakeTowerResult("Cannon", shots_fired=3, shots_hit=3, damage_dealt=200, kills=4)

    results = compute_tower_results([low, high])

    assert [row["display_name"] for row in results] == ["Cannon", "Basic"]


def test_compute_tower_results_reports_none_accuracy_for_a_tower_that_never_fired():
    never_fired = _FakeTowerResult("Support", shots_fired=0, shots_hit=0, damage_dealt=0, kills=0)
    results = compute_tower_results([never_fired])
    assert results[0]["accuracy"] is None


def test_compute_tower_results_computes_accuracy_as_a_fraction():
    tower = _FakeTowerResult("Basic", shots_fired=4, shots_hit=3, damage_dealt=30, kills=1)
    results = compute_tower_results([tower])
    assert results[0]["accuracy"] == 0.75


def test_compute_tower_results_on_an_empty_list_is_an_empty_list():
    assert compute_tower_results([]) == []


def test_draw_results_table_with_no_results_does_not_raise():
    pygame.font.init()
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    draw_results_table(surface, small_font, None, top_y=100)
    draw_results_table(surface, small_font, [], top_y=100)


def test_draw_results_table_with_results_does_not_raise():
    pygame.font.init()
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    results = compute_tower_results([
        _FakeTowerResult("Basic", shots_fired=4, shots_hit=3, damage_dealt=30, kills=1),
        _FakeTowerResult("Support", shots_fired=0, shots_hit=0, damage_dealt=0, kills=0),
    ])
    draw_results_table(surface, small_font, results, top_y=100)


def test_draw_results_table_collapses_extra_rows_into_a_more_line():
    from ui import RESULTS_MAX_ROWS

    pygame.font.init()
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    results = compute_tower_results([
        _FakeTowerResult(f"Tower {i}", shots_fired=1, shots_hit=1, damage_dealt=float(i), kills=0)
        for i in range(RESULTS_MAX_ROWS + 3)
    ])
    draw_results_table(surface, small_font, results, top_y=100)  # must not raise


def test_draw_victory_screen_with_results_does_not_raise():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    results = compute_tower_results([_FakeTowerResult("Basic", 4, 3, 30, 1)])
    draw_victory_screen(surface, font, small_font, has_next_level=True, results=results)


def test_draw_game_over_screen_with_results_does_not_raise():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    results = compute_tower_results([_FakeTowerResult("Basic", 4, 3, 30, 1)])
    draw_game_over_screen(surface, font, small_font, results=results)


def test_draw_floor_cleared_screen_with_results_does_not_raise():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    results = compute_tower_results([_FakeTowerResult("Basic", 4, 3, 30, 1)])
    draw_floor_cleared_screen(surface, font, small_font, 2, 6, results=results)


# --- Draft screen ---

def test_build_draft_choice_rects_returns_one_rect_per_choice():
    rects = build_draft_choice_rects(3)
    assert len(rects) == 3


def test_build_draft_choice_rects_is_empty_for_zero_choices():
    assert build_draft_choice_rects(0) == []


def test_build_draft_choice_rects_does_not_overlap():
    rects = build_draft_choice_rects(3)
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b)


def test_get_clicked_draft_choice_returns_matching_index():
    rects = build_draft_choice_rects(3)
    assert get_clicked_draft_choice(rects[1].center, rects) == 1


def test_get_clicked_draft_choice_returns_none_outside_all_cards():
    rects = build_draft_choice_rects(3)
    assert get_clicked_draft_choice((0, 0), rects) is None


def test_draw_draft_screen_does_not_raise():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    choices = ["basic", "cannon", "support"]  # support exercises the IS_SUPPORT branch too
    rects = build_draft_choice_rects(len(choices))
    draw_draft_screen(surface, font, small_font, choices, rects, "tower", hovered_index=1)


def test_draw_draft_screen_with_relics_does_not_raise():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    from relics import RELICS
    choices = list(RELICS.keys())[:2]
    rects = build_draft_choice_rects(len(choices))
    draw_draft_screen(surface, font, small_font, choices, rects, "relic", hovered_index=0)


def test_format_wave_preview_orders_by_registry_order_not_dict_order():
    from ui import ENEMY_ORDER

    # Deliberately built out of ENEMY_ORDER's order to prove the formatter
    # re-sorts rather than trusting dict iteration order.
    reversed_order = list(reversed(ENEMY_ORDER))
    composition = {name: index + 1 for index, name in enumerate(reversed_order)}

    text = _format_wave_preview(composition)

    positions = [text.index(f"{name.capitalize()} x") for name in ENEMY_ORDER]
    assert positions == sorted(positions)


def test_format_wave_preview_only_mentions_species_actually_present():
    composition = {"grunt": 8}
    text = _format_wave_preview(composition)
    assert text == "Next: Grunt x8"


def test_targeting_button_sits_within_the_stats_panel():
    rect = build_targeting_button_rect()
    assert rect.left >= settings.PLAY_WIDTH
    assert rect.right <= settings.SCREEN_WIDTH
    assert rect.top >= 0
    assert rect.bottom <= settings.SCREEN_HEIGHT


def test_targeting_button_sits_above_the_upgrade_button_without_overlapping():
    targeting_rect = build_targeting_button_rect()
    upgrade_rect = build_upgrade_button_rect()
    assert not targeting_rect.colliderect(upgrade_rect)
    assert targeting_rect.bottom <= upgrade_rect.top


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


def test_draw_level_select_screen_handles_a_missing_thumbnail():
    # Game._enter_level_select() always builds one thumbnail per entry, so
    # this only ever happens defensively -- a caller passing a thumbnails
    # dict that doesn't have every listed entry's key must not crash, just
    # skip the thumbnail and still render the row's label.
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))

    class FakeLevel:
        name = "No Thumbnail Level"

    entries = [(1, FakeLevel())]
    rects = build_level_select_rects(entries)

    draw_level_select_screen(surface, font, small_font, entries, rects, thumbnails={})


def test_draw_level_select_screen_shows_the_survival_hint_only_for_purpose_play():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    entries = []
    rects = {}

    # None of these should raise, with the hint shown (armed and not) or
    # hidden (purpose="edit") -- exercises every branch of the new
    # endless_armed handling without needing to read back pixels.
    draw_level_select_screen(surface, font, small_font, entries, rects, thumbnails={},
                              purpose="play", endless_armed=False)
    draw_level_select_screen(surface, font, small_font, entries, rects, thumbnails={},
                              purpose="play", endless_armed=True)
    draw_level_select_screen(surface, font, small_font, entries, rects, thumbnails={},
                              purpose="edit", endless_armed=True)


def test_draw_level_select_screen_shows_the_sandbox_hint_only_for_purpose_play():
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
    entries = []
    rects = {}

    # Same idea as the Survival hint above, for the independent Sandbox
    # toggle -- exercises every branch of the new sandbox_armed handling.
    draw_level_select_screen(surface, font, small_font, entries, rects, thumbnails={},
                              purpose="play", sandbox_armed=False)
    draw_level_select_screen(surface, font, small_font, entries, rects, thumbnails={},
                              purpose="play", sandbox_armed=True)
    draw_level_select_screen(surface, font, small_font, entries, rects, thumbnails={},
                              purpose="edit", sandbox_armed=True)


# --- Level select scrolling ---

def test_level_select_content_height_is_zero_for_no_entries():
    assert level_select_content_height(0) == 0


def test_level_select_content_height_has_no_trailing_gap():
    one_row = level_select_content_height(1)
    two_rows = level_select_content_height(2)
    assert one_row == LEVEL_SELECT_ROW_HEIGHT
    assert two_rows == 2 * LEVEL_SELECT_ROW_HEIGHT + LEVEL_SELECT_ROW_GAP


def test_level_select_max_scroll_is_zero_when_everything_fits():
    assert level_select_max_scroll(0) == 0
    assert level_select_max_scroll(1) == 0


def test_level_select_max_scroll_is_positive_once_content_overflows_the_viewport():
    # However many rows it takes to definitely overflow the visible area.
    viewport_height = LEVEL_SELECT_BOTTOM - LEVEL_SELECT_TOP
    row_span = LEVEL_SELECT_ROW_HEIGHT + LEVEL_SELECT_ROW_GAP
    overflowing_count = viewport_height // row_span + 5
    max_scroll = level_select_max_scroll(overflowing_count)
    assert max_scroll > 0
    assert max_scroll == level_select_content_height(overflowing_count) - viewport_height


def test_build_level_select_rects_shifts_rows_up_by_the_scroll_offset():
    entries = [(1, "a"), (2, "b")]
    unscrolled = build_level_select_rects(entries, scroll_offset=0)
    scrolled = build_level_select_rects(entries, scroll_offset=50)
    for key in (1, 2):
        assert scrolled[key].y == unscrolled[key].y - 50
        assert scrolled[key].x == unscrolled[key].x  # only y moves


def _make_thumbnail_test_level():
    return Level(
        id=1, name="Test",
        path_cells=frozenset({(0, 0), (1, 0)}),
        spawn_cells=((0, 0),), goal_cells=((1, 0),),
        wave_specs=[{(0, 0): {"grunt": 1}}],
    )


def test_build_level_thumbnail_has_the_requested_default_size():
    thumbnail = build_level_thumbnail(_make_thumbnail_test_level())
    assert thumbnail.get_size() == (LEVEL_THUMBNAIL_WIDTH, LEVEL_THUMBNAIL_HEIGHT)


def test_build_level_thumbnail_respects_a_custom_size():
    thumbnail = build_level_thumbnail(_make_thumbnail_test_level(), width=60, height=36)
    assert thumbnail.get_size() == (60, 36)


def test_build_level_thumbnail_colors_path_cells_and_leaves_the_rest_as_ground():
    thumbnail = build_level_thumbnail(_make_thumbnail_test_level())
    cell_h = LEVEL_THUMBNAIL_HEIGHT / settings.GRID_ROWS

    # A pixel inside path cell (0, 0), away from its own center dot.
    path_pixel = thumbnail.get_at((1, int(cell_h) - 1))
    assert (path_pixel.r, path_pixel.g, path_pixel.b) == settings.COLOR_THUMBNAIL_PATH

    # A pixel well outside any path cell.
    ground_pixel = thumbnail.get_at((LEVEL_THUMBNAIL_WIDTH - 2, LEVEL_THUMBNAIL_HEIGHT - 2))
    assert (ground_pixel.r, ground_pixel.g, ground_pixel.b) == settings.COLOR_THUMBNAIL_GROUND


def test_build_level_thumbnail_marks_spawn_and_goal_with_distinct_colors():
    thumbnail = build_level_thumbnail(_make_thumbnail_test_level())
    cell_w = LEVEL_THUMBNAIL_WIDTH / settings.GRID_COLS
    cell_h = LEVEL_THUMBNAIL_HEIGHT / settings.GRID_ROWS

    spawn_center = thumbnail.get_at((int(cell_w * 0.5), int(cell_h * 0.5)))
    assert (spawn_center.r, spawn_center.g, spawn_center.b) == settings.COLOR_EDITOR_SPAWN

    goal_center = thumbnail.get_at((int(cell_w * 1.5), int(cell_h * 0.5)))
    assert (goal_center.r, goal_center.g, goal_center.b) == settings.COLOR_EDITOR_GOAL


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


# --- Wave editor sidebar scrolling ---
#
# ENEMY_ORDER (8 species today) no longer needs to fit inside a fixed pixel
# budget between WAVE_UNIT_ROWS_TOP and the action buttons below (see
# ui.py's WAVE_UNIT_ROWS_TOP comment for why the previous cramped-fit
# approach broke again the moment a species was added) -- it scrolls
# instead, mirroring the level browser's own scroll mechanism exactly (see
# the "Level select scrolling" tests above this module for the template
# these follow).

def test_wave_unit_content_height_has_no_trailing_gap():
    one_row = wave_unit_content_height(1)
    two_rows = wave_unit_content_height(2)
    assert one_row == WAVE_UNIT_ROW_HEIGHT
    assert two_rows == 2 * WAVE_UNIT_ROW_HEIGHT


def test_wave_unit_max_scroll_is_zero_when_everything_fits():
    assert wave_unit_max_scroll(0) == 0
    assert wave_unit_max_scroll(1) == 0


def test_wave_unit_max_scroll_is_positive_once_the_registry_overflows_the_viewport():
    viewport_height = WAVE_UNIT_ROWS_BOTTOM - WAVE_UNIT_ROWS_TOP
    overflowing_count = viewport_height // WAVE_UNIT_ROW_HEIGHT + 5
    max_scroll = wave_unit_max_scroll(overflowing_count)
    assert max_scroll > 0
    assert max_scroll == wave_unit_content_height(overflowing_count) - viewport_height


def test_build_wave_unit_rects_shifts_rows_up_by_the_scroll_offset():
    unscrolled = build_wave_unit_rects(scroll_offset=0)
    scrolled = build_wave_unit_rects(scroll_offset=50)
    for name in ENEMY_TYPES:
        for suffix in ("minus", "plus"):
            key = (name, suffix)
            assert scrolled[key].y == unscrolled[key].y - 50
            assert scrolled[key].x == unscrolled[key].x  # only y moves


# --- _draw_centered_overlay ---

def test_draw_centered_overlay_skips_a_falsy_subtitle_line():
    # Documented in the docstring ("an empty string/list draws no subtitle
    # at all") -- no current caller (menu/pause/game-over/victory screens)
    # actually passes one, so this exercises it directly.
    pygame.font.init()
    font = pygame.font.SysFont(None, 32)
    small_font = pygame.font.SysFont(None, 22)
    surface = pygame.Surface((400, 300))

    _draw_centered_overlay(surface, font, small_font, "Title", ["", "a real line"], (255, 255, 255))
    # Must not raise, and the blank entry shouldn't have consumed a line's
    # worth of vertical space -- diffing against a version with just the
    # one real line should render identically.
    surface_without_blank = pygame.Surface((400, 300))
    _draw_centered_overlay(surface_without_blank, font, small_font, "Title", ["a real line"], (255, 255, 255))
    assert surface.get_buffer().raw == surface_without_blank.get_buffer().raw


# --- _wrap_text (editor validation-message word wrap) ---

def test_wrap_text_returns_an_empty_list_for_empty_text():
    pygame.font.init()
    font = pygame.font.SysFont(None, 22)
    assert _wrap_text("", font, max_width=1000) == []


def test_wrap_text_keeps_a_short_line_unwrapped():
    pygame.font.init()
    font = pygame.font.SysFont(None, 22)
    assert _wrap_text("short message", font, max_width=1000) == ["short message"]


def test_wrap_text_wraps_a_long_message_across_multiple_lines_within_the_width():
    pygame.font.init()
    font = pygame.font.SysFont(None, 22)
    text = "a validation message with enough short words to overflow a narrow width"
    max_width = 100
    lines = _wrap_text(text, font, max_width)

    assert len(lines) > 1
    for line in lines:
        assert font.size(line)[0] <= max_width
    assert " ".join(lines) == text  # every word preserved, in order, none dropped or duplicated


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
