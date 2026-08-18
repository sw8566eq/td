"""Enemy base class, concrete species, and the ENEMY_TYPES registry.

Enemy carries all shared movement/HP/slow logic plus per-wave scaling, all
as overridable class attributes. v1 ships one species (GruntEnemy), but a
new species -- a fast scout, an armored tank, a flier -- is written the same
way towers are: subclass Enemy, override stats (and update()/take_damage()
too, if it needs genuinely different behavior like a shield), then add one
line to ENEMY_TYPES. Levels reference enemies by their registry name string
in wave_specs (see levels.py), so WaveManager never needs to know about
concrete Enemy subclasses directly.
"""

import pygame


class Enemy:
    # --- Per-wave scaling stats (all overridable per subclass) ---
    base_hp = 50
    hp_per_wave = 12
    base_speed = 60.0  # pixels/sec
    speed_per_wave = 3.0
    max_speed = 140.0
    base_reward = 10
    reward_per_wave = 2

    sprite_name = "enemy_grunt"
    radius = 16  # pixels; used for drawing size

    # How fast (px/sec) a knockback shove animates -- separate from the
    # enemy's own forward speed, since a knockback is a hit landing on the
    # enemy, not the enemy's own movement.
    knockback_speed = 150.0

    def __init__(self, waypoints_px, wave_number):
        self.waypoints = waypoints_px
        self.wp_index = 1  # index of the next waypoint to reach
        self.pos = pygame.Vector2(waypoints_px[0])
        self.wave_number = wave_number

        self.max_hp = self._scale(self.base_hp, self.hp_per_wave, wave_number)
        self.hp = self.max_hp
        self.speed = min(self._scale(self.base_speed, self.speed_per_wave, wave_number), self.max_speed)
        self.gold_reward = self._scale(self.base_reward, self.reward_per_wave, wave_number)

        self.slow_multiplier = 1.0
        self.slow_timer = 0.0

        self.knockback_remaining = 0.0  # px of backward slide still owed

        self.distance_traveled = 0.0
        self.is_dead = False
        self.reached_goal = False

    @staticmethod
    def _scale(base, per_wave, wave_number):
        return base + per_wave * (wave_number - 1)

    def update(self, dt):
        if self.is_dead or self.reached_goal:
            return

        if self.slow_timer > 0:
            self.slow_timer -= dt
            if self.slow_timer <= 0:
                self.slow_timer = 0.0
                self.slow_multiplier = 1.0

        if self.knockback_remaining > 0:
            # Slide backward at a fixed animation speed instead of the
            # enemy's own forward movement this frame -- being shoved and
            # walking forward don't happen at once.
            self._advance_knockback(dt)
            return

        if self.wp_index >= len(self.waypoints):
            self.reached_goal = True
            return

        target = self.waypoints[self.wp_index]
        to_target = target - self.pos
        distance = to_target.length()
        step = self.speed * self.slow_multiplier * dt

        if distance <= step or distance == 0:
            self.distance_traveled += distance
            self.pos = pygame.Vector2(target)
            self.wp_index += 1
            if self.wp_index >= len(self.waypoints):
                self.reached_goal = True
        else:
            self.pos += to_target.normalize() * step
            self.distance_traveled += step

    def take_damage(self, amount):
        if self.is_dead:
            return
        self.hp -= amount
        if self.hp <= 0:
            self.hp = 0
            self.is_dead = True

    def apply_slow(self, factor, duration):
        # Keep the stronger of current vs. new slow so repeated hits refresh
        # rather than weaken the effect.
        self.slow_multiplier = min(self.slow_multiplier, factor)
        self.slow_timer = max(self.slow_timer, duration)

    def apply_knockback(self, distance):
        """Queue `distance` pixels of backward path travel, animated over
        the next several update() calls at knockback_speed rather than
        applied instantly.

        No angle/physics involved -- it's still just rewinding path
        progress (distance_traveled) and re-deriving position/waypoint-
        index from that (see _advance_knockback/_seek_to_distance), which
        works the same regardless of which way the enemy is facing or how
        many turns the path has. A knockback landing while a previous one
        is still playing out adds to it, so stacked hits compound into one
        longer slide rather than resetting or being ignored.
        """
        if self.is_dead or self.reached_goal or distance <= 0:
            return
        self.knockback_remaining += distance

    def _advance_knockback(self, dt):
        step = min(self.knockback_speed * dt, self.knockback_remaining)
        new_distance = self.distance_traveled - step
        if new_distance <= 0:
            # Hit the start of the path -- nowhere left to push, so drop
            # any leftover shove instead of leaving the enemy stuck
            # "mid-knockback" (unable to move forward) while remaining
            # counts down doing nothing visible.
            new_distance = 0.0
            self.knockback_remaining = 0.0
        else:
            self.knockback_remaining -= step
        self._seek_to_distance(new_distance)

    def _seek_to_distance(self, distance):
        """Recompute pos/wp_index to match a given cumulative path
        distance (0 = start of path). Only used by apply_knockback --
        ordinary forward movement advances incrementally in update()
        instead."""
        self.distance_traveled = distance
        remaining = distance
        last_index = len(self.waypoints) - 1
        for i in range(1, len(self.waypoints)):
            segment = self.waypoints[i] - self.waypoints[i - 1]
            segment_len = segment.length()
            if remaining <= segment_len or i == last_index:
                t = 0.0 if segment_len == 0 else min(remaining / segment_len, 1.0)
                self.pos = self.waypoints[i - 1] + segment * t
                self.wp_index = i
                return
            remaining -= segment_len
        # Degenerate single-waypoint path -- nowhere to go.
        self.pos = pygame.Vector2(self.waypoints[0])
        self.wp_index = 1

    def draw(self, surface, assets):
        size = (self.radius * 2, self.radius * 2)
        sprite = assets.get(self.sprite_name, size)
        rect = sprite.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        surface.blit(sprite, rect)
        self._draw_health_bar(surface)

    def _draw_health_bar(self, surface):
        if self.hp >= self.max_hp:
            return
        bar_width, bar_height = self.radius * 2, 4
        x = int(self.pos.x - self.radius)
        y = int(self.pos.y - self.radius - bar_height - 2)
        pygame.draw.rect(surface, (60, 20, 20), (x, y, bar_width, bar_height))
        fill_width = int(bar_width * (self.hp / self.max_hp))
        pygame.draw.rect(surface, (60, 200, 60), (x, y, fill_width, bar_height))


class GruntEnemy(Enemy):
    """The one enemy species shipped in v1 -- uses the base stats as-is."""
    pass


ENEMY_TYPES = {
    "grunt": GruntEnemy,
}
