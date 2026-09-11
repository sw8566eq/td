import pygame
import pytest

from projectile import Projectile
from tower import (
    TOWER_TYPES, BasicTower, BeaconTower, BeamTower, KnockbackTower, LightningTower,
    PoisonTower, SniperTower, SupportTower, Tower,
)


class FakeEnemy:
    def __init__(self, pos=(50, 50)):
        self.pos = pygame.Vector2(pos)
        self.is_dead = False
        self.reached_goal = False
        self.distance_traveled = 0.0
        self.hp = 100


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
        if name == "support":
            continue  # never fires at all -- create_projectile() raises, see below
        tower = tower_cls(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(target)
        assert isinstance(projectile, Projectile), name
        assert projectile.target is target, name
        assert projectile.damage == tower_cls.damage, name


# --- Footprint geometry (see Game._current_footprint_subtiles for how a
# Compact Framework-style relic actually sets footprint_subtiles) ---

def test_tile_rect_is_a_full_tile_by_default():
    import settings
    tower = BasicTower(anchor_col=2, anchor_row=3, pixel_pos=(0, 0))
    rect = tower.tile_rect()
    assert rect.size == (settings.TILE_SIZE, settings.TILE_SIZE)
    assert rect.topleft == (2 * settings.SUBTILE_SIZE, 3 * settings.SUBTILE_SIZE)


def test_tile_rect_shrinks_with_footprint_subtiles():
    import settings
    tower = BasicTower(anchor_col=2, anchor_row=3, pixel_pos=(0, 0))
    tower.footprint_subtiles = 6

    rect = tower.tile_rect()

    size = 6 * settings.SUBTILE_SIZE
    assert rect.size == (size, size)
    assert rect.topleft == (2 * settings.SUBTILE_SIZE, 3 * settings.SUBTILE_SIZE)  # anchor unaffected


def test_upgrade_badge_center_sits_on_the_shrunk_footprints_own_corner():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    full_size_center = tower.upgrade_badge_center()

    tower.footprint_subtiles = 6
    shrunk_center = tower.upgrade_badge_center()

    # The badge sits at tile_rect()'s own top-right corner -- a smaller
    # rect's right edge is closer to the anchor, so the badge moves with
    # it rather than floating outside the now-smaller sprite.
    rect = tower.tile_rect()
    inset = tower.BADGE_RADIUS + 2
    assert shrunk_center == (rect.left + rect.width - inset, rect.top + inset)
    assert shrunk_center[0] < full_size_center[0]


def test_draw_requests_a_smaller_sprite_size_when_footprint_subtiles_is_reduced():
    import settings
    from assets import AssetManager

    class _SpyAssetManager(AssetManager):
        def __init__(self):
            super().__init__()
            self.requested_sizes = []

        def get(self, name, size):
            self.requested_sizes.append(size)
            return super().get(name, size)

    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    tower.footprint_subtiles = 6
    surface = pygame.Surface((100, 100))
    assets = _SpyAssetManager()

    tower.draw(surface, assets)

    margin = 2 * settings.SUBTILE_GAP
    expected_size = 6 * settings.SUBTILE_SIZE - margin
    assert assets.requested_sizes[0] == (expected_size, expected_size)


# --- Lifetime stats (post-level results screen -- see ui.compute_tower_results) ---

def test_new_tower_starts_with_every_stat_at_zero():
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    assert tower.shots_fired == 0
    assert tower.shots_hit == 0
    assert tower.damage_dealt == 0.0
    assert tower.kills == 0


def test_update_increments_shots_fired_on_a_successful_fire_cycle():
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    target = FakeEnemy((55, 50))  # well within range

    tower.update(dt=1.0, enemies=[target], projectiles=[])

    assert tower.shots_fired == 1


def test_update_does_not_increment_shots_fired_while_on_cooldown():
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    tower.cooldown = 10.0  # still well above zero after a small dt
    target = FakeEnemy((55, 50))

    tower.update(dt=0.01, enemies=[target], projectiles=[])

    assert tower.shots_fired == 0


def test_update_does_not_increment_shots_fired_with_no_target_in_range():
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    target = FakeEnemy((10_000, 10_000))  # far outside range

    tower.update(dt=1.0, enemies=[target], projectiles=[])

    assert tower.shots_fired == 0


def test_update_increments_shots_fired_once_per_shot_across_multiple_cycles():
    tower = KnockbackTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    target = FakeEnemy((55, 50))

    for _ in range(3):
        tower.update(dt=1.0 / tower.fire_rate, enemies=[target], projectiles=[])

    assert tower.shots_fired == 3


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
        if name in ("knockback", "support"):
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
        if name in ("lightning", "support"):
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
        if name in ("poison", "support"):
            continue
        tower = tower_cls(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(FakeEnemy())
        assert projectile.poison_effect is None, name


# --- Beam tower (ramps damage against a locked, uninterrupted target) ---

def test_beam_tower_is_registered():
    assert TOWER_TYPES["beam"] is BeamTower


def test_beam_tower_first_shot_at_a_target_has_no_ramp():
    tower = BeamTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    projectile = tower.create_projectile(FakeEnemy())
    assert projectile.damage == tower.damage


def test_beam_tower_ramps_damage_on_consecutive_hits_against_the_same_target():
    tower = BeamTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    target = FakeEnemy()
    first = tower.create_projectile(target)
    second = tower.create_projectile(target)
    third = tower.create_projectile(target)
    assert first.damage == tower.damage
    assert second.damage == pytest.approx(tower.damage * (1 + tower.ramp_per_hit))
    assert third.damage == pytest.approx(tower.damage * (1 + 2 * tower.ramp_per_hit))


def test_beam_tower_ramp_resets_when_the_target_changes():
    tower = BeamTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    first_target, second_target = FakeEnemy(), FakeEnemy()
    tower.create_projectile(first_target)
    tower.create_projectile(first_target)  # ramp has now built up

    switched = tower.create_projectile(second_target)

    assert switched.damage == tower.damage  # back to the un-ramped base


def test_beam_tower_ramp_is_capped_at_max_ramp_multiplier():
    tower = BeamTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    target = FakeEnemy()
    shots_needed_to_exceed_cap = int(tower.max_ramp_multiplier / tower.ramp_per_hit) + 5
    projectile = None
    for _ in range(shots_needed_to_exceed_cap):
        projectile = tower.create_projectile(target)
    assert projectile.damage == pytest.approx(tower.damage * tower.max_ramp_multiplier)


def test_beam_tower_specialization_boosts_carry_through_to_the_projectile():
    overcharge_tower = BeamTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    for _ in range(BeamTower.MAX_LEVEL - 1):
        overcharge_tower.upgrade()
    base_ramp_per_hit = overcharge_tower.ramp_per_hit
    overcharge_tower.specialize("overcharge")
    assert overcharge_tower.ramp_per_hit > base_ramp_per_hit

    discharge_tower = BeamTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    for _ in range(BeamTower.MAX_LEVEL - 1):
        discharge_tower.upgrade()
    base_damage = discharge_tower.damage
    discharge_tower.specialize("discharge")
    projectile = discharge_tower.create_projectile(FakeEnemy())
    assert projectile.damage == discharge_tower.damage
    assert projectile.damage > base_damage


# --- Support/Aura tower ---

def test_support_tower_is_registered():
    assert TOWER_TYPES["support"] is SupportTower


def test_support_tower_create_projectile_raises():
    tower = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    with pytest.raises(NotImplementedError):
        tower.create_projectile(FakeEnemy())


def test_support_tower_never_increments_shots_fired():
    tower = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    attacker = BasicTower(anchor_col=1, anchor_row=1, pixel_pos=(60, 50))
    tower.update(dt=1.0, enemies=[], projectiles=[], towers=[tower, attacker])
    assert tower.shots_fired == 0


def test_support_tower_buffs_an_attacking_tower_in_range():
    support = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    attacker = BasicTower(anchor_col=1, anchor_row=1, pixel_pos=(60, 50))  # well within support.range

    for tower in (support, attacker):
        tower.reset_aura()
    for tower in (support, attacker):
        tower.update(dt=1.0, enemies=[], projectiles=[], towers=[support, attacker])

    assert attacker.aura_damage_multiplier == SupportTower.buff_damage_multiplier
    assert attacker.aura_range_multiplier == SupportTower.buff_range_multiplier


def test_resonant_field_widens_a_support_towers_broadcast_reach():
    support = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    just_outside_base_reach = BasicTower(
        anchor_col=1, anchor_row=1, pixel_pos=(support.range + 10, 0),
    )
    support.update(dt=1.0, enemies=[], projectiles=[], towers=[support, just_outside_base_reach])
    assert just_outside_base_reach.aura_damage_multiplier == 1.0  # not yet buffed

    support.relic_aura_range_bonus_multiplier = 1.20
    support.update(dt=1.0, enemies=[], projectiles=[], towers=[support, just_outside_base_reach])

    assert just_outside_base_reach.aura_damage_multiplier == SupportTower.buff_damage_multiplier


def test_resonant_field_strengthens_a_support_towers_own_buff():
    support = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    attacker = BasicTower(anchor_col=1, anchor_row=1, pixel_pos=(60, 50))
    support.relic_aura_strength_bonus_multiplier = 1.20

    support.update(dt=1.0, enemies=[], projectiles=[], towers=[support, attacker])

    assert attacker.aura_damage_multiplier == pytest.approx(SupportTower.buff_damage_multiplier * 1.20)
    assert attacker.aura_range_multiplier == pytest.approx(SupportTower.buff_range_multiplier * 1.20)


def test_support_tower_does_not_buff_a_tower_out_of_range():
    support = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    far_attacker = BasicTower(anchor_col=10, anchor_row=10, pixel_pos=(10_000, 10_000))

    support.update(dt=1.0, enemies=[], projectiles=[], towers=[support, far_attacker])

    assert far_attacker.aura_damage_multiplier == 1.0
    assert far_attacker.aura_range_multiplier == 1.0


def test_support_tower_never_buffs_itself():
    support = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    support.update(dt=1.0, enemies=[], projectiles=[], towers=[support])
    assert support.aura_damage_multiplier == 1.0


def test_effective_damage_defaults_to_base_damage_with_no_buff():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    assert tower.effective_damage() == BasicTower.damage


def test_effective_damage_reflects_the_current_aura_multiplier():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.aura_damage_multiplier = 2.0
    assert tower.effective_damage() == BasicTower.damage * 2.0


def test_aura_buff_boosts_an_attacking_towers_shot_damage():
    attacker = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    attacker.aura_damage_multiplier = 2.0
    projectile = attacker.create_projectile(FakeEnemy())
    assert projectile.damage == BasicTower.damage * 2.0


def test_aura_buff_widens_an_attacking_towers_effective_range():
    attacker = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    just_outside_base_range = FakeEnemy((BasicTower.range + 10, 0))
    assert not attacker.in_range(just_outside_base_range)

    attacker.aura_range_multiplier = 2.0
    assert attacker.in_range(just_outside_base_range)


def test_reset_aura_clears_a_previously_applied_buff():
    attacker = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    attacker.receive_aura(damage_multiplier=1.5, range_multiplier=1.5)
    attacker.reset_aura()
    assert attacker.aura_damage_multiplier == 1.0
    assert attacker.aura_range_multiplier == 1.0


def test_effective_damage_reflects_the_relic_bonus():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_damage_bonus_multiplier = 1.25
    assert tower.effective_damage() == pytest.approx(BasicTower.damage * 1.25)


def test_effective_damage_stacks_aura_relic_and_last_stand_bonuses_additively():
    # Regression guard mirroring effective_range()'s own additive-stack
    # test: three independent bonus sources must ADD, not multiply and not
    # max() -- see effective_damage()'s own docstring.
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.aura_damage_multiplier = 1.5
    tower.relic_damage_bonus_multiplier = 1.25
    tower.relic_last_stand_bonus_multiplier = 1.3
    tower.set_last_stand_multiplier(True)

    assert tower.effective_damage() == pytest.approx(BasicTower.damage * 2.05)  # 1 + .5 + .25 + .3
    assert tower.effective_damage() != pytest.approx(BasicTower.damage * 1.5 * 1.25 * 1.3)  # not multiplicative
    assert tower.effective_damage() != pytest.approx(BasicTower.damage * max(1.5, 1.25, 1.3))  # not max()


def test_set_last_stand_multiplier_is_inactive_by_default():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_last_stand_bonus_multiplier = 1.3
    assert tower.effective_damage() == BasicTower.damage


def test_set_last_stand_multiplier_toggles_the_bonus_on_and_off():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_last_stand_bonus_multiplier = 1.3

    tower.set_last_stand_multiplier(True)
    assert tower.effective_damage() == pytest.approx(BasicTower.damage * 1.3)

    tower.set_last_stand_multiplier(False)
    assert tower.effective_damage() == BasicTower.damage


def test_effective_range_stacks_the_relic_bonus_additively_with_the_aura():
    # Regression guard: a Spyglass Array-style relic's bonus must ADD to a
    # Support tower's own per-frame aura buff, not multiply with it and
    # not take max() the way receive_aura()'s own multi-SupportTower rule
    # does -- see effective_range()'s own docstring.
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.aura_range_multiplier = 1.15
    tower.relic_range_bonus_multiplier = 1.10

    assert tower.effective_range() == pytest.approx(tower.range * 1.25)
    assert tower.effective_range() != pytest.approx(tower.range * 1.15 * 1.10)  # not multiplicative
    assert tower.effective_range() != pytest.approx(tower.range * max(1.15, 1.10))  # not max()


def test_effective_range_matches_range_with_no_aura_or_relic_bonus():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    assert tower.effective_range() == tower.range


def test_relic_range_bonus_alone_widens_in_range():
    attacker = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    just_outside_base_range = FakeEnemy((BasicTower.range + 10, 0))
    assert not attacker.in_range(just_outside_base_range)

    attacker.relic_range_bonus_multiplier = 2.0
    assert attacker.in_range(just_outside_base_range)


def test_effective_fire_rate_reflects_the_relic_bonus():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_fire_rate_bonus_multiplier = 1.08

    assert tower.effective_fire_rate() == pytest.approx(tower.fire_rate * 1.08)


def test_effective_fire_rate_matches_fire_rate_with_no_relic_bonus():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    assert tower.effective_fire_rate() == tower.fire_rate


def test_update_uses_effective_fire_rate_for_the_next_cooldown():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_fire_rate_bonus_multiplier = 2.0
    target = FakeEnemy((0, 0))

    tower.update(dt=0.0, enemies=[target], projectiles=[])

    assert tower.cooldown == pytest.approx(1.0 / (tower.fire_rate * 2.0))


def test_support_towers_own_aura_range_widens_with_a_relic_bonus_too():
    # No relic in this codebase singles out one tower type -- a Range
    # relic widens a Support tower's own reach the same as everyone
    # else's, so its aura reaches further too.
    support = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    support.relic_range_bonus_multiplier = 2.0
    other = BasicTower(anchor_col=10, anchor_row=10, pixel_pos=(support.range + 10, 0))

    support.update(dt=0.0, enemies=[], projectiles=[], towers=[support, other])

    assert other.aura_range_multiplier == support.buff_range_multiplier


def test_support_towers_own_broadcast_reach_ignores_a_buff_it_just_received():
    # Regression: SupportTower.update() must NOT use effective_range() for
    # its own broadcast check, since effective_range() folds in
    # aura_range_multiplier -- and Game.update()'s two-pass loop runs every
    # tower's own update() in list order, all sharing one frame, so a
    # Support tower earlier in the list can buff a later one *before* that
    # later one's own update() runs. If the later one's own broadcast
    # reach then also reflected that buff, one relic-widened Support tower
    # could chain-buff a second one into reaching further than its own
    # un-buffed range ever would, purely as an accident of placement
    # order -- see relic_adjusted_range()'s own docstring.
    a = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    b = SupportTower(anchor_col=1, anchor_row=0, pixel_pos=(a.range - 5, 0))  # within A's own reach
    c = SupportTower(anchor_col=2, anchor_row=0, pixel_pos=(a.range - 5 + b.range + 10, 0))  # outside B's un-buffed reach

    towers = [a, b, c]
    for tower in towers:
        tower.reset_aura()
    for tower in towers:
        tower.update(dt=0.0, enemies=[], projectiles=[], towers=towers)

    assert b.aura_range_multiplier == a.buff_range_multiplier  # A did buff B
    assert c.aura_range_multiplier == 1.0  # but B must not then chain the buff on to C


def test_receive_aura_keeps_the_stronger_buff_not_stacked():
    attacker = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    attacker.receive_aura(damage_multiplier=1.5, range_multiplier=1.5)
    attacker.receive_aura(damage_multiplier=1.2, range_multiplier=1.2)  # weaker -- must not override
    assert attacker.aura_damage_multiplier == 1.5
    assert attacker.aura_range_multiplier == 1.5

    attacker.receive_aura(damage_multiplier=2.0, range_multiplier=2.0)  # stronger -- must win
    assert attacker.aura_damage_multiplier == 2.0
    assert attacker.aura_range_multiplier == 2.0


def test_two_support_towers_in_range_take_the_stronger_buff_not_a_stacked_product():
    weak_support = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(50, 50))
    weak_support.buff_damage_multiplier = 1.1
    strong_support = SupportTower(anchor_col=1, anchor_row=1, pixel_pos=(60, 50))
    strong_support.buff_damage_multiplier = 1.5
    attacker = BasicTower(anchor_col=2, anchor_row=2, pixel_pos=(70, 50))

    towers = [weak_support, strong_support, attacker]
    for tower in towers:
        tower.reset_aura()
    for tower in towers:
        tower.update(dt=1.0, enemies=[], projectiles=[], towers=towers)

    assert attacker.aura_damage_multiplier == 1.5  # not 1.1 * 1.5


def test_support_tower_upgrade_scales_its_buff_strength_and_radius():
    tower = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    base_multiplier = tower.buff_damage_multiplier
    base_range = tower.range

    tower.upgrade()

    assert tower.buff_damage_multiplier > base_multiplier
    assert tower.range > base_range
    assert tower.damage == 0  # never scales -- not in LEVEL_SCALED_STATS


def test_support_tower_specializations_do_not_touch_a_permanently_zero_damage():
    tower = SupportTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    for _ in range(SupportTower.MAX_LEVEL - 1):
        tower.upgrade()
    assert tower.can_specialize
    tower.specialize("amplify")
    assert tower.damage == 0  # never touched -- "damage" isn't in SPECIALIZATIONS' stat_multipliers


# --- Overcrowded Circuits' own live density bonus (set_nearby_tower_bonus) ---
# set_nearby_tower_bonus() takes the board's own current towers list and
# scans it itself -- mirroring SupportTower.update()'s own precedent for
# "which other towers are near this one" -- rather than a caller reducing
# it to a bare count first, so these tests build small towers lists
# instead of passing pre-computed counts.

def _other_towers_at(count, distance):
    """`count` bare BasicTower instances, all `distance` px from the
    origin -- stand-ins for "other towers on the board"."""
    return [BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(distance, 0)) for _ in range(count)]


