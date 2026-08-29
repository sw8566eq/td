"""Difficulty modes: a registry of named multiplier bundles, same shape as
TOWER_TYPES/ENEMY_TYPES/LEVELS.

Every multiplier composes as an *extra* factor on top of today's existing
math (Enemy._scale's linear per-wave curve, Level's own starting_gold/
starting_lives) rather than replacing it -- see WaveManager._spawn_enemy and
Game._load_level_object for where these actually get applied. "normal" is
every multiplier at 1.0, so picking it is byte-for-byte the game's original,
pre-difficulty behavior.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DifficultyMode:
    key: str
    display_name: str
    enemy_hp_multiplier: float = 1.0
    enemy_speed_multiplier: float = 1.0
    enemy_gold_multiplier: float = 1.0
    starting_gold_multiplier: float = 1.0
    starting_lives_multiplier: float = 1.0


DIFFICULTY_MODES = {
    "easy": DifficultyMode(
        "easy", "Easy",
        enemy_hp_multiplier=0.75, enemy_gold_multiplier=1.15,
        starting_gold_multiplier=1.25, starting_lives_multiplier=1.5,
    ),
    "normal": DifficultyMode("normal", "Normal"),
    "hard": DifficultyMode(
        "hard", "Hard",
        enemy_hp_multiplier=1.35, enemy_speed_multiplier=1.1, enemy_gold_multiplier=0.9,
        starting_gold_multiplier=0.85, starting_lives_multiplier=0.75,
    ),
}
DIFFICULTY_ORDER = list(DIFFICULTY_MODES.keys())  # stable UI order = registry insertion order
DEFAULT_DIFFICULTY = "normal"
