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
        """Push this enemy backward along its path by `distance` pixels.

        No angle/physics involved -- knockback just rewinds path progress
        (distance_traveled) and re-derives position/waypoint-index from
        that, which works the same regardless of which way the enemy is
        currently facing or how many turns the path has.
        """
        if self.is_dead or self.reached_goal or distance <= 0:
            return
        self._seek_to_distance(max(0.0, self.distance_traveled - distance))

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
