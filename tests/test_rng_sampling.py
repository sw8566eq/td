import random

from rng_sampling import sample_up_to


def test_sample_up_to_returns_the_requested_count_when_pool_has_enough():
    result = sample_up_to(random.Random(1), ["a", "b", "c", "d"], count=2)
    assert len(result) == 2
    assert len(set(result)) == 2  # no replacement
    assert set(result).issubset({"a", "b", "c", "d"})


def test_sample_up_to_returns_fewer_once_the_pool_is_exhausted():
    assert sample_up_to(random.Random(1), ["a", "b"], count=5) == sample_up_to(random.Random(1), ["a", "b"], count=2)
    assert len(sample_up_to(random.Random(1), ["a", "b"], count=5)) == 2


def test_sample_up_to_on_an_empty_pool_returns_empty():
    assert sample_up_to(random.Random(1), [], count=3) == []


def test_sample_up_to_never_raises_for_count_larger_than_the_pool():
    # random.Random.sample() itself would raise ValueError here --
    # sample_up_to's whole point is clamping count first so callers never
    # have to guard against that themselves.
    sample_up_to(random.Random(1), ["a"], count=100)


def test_sample_up_to_is_deterministic_for_a_fixed_rng_seed():
    first = sample_up_to(random.Random(7), ["a", "b", "c"], count=2)
    second = sample_up_to(random.Random(7), ["a", "b", "c"], count=2)
    assert first == second
