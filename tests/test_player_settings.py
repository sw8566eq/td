"""Tests for player_settings.py -- mirrors test_progress.py's tmp_path style
so the real repo-root player_settings.json is never touched."""

from player_settings import DEFAULTS, load_settings, save_settings


def test_missing_file_returns_the_defaults(tmp_path):
    path = tmp_path / "player_settings.json"
    assert load_settings(path) == DEFAULTS


def test_corrupt_file_falls_back_to_the_defaults(tmp_path):
    path = tmp_path / "player_settings.json"
    path.write_text("not valid json{{{")
    assert load_settings(path) == DEFAULTS


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "player_settings.json"
    save_settings({"fullscreen": True, "difficulty": "hard"}, path)
    assert load_settings(path) == {"fullscreen": True, "difficulty": "hard"}


def test_a_file_missing_a_key_fills_it_in_from_defaults(tmp_path):
    path = tmp_path / "player_settings.json"
    path.write_text('{"schema_version": 1, "fullscreen": true}')
    assert load_settings(path) == {"fullscreen": True, "difficulty": "normal"}


def test_save_never_touches_a_different_path(tmp_path):
    real_path = tmp_path / "real.json"
    other_path = tmp_path / "other.json"
    save_settings({"fullscreen": True, "difficulty": "easy"}, real_path)
    assert not other_path.exists()