def test_set_nearby_tower_bonus_defaults_to_no_bonus():
    # Neutral relic_* defaults (radius 0) make this a no-op regardless of
    # how many other towers are on the board -- the relic-less-run case.
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.set_nearby_tower_bonus([tower] + _other_towers_at(5, distance=10))
    assert tower.relic_tower_density_bonus_multiplier == 1.0


def test_set_nearby_tower_bonus_scales_with_neighbor_count():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_tower_density_radius = 100
    tower.relic_tower_density_damage_bonus_per_neighbor = 0.02
    tower.relic_tower_density_damage_bonus_cap = 0.20
    tower.set_nearby_tower_bonus([tower] + _other_towers_at(3, distance=10))
    assert tower.relic_tower_density_bonus_multiplier == pytest.approx(1.06)  # 1 + 3 * 0.02


def test_set_nearby_tower_bonus_ignores_towers_outside_the_radius():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_tower_density_radius = 100
    tower.relic_tower_density_damage_bonus_per_neighbor = 0.02
    tower.relic_tower_density_damage_bonus_cap = 0.20
    towers = [tower] + _other_towers_at(3, distance=10) + _other_towers_at(2, distance=1000)
    tower.set_nearby_tower_bonus(towers)
    assert tower.relic_tower_density_bonus_multiplier == pytest.approx(1.06)  # the 2 far ones excluded


