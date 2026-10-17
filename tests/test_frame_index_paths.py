"""The spatial-index fast paths must give the same answers as a raw-list scan.

Every enemy-vs-enemies query that Game.update() narrows with an index
(healer heals, splash, chain hops, ground fires) has an index-free fallback,
and the two must agree exactly, visiting order included. See
docs/agents/towers.md "Tower targeting is broad-phase, not brute-force".
"""

import random

import pygame
import pytest

from entities.effects import GroundFire
from entities.enemy import GruntEnemy, HealerEnemy
from entities.projectile import Projectile
from world.spatial_index import EnemySpatialIndex, MovingEnemyIndex


class FakeEnemy:
    def __init__(self, pos, is_dead=False, reached_goal=False):
        self.pos = pygame.Vector2(pos)
        self.is_dead = is_dead
        self.reached_goal = reached_goal


def _enemy_at(x, y=0.0, cls=GruntEnemy):
    enemy = cls([pygame.Vector2(x, y), pygame.Vector2(x + 2000, y)], wave_number=1)
    enemy.pos = pygame.Vector2(x, y)
    return enemy


def _board(count=60, seed=7):
    rng = random.Random(seed)
    return [_enemy_at(rng.uniform(0, 600), rng.uniform(0, 400)) for _ in range(count)]


# --- EnemySpatialIndex.near_in_order / MovingEnemyIndex ---

def test_near_in_order_returns_candidates_in_original_list_order():
    # Spread across several cells, listed in an order no bucket walk gives.
    enemies = [FakeEnemy((300, 0)), FakeEnemy((10, 0)), FakeEnemy((150, 0)), FakeEnemy((20, 0))]
    index = EnemySpatialIndex(enemies, cell_size=128)
    assert index.near_in_order(pygame.Vector2(150, 0), radius=200) == enemies


def test_near_in_order_skips_enemies_excluded_at_build_time():
    alive, dead = FakeEnemy((10, 0)), FakeEnemy((12, 0), is_dead=True)
    index = EnemySpatialIndex([dead, alive])
    assert index.near_in_order(pygame.Vector2(0, 0), radius=50) == [alive]


def test_moving_index_builds_lazily_on_first_query():
    enemy = FakeEnemy((10, 0))
    index = MovingEnemyIndex([enemy])
    assert not index.built
    assert index.near(pygame.Vector2(0, 0), 50) == [enemy]
    assert index.built
    assert index.near_in_order(pygame.Vector2(0, 0), 50) == [enemy]


def test_moving_index_widens_queries_by_the_largest_reported_move():
    enemy = FakeEnemy((10, 0))
    index = MovingEnemyIndex([enemy], cell_size=16)
    index.near(pygame.Vector2(0, 0), 1)  # snapshot taken with the enemy at x=10
    enemy.pos = pygame.Vector2(400, 0)   # then it moves far away
    index.note_moved(390.0)
    index.note_moved(5.0)  # a smaller move never shrinks the slack
    assert index.slack == 390.0
    # Its snapshot cell (x=10) is now inside the widened query around x=400.
    assert enemy in index.near(pygame.Vector2(400, 0), 1)
    assert enemy in index.near_in_order(pygame.Vector2(400, 0), 1)


# --- HealerEnemy ---

def test_healer_with_a_moving_index_heals_exactly_who_the_list_scan_heals():
    def run(use_index):
        enemies = _board()
        healers = [_enemy_at(300, 200, HealerEnemy), _enemy_at(100, 100, HealerEnemy)]
        enemies[10:10] = healers[:1]
        enemies.append(healers[1])
        for enemy in enemies:
            enemy.hp = enemy.max_hp / 2
        index = MovingEnemyIndex(enemies)
        for enemy in enemies:
            if use_index and index.built:
                x, y = enemy.pos.x, enemy.pos.y
                enemy.update(0.5, enemies, index)
                index.note_moved(enemy.pos.distance_to((x, y)))
            else:
                enemy.update(0.5, enemies, index if use_index else None)
        return [(enemy.hp, enemy.pos.x, enemy.pos.y) for enemy in enemies]

    assert run(use_index=True) == run(use_index=False)


# --- Projectile splash / chain ---

def _shot(target, **kwargs):
    return Projectile(pygame.Vector2(target.pos), target, speed=1000, damage=7, **kwargs)


@pytest.mark.parametrize("kwargs", [
    {"splash_radius": 120, "relic_crit_chance": 0.5, "relic_crit_damage_multiplier": 2.0},
    {"chain_range": 150, "max_chain_targets": 6},
    {"relic_chain_chance": 1.0, "relic_chain_effect": (0.5, 200), "relic_overkill_carry_fraction": 1.0},
])
def test_projectile_hits_with_an_index_match_the_raw_list_scan(kwargs):
    def run(use_index):
        random.seed(3)
        enemies = _board()
        # Two equidistant chain candidates, so the tie-break is exercised too.
        enemies.append(_enemy_at(enemies[0].pos.x + 40, enemies[0].pos.y))
        enemies.insert(1, _enemy_at(enemies[0].pos.x - 40, enemies[0].pos.y))
        enemies[0].hp = 1.0  # an overkill to carry
        index = EnemySpatialIndex(enemies) if use_index else None
        _shot(enemies[0], **kwargs).update(0.1, enemies, index)
        return [enemy.hp for enemy in enemies], random.random()

    assert run(use_index=True) == run(use_index=False)


# --- Ground fires ---

def test_ground_fires_with_an_index_match_the_raw_list_scan(game):
    class Source:
        damage_dealt = 0.0
        kills = 0

    def run(use_index):
        game.enemies = _board()
        source = Source()
        game.ground_fires = [GroundFire(pygame.Vector2(300, 200), 150, 13.7, 5.0, source),
                             GroundFire(pygame.Vector2(100, 100), 90, 3.1, 5.0, source)]
        index = MovingEnemyIndex(game.enemies) if use_index else None
        game._update_ground_fires(0.37, index)
        return [enemy.hp for enemy in game.enemies], source.damage_dealt

    assert run(use_index=True) == run(use_index=False)
