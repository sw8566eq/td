import pygame

from projectile import Projectile
from tower import TOWER_TYPES, KnockbackTower


class FakeEnemy:
    def __init__(self, pos=(50, 50)):
        self.pos = pygame.Vector2(pos)
        self.is_dead = False


def test_every_registered_tower_creates_a_projectile_aimed_at_its_target():
    target = FakeEnemy()
    for name, tower_cls in TOWER_TYPES.items():
        tower = tower_cls(col=0, row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(target)
        assert isinstance(projectile, Projectile), name
        assert projectile.target is target, name
        assert projectile.damage == tower_cls.damage, name


def test_knockback_tower_is_registered():
    assert TOWER_TYPES["knockback"] is KnockbackTower


def test_knockback_tower_projectile_carries_a_positive_knockback_duration():
    tower = KnockbackTower(col=0, row=0, pixel_pos=(0, 0))
    projectile = tower.create_projectile(FakeEnemy())
    assert projectile.knockback_duration == KnockbackTower.knockback_duration
    assert projectile.knockback_duration > 0


def test_knockback_tower_is_aoe_but_only_a_light_shove():
    tower = KnockbackTower(col=0, row=0, pixel_pos=(0, 0))
    projectile = tower.create_projectile(FakeEnemy())
    assert projectile.splash_radius > 0
    # Now that it's AoE, the per-enemy shove should be much smaller than a
    # single-target knockback would reasonably be -- guard against someone
    # bumping this back up without noticing it now hits a whole cluster.
    assert projectile.knockback_duration <= 0.5


def test_other_towers_have_no_knockback():
    for name, tower_cls in TOWER_TYPES.items():
        if name == "knockback":
            continue
        tower = tower_cls(col=0, row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(FakeEnemy())
        assert projectile.knockback_duration == 0.0, name
