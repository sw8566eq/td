"""Enemy base class, concrete species, and the ENEMY_TYPES registry.

Enemy carries all shared movement/HP/slow logic plus per-wave scaling, all
as overridable class attributes. Ships with six species -- GruntEnemy
(baseline), ScoutEnemy (fast/low-HP), TankEnemy (slow/high-HP), BossEnemy
(a level's one-off final-wave heavyweight), ShieldedEnemy (a regenerating
shield absorbs damage before HP does), FlyingEnemy (only a tower with
can_target_flying -- see tower.py -- can hit it) -- and a new one is
written the same way towers are: subclass Enemy, override stats (and
update()/take_damage() too, if it needs genuinely different behavior like a
shield), then add one line to ENEMY_TYPES. Levels reference enemies by
their registry name string in wave_specs (see levels.py), so WaveManager
never needs to know about concrete Enemy subclasses directly.
"""

import pygame

import settings


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

    # Whether a tower needs can_target_flying = True (see tower.py) to hit
    # this species at all -- False for every ground-bound enemy, True only
    # for FlyingEnemy below.
    is_flying = False

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

        # Damage-over-time state -- see apply_poison(). damage_per_tick/
        # tick_interval describe the currently-active poison (meaningless
        # while time_remaining is 0); tick_timer counts down to the next
        # actual damage application.
        self.poison_damage_per_tick = 0.0
        self.poison_tick_interval = 0.0
        self.poison_tick_timer = 0.0
        self.poison_time_remaining = 0.0

        self.knockback_remaining = 0.0  # px of backward slide still owed

        self.distance_traveled = 0.0
        self.is_dead = False
        self.reached_goal = False

        # Amounts actually applied by take_damage() since the last time
        # something drained this -- Game.update() turns each one into a
        # floating damage number at this enemy's current position, then
        # clears the list every frame. A plain list rather than a single
        # running total so multiple hits landing the same frame (a splash
        # hit, or several links of a chain) each get their own popup.
        self.damage_events = []

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

        if self.poison_time_remaining > 0:
            self.poison_time_remaining -= dt
            self.poison_tick_timer -= dt
            if self.poison_tick_timer <= 0:
                self.poison_tick_timer += self.poison_tick_interval
                self.take_damage(self.poison_damage_per_tick)
                if self.is_dead:
                    return  # a killing tick -- don't also move the corpse this frame
            if self.poison_time_remaining <= 0:
                self.poison_time_remaining = 0.0
                self.poison_damage_per_tick = 0.0

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
        # Also guard reached_goal, not just is_dead: every current caller
        # into this already excludes reached_goal enemies upstream (see
        # Projectile), so this is dormant today, but take_damage is a
        # normal public entry point (tests call it directly, and so could
        # a future hazard tile or damage-over-time effect) -- without
        # this, a direct call on an escaped enemy could flip is_dead to
        # True, and Game.update()'s alive-filter checks is_dead before
        # reached_goal, so it would award gold for an enemy that had
        # already cost a life instead.
        if self.is_dead or self.reached_goal:
            return 0.0
        self.damage_events.append(amount)
        self.hp -= amount
        if self.hp <= 0:
            self.hp = 0
            self.is_dead = True
        # Returns exactly `amount` here (an overkill hit still reports its
        # full nominal damage, not clamped to however much hp had left) --
        # a subclass that absorbs part of a hit before it ever reaches hp
        # (ShieldedEnemy's shield, BossEnemy's armor phase) is what makes
        # this genuinely differ from `amount`, by passing in the smaller,
        # already-reduced figure. Projectile._apply_hit_effects() credits
        # this return value, not the raw shot damage, to the firing
        # tower's lifetime damage_dealt stat.
        return amount

    def apply_slow(self, factor, duration):
        # Guards like take_damage/apply_knockback do -- a hit that kills
        # its target still runs the rest of _apply_hit_effects
        # (Projectile), so without this an already-dead enemy's
        # slow_timer/slow_multiplier still get mutated (harmless in
        # practice today, since a dead enemy's update() returns before
        # ever reading them, but not otherwise guaranteed and needlessly
        # inconsistent with its two siblings).
        if self.is_dead or self.reached_goal:
            return
        # Keep the stronger of current vs. new slow so repeated hits refresh
        # rather than weaken the effect.
        self.slow_multiplier = min(self.slow_multiplier, factor)
        self.slow_timer = max(self.slow_timer, duration)

    def apply_poison(self, damage_per_tick, tick_interval, duration):
        """Start (or refresh) a damage-over-time effect: damage_per_tick
        every tick_interval seconds, for duration seconds total -- see the
        per-frame handling in update(). Re-poisoning follows apply_slow's
        precedent, not apply_knockback's: keep the stronger tick and extend
        the duration, rather than stacking multiple concurrent DoT
        instances (which nothing here needs yet). Deliberately does NOT
        reset poison_tick_timer -- only a genuinely fresh application
        (nothing currently active) starts a new tick countdown; a re-hit
        while already poisoned strengthens/extends it without delaying
        whatever tick is already due."""
        if self.is_dead or self.reached_goal:
            return
        if self.poison_time_remaining <= 0:
            self.poison_tick_timer = 0.0  # first tick fires on the very next update()
        self.poison_damage_per_tick = max(self.poison_damage_per_tick, damage_per_tick)
        self.poison_tick_interval = tick_interval
        self.poison_time_remaining = max(self.poison_time_remaining, duration)

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
    """The baseline species -- uses Enemy's base stats as-is."""
    pass


