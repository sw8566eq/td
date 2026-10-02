"""The Mortar -- long range, a minimum-range dead zone, big splash."""

import pygame

from entities.enemy import FlyingEnemy, GruntEnemy
from entities.tower import TOWER_TYPES, MortarTower


def _enemy_at(x, cls=GruntEnemy):
    enemy = cls([pygame.Vector2(x, 0), pygame.Vector2(x + 500, 0)], wave_number=1)
    enemy.pos = pygame.Vector2(x, 0)
    return enemy


def test_mortar_cannot_hit_inside_its_dead_zone():
    mortar = MortarTower(0, 0, pygame.Vector2(0, 0))
    near, far = _enemy_at(MortarTower.MIN_RANGE - 10), _enemy_at(MortarTower.MIN_RANGE + 50)
    assert mortar.acquire_target([near]) is None
    assert mortar.acquire_target([near, far]) is far


def test_mortar_ignores_flyers_and_splashes():
    mortar = MortarTower(0, 0, pygame.Vector2(0, 0))
    assert mortar.acquire_target([_enemy_at(150, FlyingEnemy)]) is None
    target = _enemy_at(150)
    assert mortar.create_projectile(target).splash_radius == MortarTower.splash_radius


def test_ordinary_towers_have_no_dead_zone():
    assert all(cls.MIN_RANGE == 0 for name, cls in TOWER_TYPES.items() if name != "mortar")


def test_range_previews_draw_the_dead_zone():
    from presentation import ui

    surface = pygame.Surface((400, 400))
    ui.draw_range_preview(surface, MortarTower, (200, 200))
    ui.draw_tower_range_preview(surface, MortarTower(0, 0, pygame.Vector2(200, 200)))
