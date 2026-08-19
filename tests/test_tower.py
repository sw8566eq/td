import pygame

from projectile import Projectile
from tower import TOWER_TYPES, KnockbackTower, LightningTower


class FakeEnemy:
    def __init__(self, pos=(50, 50)):
        self.pos = pygame.Vector2(pos)
        self.is_dead = False


def test_every_registered_tower_creates_a_projectile_aimed_at_its_target():
    target = FakeEnemy()
    for name, tower_cls in TOWER_TYPES.items():
        tower = tower_cls(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(target)
        assert isinstance(projectile, Projectile), name
        assert projectile.target is target, name
        assert projectile.damage == tower_cls.damage, name


def test_knockback_tower_is_registered():
    assert TOWER_TYPES["knockback"] is KnockbackTower


def test_knockback_tower_projectile_carries_a_positive_knockback_duration():
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    projectile = tower.create_projectile(FakeEnemy())
    assert projectile.knockback_duration == KnockbackTower.knockback_duration
    assert projectile.knockback_duration > 0


def test_knockback_tower_is_aoe_but_only_a_light_shove():
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
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
        tower = tower_cls(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(FakeEnemy())
        assert projectile.knockback_duration == 0.0, name


def test_lightning_tower_is_registered():
    assert TOWER_TYPES["lightning"] is LightningTower


def test_lightning_tower_projectile_carries_chain_settings():
    tower = LightningTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    projectile = tower.create_projectile(FakeEnemy())
    assert projectile.chain_range == LightningTower.chain_range
    assert projectile.chain_range > 0
    assert projectile.max_chain_targets == LightningTower.max_chain_targets


def test_lightning_tower_chain_has_no_target_cap():
    assert LightningTower.max_chain_targets == float("inf")


def test_other_towers_do_not_chain():
    for name, tower_cls in TOWER_TYPES.items():
        if name == "lightning":
            continue
        tower = tower_cls(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(FakeEnemy())
        assert projectile.chain_range == 0.0, name