class ScoutEnemy(Enemy):
    """Fast and fragile: dies to a couple of hits from almost anything, but
    covers ground quickly and can slip past towers with too little range or
    too slow a fire rate to catch it. Smaller sprite to read as "small and
    quick" at a glance. Also the most rewarding target for the knockback
    tower -- apply_knockback's distance scales with the enemy's own speed,
    so scouts get shoved back proportionally further than slower species."""
    base_hp = 18
    hp_per_wave = 4
    base_speed = 130.0
    speed_per_wave = 5.0
    max_speed = 220.0
    base_reward = 6
    reward_per_wave = 1
    sprite_name = "enemy_scout"
    radius = 12


class TankEnemy(Enemy):
    """Slow and heavily armored: high HP that takes sustained fire to bring
    down, but gives towers plenty of time to line up shots -- and frost's
    slow effect turns an already-slow tank into a near-standstill. Larger
    sprite and a bigger gold reward to match the threat and effort."""
    base_hp = 140
    hp_per_wave = 30
    base_speed = 30.0
    speed_per_wave = 1.5
    max_speed = 70.0
    base_reward = 20
    reward_per_wave = 4
    sprite_name = "enemy_tank"
    radius = 22


class BossEnemy(Enemy):
    """A one-off heavyweight meant for a level's final wave: dramatically
    more HP and gold reward than any regular species, moving at a
    deliberate, menacing crawl -- towers get plenty of time to line up
    shots, but need to have actually dealt real damage over the level to
    bring it down in time.

    Two self-contained, one-time mechanics kick in as its HP drops, same
    "override take_damage()/update(), guard is_dead/reached_goal first"
    shape as ShieldedEnemy's regenerating shield:

    - Enrage: past ENRAGE_HP_FRACTION of max_hp, permanently speeds up by
      ENRAGE_SPEED_MULTIPLIER (capped at max_speed like any other speed
      change) -- a boss that's taken serious damage gets more dangerous,
      not more docile.
    - Armor phase: past the lower ARMOR_HP_FRACTION, a one-time
      ARMOR_DURATION-second window where incoming damage is reduced by a
      flat ARMOR_FLAT_REDUCTION before it's applied (absorbed the same way
      ShieldedEnemy's shield eats damage before HP does), buying a last
      stretch of survival time right when it looks nearly dead.

    Both thresholds are checked against self.max_hp *at the moment of the
    check*, never a value cached in __init__ -- WaveManager._spawn_enemy
    multiplies max_hp/hp by the active difficulty's enemy_hp_multiplier
    *after* construction (see its own hasattr(enemy, "max_shield") patch-up
    for ShieldedEnemy, same reasoning), so a threshold computed at
    __init__ time would silently fire at the wrong HP on Easy/Hard."""
    base_hp = 500
    hp_per_wave = 50
    base_speed = 25.0
    speed_per_wave = 1.0
    max_speed = 50.0
    base_reward = 150
    reward_per_wave = 20
    sprite_name = "enemy_boss"
    radius = 30

    ENRAGE_HP_FRACTION = 0.5
    ENRAGE_SPEED_MULTIPLIER = 1.5
    ARMOR_HP_FRACTION = 0.2
    ARMOR_FLAT_REDUCTION = 15
    ARMOR_DURATION = 4.0

    def __init__(self, waypoints_px, wave_number):
        super().__init__(waypoints_px, wave_number)
        self.enraged = False
        self.armor_used = False
        self.armor_timer = 0.0

    def take_damage(self, amount):
        if self.is_dead or self.reached_goal:
            return 0.0
        if self.armor_timer > 0:
            amount = max(0.0, amount - self.ARMOR_FLAT_REDUCTION)
        applied = super().take_damage(amount)
        if self.is_dead:
            return applied  # a killing blow -- no mechanic left to trigger

        if not self.enraged and self.hp <= self.ENRAGE_HP_FRACTION * self.max_hp:
            self.enraged = True
            self.speed = min(self.speed * self.ENRAGE_SPEED_MULTIPLIER, self.max_speed)
        if not self.armor_used and self.hp <= self.ARMOR_HP_FRACTION * self.max_hp:
            self.armor_used = True
            self.armor_timer = self.ARMOR_DURATION
        return applied

    def update(self, dt):
        super().update(dt)
        if self.is_dead or self.reached_goal:
            return
        if self.armor_timer > 0:
            self.armor_timer = max(0.0, self.armor_timer - dt)

    def draw(self, surface, assets):
        super().draw(surface, assets)
        # A small cosmetic tell, same spirit as ShieldedEnemy's shield bar:
        # a ring while a damage-reduction window is active, tinted gold
        # once enraged so either state reads at a glance without needing
        # to watch the health bar's exact fraction.
        if self.armor_timer > 0 or self.enraged:
            color = settings.COLOR_GOLD if self.armor_timer > 0 else (220, 90, 40)
            center = (int(self.pos.x), int(self.pos.y))
            pygame.draw.circle(surface, color, center, self.radius + 4, width=2)


