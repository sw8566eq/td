"""A single, data-parametrized Projectile class.

Splash-vs-single-target, slow-vs-no-slow, and knockback-vs-no-knockback are
all differences in the data passed at construction (fed by each Tower
subclass's create_projectile()), not separate Projectile subclasses -- the
resolution algorithm is identical either way, just applied to one enemy or
many.
"""

import pygame


class Projectile:
    def __init__(self, pos, target, speed, damage, splash_radius=0, slow_effect=None,
                 knockback_duration=0.0, sprite_name=""):
        self.pos = pygame.Vector2(pos)
        self.target = target
        self.speed = speed
        self.damage = damage
        self.splash_radius = splash_radius
        self.slow_effect = slow_effect  # (factor, duration) or None
        # Seconds of forward path progress to undo on hit, at the enemy's
        # speed at the moment of impact -- 0 means no knockback.
        self.knockback_duration = knockback_duration
        self.sprite_name = sprite_name
        self.dead = False

    def update(self, dt, enemies):
        if self.dead:
            return

        if self.target.is_dead:
            # Target died before impact -- discard as a dud rather than
            # retargeting (a deliberate MVP simplification).
            self.dead = True
            return

        to_target = self.target.pos - self.pos
        distance = to_target.length()
        step = self.speed * dt

        if distance <= step or distance == 0:
            self._resolve_hit(self.target.pos, enemies)
            self.dead = True
        else:
            self.pos += to_target.normalize() * step

    def _resolve_hit(self, impact_pos, enemies):
        if self.splash_radius > 0:
            for enemy in enemies:
                if enemy.is_dead:
                    continue
                if impact_pos.distance_to(enemy.pos) <= self.splash_radius:
                    self._apply_hit_effects(enemy)
        else:
            self._apply_hit_effects(self.target)

    def _apply_hit_effects(self, enemy):
        enemy.take_damage(self.damage)
        if self.slow_effect is not None:
            enemy.apply_slow(*self.slow_effect)
        if self.knockback_duration:
            enemy.apply_knockback(enemy.speed * self.knockback_duration)

    def draw(self, surface, assets):
        size = (12, 12)
        sprite = assets.get(self.sprite_name, size)
        rect = sprite.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        surface.blit(sprite, rect)