def test_set_nearby_tower_bonus_is_capped():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_tower_density_radius = 100
    tower.relic_tower_density_damage_bonus_per_neighbor = 0.02
    tower.relic_tower_density_damage_bonus_cap = 0.20
    tower.set_nearby_tower_bonus([tower] + _other_towers_at(50, distance=10))  # far beyond the cap
    assert tower.relic_tower_density_bonus_multiplier == pytest.approx(1.20)


def test_effective_damage_reflects_the_density_bonus():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_tower_density_radius = 100
    tower.relic_tower_density_damage_bonus_per_neighbor = 0.02
    tower.relic_tower_density_damage_bonus_cap = 0.20
    tower.set_nearby_tower_bonus([tower] + _other_towers_at(3, distance=10))
    assert tower.effective_damage() == pytest.approx(BasicTower.damage * 1.06)


def test_effective_damage_stacks_density_bonus_additively_with_everything_else():
    # Extends the existing three-source additive-stack regression above to
    # the fourth (Overcrowded Circuits-style) source -- still ADDs, never
    # multiplies or max()'s against the other three.
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.aura_damage_multiplier = 1.5
    tower.relic_damage_bonus_multiplier = 1.25
    tower.relic_last_stand_bonus_multiplier = 1.3
    tower.set_last_stand_multiplier(True)
    tower.relic_tower_density_radius = 100
    tower.relic_tower_density_damage_bonus_per_neighbor = 0.02
    tower.relic_tower_density_damage_bonus_cap = 0.20
    tower.set_nearby_tower_bonus([tower] + _other_towers_at(5, distance=10))  # +0.10, under the cap

    assert tower.effective_damage() == pytest.approx(BasicTower.damage * 2.15)  # 1 + .5 + .25 + .3 + .10
    assert tower.effective_damage() != pytest.approx(BasicTower.damage * 1.5 * 1.25 * 1.3 * 1.10)  # not multiplicative


