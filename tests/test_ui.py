import pygame

import settings
from ui import (
    build_button_rects,
    build_sell_button_rect,
    build_skip_button_rect,
    build_upgrade_button_rect,
    get_clicked_tower_button,
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
