"""Tests for the difficulty.py registry -- see waves.py/game.py for where
these multipliers actually get applied."""

from difficulty import DEFAULT_DIFFICULTY, DIFFICULTY_MODES


def test_registry_has_easy_normal_and_hard():
    assert set(DIFFICULTY_MODES.keys()) == {"easy", "normal", "hard"}


def test_default_difficulty_is_normal():
    assert DEFAULT_DIFFICULTY == "normal"


def test_normal_is_every_multiplier_at_one_exact_parity_with_pre_difficulty_behavior():
    normal = DIFFICULTY_MODES["normal"]
    assert normal.enemy_hp_multiplier == 1.0
    assert normal.enemy_speed_multiplier == 1.0
    assert normal.enemy_gold_multiplier == 1.0
    assert normal.starting_gold_multiplier == 1.0
    assert normal.starting_lives_multiplier == 1.0


def test_easy_is_gentler_than_normal():
    easy = DIFFICULTY_MODES["easy"]
    assert easy.enemy_hp_multiplier < 1.0
    assert easy.starting_gold_multiplier > 1.0
    assert easy.starting_lives_multiplier > 1.0


def test_hard_is_tougher_than_normal():
    hard = DIFFICULTY_MODES["hard"]
    assert hard.enemy_hp_multiplier > 1.0
    assert hard.starting_gold_multiplier < 1.0
    assert hard.starting_lives_multiplier < 1.0


def test_every_mode_key_matches_its_own_registry_key():
    for key, mode in DIFFICULTY_MODES.items():
        assert mode.key == key