# --- Adrenaline Rush's own live fire-rate bonus ---

def test_set_last_stand_multiplier_toggles_the_fire_rate_bonus_too():
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_last_stand_fire_rate_bonus_multiplier = 1.15
    assert tower.effective_fire_rate() == tower.fire_rate  # inactive by default

    tower.set_last_stand_multiplier(True)
    assert tower.effective_fire_rate() == pytest.approx(tower.fire_rate * 1.15)

    tower.set_last_stand_multiplier(False)
    assert tower.effective_fire_rate() == tower.fire_rate


def test_effective_fire_rate_stacks_relic_and_last_stand_bonuses_multiplicatively():
    # Unlike effective_damage()'s additive stack, effective_fire_rate() has
    # no aura source to protect -- both sources here just multiply.
    tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    tower.relic_fire_rate_bonus_multiplier = 1.08
    tower.relic_last_stand_fire_rate_bonus_multiplier = 1.15
    tower.set_last_stand_multiplier(True)

    assert tower.effective_fire_rate() == pytest.approx(tower.fire_rate * 1.08 * 1.15)


# --- Beacon tower (near-zero damage, marks whatever its splash touches) ---

def test_beacon_tower_is_registered():
    assert TOWER_TYPES["beacon"] is BeaconTower


def test_beacon_tower_projectile_carries_a_mark_effect():
    tower = BeaconTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    projectile = tower.create_projectile(FakeEnemy())
    assert projectile.mark_effect == (BeaconTower.mark_damage_multiplier, BeaconTower.mark_duration)
    assert projectile.splash_radius == BeaconTower.mark_splash_radius


