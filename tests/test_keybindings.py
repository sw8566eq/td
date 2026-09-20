"""Tests for keybindings.py -- mirrors test_player_settings.py's tmp_path
style so the real repo-root keybindings.json is never touched, plus
coverage for the matching/conflict helpers input_handler.py and Game.
rebind_action() build on."""

import pygame

from keybindings import (
    ACTION_ORDER,
    DEFAULT_BINDINGS,
    EDITOR_ACTIONS,
    PLAYING_ACTIONS,
    find_conflict,
    group_of,
    is_reserved,
    load_bindings,
    matches,
    normalize_mods,
    save_bindings,
)

# --- Persistence ---


def test_missing_file_returns_the_defaults(tmp_path):
    path = tmp_path / "keybindings.json"
    assert load_bindings(path) == DEFAULT_BINDINGS


def test_corrupt_file_falls_back_to_the_defaults(tmp_path):
    path = tmp_path / "keybindings.json"
    path.write_text("not valid json{{{")
    assert load_bindings(path) == DEFAULT_BINDINGS


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "keybindings.json"
    rebound = dict(DEFAULT_BINDINGS)
    rebound["pause"] = (pygame.K_k, 0)
    save_bindings(rebound, path)
    assert load_bindings(path) == rebound


def test_a_file_missing_an_action_fills_it_in_from_defaults(tmp_path):
    path = tmp_path / "keybindings.json"
    path.write_text('{"schema_version": 1, "bindings": {"pause": [107, 0]}}')
    loaded = load_bindings(path)
    assert loaded["pause"] == (pygame.K_k, 0)
    assert loaded["skip_wave"] == DEFAULT_BINDINGS["skip_wave"]


def test_a_malformed_entry_falls_back_to_that_actions_own_default(tmp_path):
    path = tmp_path / "keybindings.json"
    path.write_text('{"schema_version": 1, "bindings": {"pause": "not-a-pair"}}')
    assert load_bindings(path)["pause"] == DEFAULT_BINDINGS["pause"]


def test_a_non_dict_bindings_value_falls_back_to_every_default(tmp_path):
    path = tmp_path / "keybindings.json"
    path.write_text('{"schema_version": 1, "bindings": "nope"}')
    assert load_bindings(path) == DEFAULT_BINDINGS


def test_save_never_touches_a_different_path(tmp_path):
    real_path = tmp_path / "real.json"
    other_path = tmp_path / "other.json"
    save_bindings(DEFAULT_BINDINGS, real_path)
    assert not other_path.exists()


# --- normalize_mods ---


def test_normalize_mods_collapses_left_and_right_ctrl_to_the_same_bit():
    assert normalize_mods(pygame.KMOD_LCTRL) == pygame.KMOD_CTRL
    assert normalize_mods(pygame.KMOD_RCTRL) == pygame.KMOD_CTRL


def test_normalize_mods_combines_multiple_families():
    normalized = normalize_mods(pygame.KMOD_LCTRL | pygame.KMOD_LSHIFT)
    assert normalized == pygame.KMOD_CTRL | pygame.KMOD_SHIFT


def test_normalize_mods_drops_non_family_bits():
    assert normalize_mods(pygame.KMOD_NUM) == 0


# --- matches ---


def test_matches_requires_the_same_key():
    assert matches((pygame.K_p, 0), pygame.K_o, 0) is False


def test_unmodified_binding_matches_regardless_of_incidental_mods_held():
    assert matches((pygame.K_SPACE, 0), pygame.K_SPACE, pygame.KMOD_SHIFT) is True


def test_modified_binding_requires_the_modifier():
    assert matches((pygame.K_z, pygame.KMOD_CTRL), pygame.K_z, 0) is False


def test_modified_binding_matches_with_extra_incidental_mods_held():
    binding = (pygame.K_z, pygame.KMOD_CTRL)
    assert matches(binding, pygame.K_z, pygame.KMOD_CTRL | pygame.KMOD_SHIFT) is True


# --- group_of / find_conflict / is_reserved ---


def test_every_action_is_in_exactly_one_group():
    for action in ACTION_ORDER:
        assert (action in PLAYING_ACTIONS) != (action in EDITOR_ACTIONS)
        assert group_of(action) in (PLAYING_ACTIONS, EDITOR_ACTIONS)


def test_find_conflict_is_none_for_an_unused_key():
    assert find_conflict(DEFAULT_BINDINGS, "pause", pygame.K_k, 0) is None


def test_find_conflict_reports_the_other_action_in_the_same_group():
    key, mods = DEFAULT_BINDINGS["skip_wave"]
    assert find_conflict(DEFAULT_BINDINGS, "pause", key, mods) == "skip_wave"


def test_find_conflict_ignores_the_action_s_own_current_binding():
    key, mods = DEFAULT_BINDINGS["pause"]
    assert find_conflict(DEFAULT_BINDINGS, "pause", key, mods) is None


def test_find_conflict_never_fires_across_groups():
    # editor_undo's default (Ctrl+Z) shares no key with any PLAYING_
    # ACTIONS default, but even a literal key match across groups
    # couldn't collide at dispatch time (see that module's own docstring)
    # -- rebinding "pause" to a bare Z is never a conflict with editor_undo.
    assert find_conflict(DEFAULT_BINDINGS, "pause", pygame.K_z, 0) is None


def test_escape_is_reserved():
    assert is_reserved(pygame.K_ESCAPE) is True


def test_an_ordinary_key_is_not_reserved():
    assert is_reserved(pygame.K_p) is False