class ShieldedEnemy(Enemy):
    """A regenerating shield absorbs damage before HP does: take_damage()
    depletes the shield first and only spills any remainder into HP, and
    the shield itself regenerates once shield_regen_delay seconds pass
    without a hit landing. Damage-over-time (PoisonTower's ticks) counts as
    a hit like any other -- take_damage() doesn't care where the damage
    came from -- so a poisoned shield still has to burn down before the
    poison actually reaches HP, same as a direct hit would."""
    base_hp = 40
    hp_per_wave = 10
    base_shield = 30
    shield_per_wave = 6
    shield_regen_delay = 3.0  # seconds without taking damage before regen starts
    shield_regen_rate = 10.0  # shield points/sec once regenerating
    base_speed = 55.0
    speed_per_wave = 2.5
    max_speed = 110.0
    base_reward = 14
    reward_per_wave = 3
    sprite_name = "enemy_shielded"
    radius = 18

    def __init__(self, waypoints_px, wave_number):
        super().__init__(waypoints_px, wave_number)
        self.max_shield = self._scale(self.base_shield, self.shield_per_wave, wave_number)
        self.shield = self.max_shield
        self.time_since_hit = 0.0

    def take_damage(self, amount):
        if self.is_dead or self.reached_goal:
            return 0.0
        self.time_since_hit = 0.0
        if self.shield > 0:
            absorbed = min(self.shield, amount)
            self.shield -= absorbed
            amount -= absorbed
        if amount > 0:
            return super().take_damage(amount)
        return 0.0  # fully absorbed by the shield -- no real hp damage dealt

    def update(self, dt):
        super().update(dt)
        if self.is_dead or self.reached_goal:
            return
        if self.shield < self.max_shield:
            self.time_since_hit += dt
            if self.time_since_hit >= self.shield_regen_delay:
                self.shield = min(self.max_shield, self.shield + self.shield_regen_rate * dt)

    def draw(self, surface, assets):
        super().draw(surface, assets)
        self._draw_shield_bar(surface)

    def _draw_shield_bar(self, surface):
        if self.shield <= 0:
            return
        # Sits above where the health bar draws (_draw_health_bar) at a
        # fixed offset -- not conditional on whether the health bar is
        # currently shown (only true once hp < max_hp) -- so the two never
        # collide regardless of which one appears when.
        bar_width, bar_height = self.radius * 2, 3
        x = int(self.pos.x - self.radius)
        y = int(self.pos.y - self.radius - 4 - 2 - bar_height - 2)
        pygame.draw.rect(surface, (30, 40, 70), (x, y, bar_width, bar_height))
        fill_width = int(bar_width * (self.shield / self.max_shield))
        pygame.draw.rect(surface, (90, 160, 255), (x, y, fill_width, bar_height))


class FlyingEnemy(Enemy):
    """Airborne -- only a tower with can_target_flying = True (see
    tower.py; every current tower except Cannon and Knockback) can hit it
    at all, regardless of range/targeting mode. Fast and comparatively
    fragile, closer to Scout than Tank."""
    is_flying = True
    base_hp = 25
    hp_per_wave = 5
    base_speed = 100.0
    speed_per_wave = 4.0
    max_speed = 180.0
    base_reward = 12
    reward_per_wave = 2
    sprite_name = "enemy_flying"
    radius = 14


ENEMY_TYPES = {
    "grunt": GruntEnemy,
    "scout": ScoutEnemy,
    "tank": TankEnemy,
    "boss": BossEnemy,
    "shielded": ShieldedEnemy,
    "flying": FlyingEnemy,
}