def test_beacon_tower_specialization_boosts_carry_through_to_the_projectile():
    wide_beacon_tower = BeaconTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    for _ in range(BeaconTower.MAX_LEVEL - 1):
        wide_beacon_tower.upgrade()
    base_splash_radius = wide_beacon_tower.mark_splash_radius
    wide_beacon_tower.specialize("wide_beacon")
    projectile = wide_beacon_tower.create_projectile(FakeEnemy())
    assert projectile.splash_radius == wide_beacon_tower.mark_splash_radius
    assert projectile.splash_radius > base_splash_radius

    searing_brand_tower = BeaconTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    for _ in range(BeaconTower.MAX_LEVEL - 1):
        searing_brand_tower.upgrade()
    base_multiplier = searing_brand_tower.mark_damage_multiplier
    base_duration = searing_brand_tower.mark_duration
    searing_brand_tower.specialize("searing_brand")
    projectile = searing_brand_tower.create_projectile(FakeEnemy())
    assert projectile.mark_effect == (searing_brand_tower.mark_damage_multiplier, searing_brand_tower.mark_duration)
    assert searing_brand_tower.mark_damage_multiplier > base_multiplier
    assert searing_brand_tower.mark_duration > base_duration


def test_other_towers_have_no_mark_effect():
    for name, tower_cls in TOWER_TYPES.items():
        if name in ("beacon", "support"):
            continue
        tower = tower_cls(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
        projectile = tower.create_projectile(FakeEnemy())
        assert projectile.mark_effect is None, name
