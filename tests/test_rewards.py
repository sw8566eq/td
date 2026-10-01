"""Tests for run/rewards.py -- the post-combat reward offer itself. The
REWARD screen's Game-level flow is covered in test_run.py."""

import random

from conftest import make_linear_run_map

from entities.tower import TOWER_TYPES
from run import card_pool, rewards
from run.card_pool import STARTER_TOWERS
from run.relics import RELICS
from run.run_state import RunState


def _run(**overrides):
    kwargs = {
        "seed": 1, "map": make_linear_run_map(["combat"]), "difficulty": "normal",
        "unlocked_towers": list(STARTER_TOWERS),
    }
    kwargs.update(overrides)
    return RunState(**kwargs)


def test_combat_reward_offers_unheld_towers_and_no_relic(tmp_path, monkeypatch):
    monkeypatch.setattr(card_pool, "_default_unlocked_pool", lambda _path: list(TOWER_TYPES))
    run = _run()
    reward = rewards.build_combat_reward(
        random.Random(1), run, is_elite=False, meta_progression_path=str(tmp_path / "meta.json"),
    )
    assert len(reward.tower_choices) == rewards.TOWER_REWARD_COUNT
    assert not set(reward.tower_choices) & set(STARTER_TOWERS)
    assert reward.relic is None
    assert not reward.is_empty


def test_elite_reward_adds_an_unheld_relic(tmp_path):
    run = _run(relics=["lucky_strikes"])
    reward = rewards.build_combat_reward(
        random.Random(1), run, is_elite=True, meta_progression_path=str(tmp_path / "meta.json"),
    )
    assert reward.relic in RELICS
    assert reward.relic != "lucky_strikes"


def test_reward_is_empty_once_every_pool_is_exhausted(tmp_path):
    run = _run(unlocked_towers=list(TOWER_TYPES), relics=list(RELICS))
    reward = rewards.build_combat_reward(
        random.Random(1), run, is_elite=True, meta_progression_path=str(tmp_path / "meta.json"),
    )
    assert reward.tower_choices == ()
    assert reward.relic is None
    assert reward.is_empty


def test_same_rng_seed_gives_the_same_reward(tmp_path):
    path = str(tmp_path / "meta.json")
    first = rewards.build_combat_reward(random.Random(7), _run(), is_elite=True, meta_progression_path=path)
    second = rewards.build_combat_reward(random.Random(7), _run(), is_elite=True, meta_progression_path=path)
    assert first == second
