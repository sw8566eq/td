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

    def __init__(self, col, row, pixel_pos):
        self.col = col
        self.row = row
        self.pos = pygame.Vector2(pixel_pos)
        self.cooldown = 0.0

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


TOWER_TYPES = {
    "basic": BasicTower,
    "cannon": CannonTower,
    "frost": FrostTower,
}
