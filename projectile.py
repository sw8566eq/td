"""A single, data-parametrized Projectile class.

Splash-vs-single-target, slow-vs-no-slow, knockback-vs-no-knockback, and
chain-vs-no-chain are all differences in the data passed at construction
(fed by each Tower subclass's create_projectile()), not separate
Projectile subclasses -- the resolution algorithm is identical either way,
just applied to one enemy or many.

Splash and chain are the two exceptions to "freely combinable", though:
_resolve_hit() only ever reaches chain resolution on its no-splash branch,
so a shot with both splash_radius and chain_range set gets splash only --
untested and unused by any current TOWER_TYPES entry, and not something
to combine casually (a splash hit already hits every enemy in the blast
radius by iterating `enemies` directly, so chaining "from" that impact
raises its own questions about who counts as already-hit that a single-
target chain doesn't have to answer).
"""

import pygame


class Projectile:
    def __init__(self, pos, target, speed, damage, splash_radius=0, slow_effect=None,
                 knockback_duration=0.0, chain_range=0.0, max_chain_targets=1, sprite_name=""):
        self.pos = pygame.Vector2(pos)
        self.target = target
        self.speed = speed
        self.damage = damage
        self.splash_radius = splash_radius
        self.slow_effect = slow_effect  # (factor, duration) or None
        # Seconds of forward path progress to undo on hit, at the enemy's
        # speed at the moment of impact -- 0 means no knockback.
        self.knockback_duration = knockback_duration
        # Max distance between consecutive links in the chain, and the
        # total number of enemies one shot can hit (including the first) --
        # chain_range 0 means no chaining, single-target only.
        self.chain_range = chain_range
        self.max_chain_targets = max_chain_targets
        self.sprite_name = sprite_name
        self.dead = False

    def update(self, dt, enemies):
        if self.dead:
            return

        if self.target.is_dead or self.target.reached_goal:
            # Target died, or reached the goal, before impact -- discard
            # as a dud rather than retargeting (a deliberate MVP
            # simplification). Without the reached_goal check, a shot
            # already in flight when its target reaches the goal would
            # still connect: reached_goal enemies stop moving (see
            # Enemy.update) but stay in memory as long as something still
            # references them, so the projectile would keep homing in on
            # wherever they stopped and "hit" an enemy that's already
            # left the level.
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
                if enemy.is_dead or enemy.reached_goal:
                    continue
                if impact_pos.distance_to(enemy.pos) <= self.splash_radius:
                    self._apply_hit_effects(enemy)
        else:
            self._apply_hit_effects(self.target)
            if self.chain_range > 0:
                self._resolve_chain(enemies)

    def _resolve_chain(self, enemies):
        """From the just-hit enemy, hop to the nearest enemy this shot
        hasn't already hit that's within chain_range, apply the same hit
        effects, and repeat from there -- up to max_chain_targets enemies
        total (including the first) or until no such enemy is left in
        range. This is Lightning's signature mechanic: each link only
        ever reaches out from wherever the bolt currently is, and never
        arcs back to something it's already hit."""
        hit = {self.target}
        current = self.target
        while len(hit) < self.max_chain_targets:
            next_target = None
            next_distance = None
            for enemy in enemies:
                if enemy.is_dead or enemy.reached_goal or enemy in hit:
                    continue
                distance = current.pos.distance_to(enemy.pos)
                if distance <= self.chain_range and (next_target is None or distance < next_distance):
                    next_target = enemy
                    next_distance = distance
            if next_target is None:
                break
            self._apply_hit_effects(next_target)
            hit.add(next_target)
            current = next_target

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
