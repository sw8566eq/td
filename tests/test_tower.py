import pygame
import pytest

from projectile import Projectile
from tower import TOWER_TYPES, KnockbackTower, LightningTower, PoisonTower, SniperTower, Tower


class FakeEnemy:
    def __init__(self, pos=(50, 50)):
        self.pos = pygame.Vector2(pos)
        self.is_dead = False


def test_base_tower_create_projectile_is_not_implemented():
    # Every registered TOWER_TYPES entry overrides this -- the base class's
    # own stub only exists to document the required interface.
    tower = Tower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    with pytest.raises(NotImplementedError):
        tower.create_projectile(FakeEnemy())


def test_draw_without_a_font_skips_the_upgrade_badge():
    from assets import AssetManager
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    surface = pygame.Surface((100, 100))
    assets = AssetManager()

    tower.draw(surface, assets)  # font defaults to None -- must not raise

    # No badge drawn: the corner it would occupy stays whatever the sprite
    # itself left there, not the badge's own selected-button color.
    from settings import COLOR_BUTTON_SELECTED
    cx, cy = tower.upgrade_badge_center()
    assert surface.get_at((cx, cy))[:3] != COLOR_BUTTON_SELECTED


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


def test_lightning_tower_specialization_boosts_carry_through_to_the_projectile():
    # Confirms the boost isn't just sitting inert on the Tower -- since
    # create_projectile() reads chain_range/damage straight off self,
    # every shot fired after specializing should reflect it.
    arc_reach_tower = LightningTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    for _ in range(LightningTower.MAX_LEVEL - 1):
        arc_reach_tower.upgrade()
    base_chain_range = arc_reach_tower.chain_range
    arc_reach_tower.specialize("arc_reach")
    projectile = arc_reach_tower.create_projectile(FakeEnemy())
    assert projectile.chain_range == arc_reach_tower.chain_range
    assert projectile.chain_range > base_chain_range

    overcharge_tower = LightningTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    for _ in range(LightningTower.MAX_LEVEL - 1):
        overcharge_tower.upgrade()
    base_damage = overcharge_tower.damage
    overcharge_tower.specialize("overcharge")
    projectile = overcharge_tower.create_projectile(FakeEnemy())
    assert projectile.damage == overcharge_tower.damage
    assert projectile.damage > base_damage


def test_other_towers_do_not_chain():
    for name, tower_cls in TOWER_TYPES.items():
        if name == "lightning":
            continue
        tower = tower_cls(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(FakeEnemy())
        assert projectile.chain_range == 0.0, name


def test_sniper_tower_is_registered():
    assert TOWER_TYPES["sniper"] is SniperTower


def test_sniper_tower_has_no_special_projectile_mechanic():
    # A pure high-damage/long-range/slow-fire-rate pick -- no splash, slow,
    # knockback, chain, or poison, same as BasicTower.
    tower = SniperTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    projectile = tower.create_projectile(FakeEnemy())
    assert projectile.splash_radius == 0
    assert projectile.slow_effect is None
    assert projectile.knockback_duration == 0.0
    assert projectile.chain_range == 0.0
    assert projectile.poison_effect is None


def test_poison_tower_is_registered():
    assert TOWER_TYPES["poison"] is PoisonTower


def test_poison_tower_projectile_carries_a_poison_effect():
    tower = PoisonTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    projectile = tower.create_projectile(FakeEnemy())
    assert projectile.poison_effect == (
        PoisonTower.poison_damage_per_tick, PoisonTower.poison_tick_interval, PoisonTower.poison_duration,
    )


def test_other_towers_have_no_poison_effect():
    for name, tower_cls in TOWER_TYPES.items():
        if name == "poison":
            continue
        tower = tower_cls(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(FakeEnemy())
        assert projectile.poison_effect is None, name
