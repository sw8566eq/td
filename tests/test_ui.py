import pygame

from ui import build_button_rects, get_clicked_tower_button


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
