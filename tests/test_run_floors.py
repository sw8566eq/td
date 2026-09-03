import random

from levels import LEVELS
from run_floors import DEFAULT_FLOOR_COUNT, sample_floor_sequence


def test_default_count_and_pool():
    sequence = sample_floor_sequence(random.Random(1))
    assert len(sequence) == DEFAULT_FLOOR_COUNT
    assert set(sequence).issubset(LEVELS.keys())


def test_no_duplicate_floors():
    sequence = sample_floor_sequence(random.Random(1), count=8)
    assert len(sequence) == len(set(sequence))


def test_kept_in_ascending_order_not_shuffled():
    sequence = sample_floor_sequence(random.Random(1), count=8)
    assert sequence == tuple(sorted(sequence))


def test_deterministic_for_a_fixed_seed():
    first = sample_floor_sequence(random.Random(42))
    second = sample_floor_sequence(random.Random(42))
    assert first == second


def test_count_is_clamped_to_the_pool_size():
    sequence = sample_floor_sequence(random.Random(1), count=len(LEVELS) + 5)
    assert len(sequence) == len(LEVELS)
    assert set(sequence) == set(LEVELS.keys())


def test_custom_level_pool_is_respected():
    pool = {2: LEVELS[2], 6: LEVELS[6]}
    sequence = sample_floor_sequence(random.Random(1), count=5, level_pool=pool)
    assert set(sequence) == {2, 6}
