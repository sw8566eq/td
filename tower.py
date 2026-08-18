"""Tower base class, concrete tower types, and the TOWER_TYPES registry.

Tower defines all shared behavior (targeting, cooldown/fire loop, range
check, drawing) as a template method; each concrete tower only sets
class-attribute stats and implements create_projectile(). Adding a new
tower type is: write a subclass, add one line to TOWER_TYPES. No other file
needs to change -- ui.py's build menu and game.py's placement logic both
iterate/index the registry rather than naming concrete classes.
"""

import pygame

import settings
from projectile import Projectile


class Tower:
    cost = 0
    range = 0
    damage = 0
    fire_rate = 1.0  # shots per second
    projectile_speed = 300.0
    sprite_name = ""
    display_name = "Tower"

    MAX_LEVEL = 3
    # Multiplier applied to each stat in LEVEL_SCALED_STATS at a given
    # level -- level 1 is always 1.0x (no bonus, the placed/base stats).
    LEVEL_STAT_MULTIPLIERS = {1: 1.0, 2: 1.35, 3: 1.8}
    # Which of a tower's own attributes get that multiplier on level-up.
    # A subclass can extend this tuple (e.g. + ("slow_duration",)) to have
    # more of its own stats scale too -- everything else about levelling
    # stays generic.
    LEVEL_SCALED_STATS = ("damage", "range")
    # Gold cost to reach level 2 / level 3, as a multiplier of this
    # tower's base `cost`.
    UPGRADE_COST_MULTIPLIERS = {2: 0.6, 3: 1.0}

    def __init__(self, col, row, pixel_pos):
        self.col = col
        self.row = row
        self.pos = pygame.Vector2(pixel_pos)
        self.cooldown = 0.0
        self.level = 1
        # Snapshot each scaled stat's level-1 value once, up front, so
        # every upgrade recomputes from the true base rather than
        # compounding on an already-scaled number.
        self._base_stats = {name: getattr(self, name) for name in self.LEVEL_SCALED_STATS}

    @property
    def is_max_level(self):
        return self.level >= self.MAX_LEVEL

    def upgrade_cost(self):
        """Gold cost to reach the next level, or None if already maxed."""
        if self.is_max_level:
            return None
        return round(self.cost * self.UPGRADE_COST_MULTIPLIERS[self.level + 1])

    def upgrade(self):
        """Level up by one, rescaling every LEVEL_SCALED_STATS entry from
        its level-1 base. No-op (returns False) once at MAX_LEVEL."""
        if self.is_max_level:
            return False
        self.level += 1
        multiplier = self.LEVEL_STAT_MULTIPLIERS[self.level]
        for name, base_value in self._base_stats.items():
            setattr(self, name, base_value * multiplier)
        return True

    def update(self, dt, enemies, projectiles):
        self.cooldown -= dt
        if self.cooldown > 0:
            return

        target = self.acquire_target(enemies)
        if target is None:
            return

        projectiles.append(self.create_projectile(target))
        self.cooldown = 1.0 / self.fire_rate

    def acquire_target(self, enemies):
        """In-range, non-dead enemy furthest along the path -- more robust
        than raw proximity on a path with switchbacks, and works unchanged
        regardless of which enemy species are involved."""
        candidates = [e for e in enemies if not e.is_dead and self.in_range(e)]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.distance_traveled)

    def in_range(self, enemy):
        return self.pos.distance_to(enemy.pos) <= self.range

    def create_projectile(self, target):
        raise NotImplementedError

    def draw(self, surface, assets):
        size = (settings.TILE_SIZE - 8, settings.TILE_SIZE - 8)
        sprite = assets.get(self.sprite_name, size)
        rect = sprite.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        surface.blit(sprite, rect)
        self._draw_level_pips(surface, rect)

    def _draw_level_pips(self, surface, sprite_rect):
        # One pip per level above 1 -- a level-1 (just-placed) tower shows
        # none, so upgraded towers are the ones that visibly stand out.
        pip_count = self.level - 1
        if pip_count <= 0:
            return
        pip_radius, spacing = 3, 9
        start_x = sprite_rect.centerx - spacing * (pip_count - 1) / 2
        y = sprite_rect.bottom - 2
        for i in range(pip_count):
            x = int(start_x + i * spacing)
            pygame.draw.circle(surface, settings.COLOR_GOLD, (x, y), pip_radius)
            pygame.draw.circle(surface, (0, 0, 0), (x, y), pip_radius, width=1)


class BasicTower(Tower):
    cost = 50
    range = 120
    damage = 10
    fire_rate = 1.2
    projectile_speed = 360.0
    sprite_name = "tower_basic"
    display_name = "Basic"

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.damage, sprite_name="projectile_basic",
        )


class CannonTower(Tower):
    cost = 100
    range = 100
    damage = 18
    fire_rate = 0.6
    projectile_speed = 260.0
    splash_radius = 55
    sprite_name = "tower_cannon"
    display_name = "Cannon"

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.damage, splash_radius=self.splash_radius,
            sprite_name="projectile_cannon",
        )


class FrostTower(Tower):
    cost = 75
    range = 110
    damage = 4
    fire_rate = 1.0
    projectile_speed = 320.0
    slow_factor = 0.5
    slow_duration = 2.0
    sprite_name = "tower_frost"
    display_name = "Frost"

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.damage, slow_effect=(self.slow_factor, self.slow_duration),
            sprite_name="projectile_frost",
        )


class KnockbackTower(Tower):
    cost = 90
    range = 90
    damage = 6
    fire_rate = 0.8
    projectile_speed = 300.0
    splash_radius = 70  # hits every enemy in this radius of the impact, not just the target
    # Seconds of each hit enemy's own forward progress to undo -- not a
    # fixed pixel distance, so faster enemies get shoved back further.
    # Kept small now that it's AoE: a big per-enemy shove across a whole
    # cluster would be far too strong.
    knockback_duration = 0.35
    sprite_name = "tower_knockback"
    display_name = "Knockback"

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.damage, splash_radius=self.splash_radius,
            knockback_duration=self.knockback_duration,
            sprite_name="projectile_knockback",
        )


TOWER_TYPES = {
    "basic": BasicTower,
    "cannon": CannonTower,
    "frost": FrostTower,
    "knockback": KnockbackTower,
}
