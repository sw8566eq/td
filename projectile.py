"""A single, data-parametrized Projectile class.

Splash-vs-single-target, slow-vs-no-slow, knockback-vs-no-knockback,
chain-vs-no-chain, and poison-vs-no-poison are all differences in the data
passed at construction (fed by each Tower subclass's create_projectile()),
not separate Projectile subclasses -- the resolution algorithm is identical
either way, just applied to one enemy or many.

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
                 knockback_duration=0.0, chain_range=0.0, max_chain_targets=1,
                 poison_effect=None, sprite_name="", source=None):
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
        # (damage_per_tick, tick_interval, duration) or None -- same shape
        # as slow_effect, just handed to enemy.apply_poison() instead.
        self.poison_effect = poison_effect
        self.sprite_name = sprite_name
        # The Tower that fired this shot, or None -- purely inert data (never
        # read by movement/collision math above), used only to attribute
        # damage_dealt/shots_hit/kills back to it for the post-level results
        # screen (see _resolve_hit/_apply_hit_effects and ui.compute_tower_
        # results). None for a projectile built without a real tower behind
        # it (e.g. a test double).
        self.source = source
        self.dead = False

        # (impact_pos, splash_radius_or_None) tuples -- one appended per
        # resolved hit (see _resolve_hit), regardless of whether it was a
        # splash/chain/single-target shot, same "once per projectile, not
        # once per enemy touched" counting shots_hit already uses below.
        # Game.update() drains this every frame into effects.ExpandingRing
        # instances, same drain-a-per-frame-event-list idiom Enemy.
        # damage_events already established for floating damage numbers.
        self.impact_events = []

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
        # Recorded once per projectile resolving, before hit_anything is
        # even known -- an impact flash reads as "this is where/how big the
        # blast was," not "this actually connected," so it fires the same
        # whether or not any enemy was still there to be hit.
        self.impact_events.append((pygame.Vector2(impact_pos), self.splash_radius or None))

        hit_anything = False
        if self.splash_radius > 0:
            for enemy in enemies:
                if enemy.is_dead or enemy.reached_goal:
                    continue
                if impact_pos.distance_to(enemy.pos) <= self.splash_radius:
                    self._apply_hit_effects(enemy)
                    hit_anything = True
        else:
            self._apply_hit_effects(self.target)
            hit_anything = True
            if self.chain_range > 0:
                self._resolve_chain(enemies)
        # Counted once per projectile, not per enemy actually touched --
        # see _apply_hit_effects for the cumulative per-enemy totals -- so
        # shots_hit / shots_fired never exceeds 1.0 even for a splash/chain
        # shot that connects with several enemies at once.
        if self.source is not None and hit_anything:
            self.source.shots_hit += 1

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
        was_alive = not enemy.is_dead
        # take_damage() returns however much of self.damage actually
        # reached hp -- usually all of it, but a shielded or armored
        # enemy (ShieldedEnemy/BossEnemy) can absorb part of a hit first,
        # and damage_dealt should reflect what was really done, not the
        # full nominal shot damage regardless of what landed.
        applied = enemy.take_damage(self.damage)
        if self.source is not None:
            self.source.damage_dealt += applied
            if was_alive and enemy.is_dead:
                self.source.kills += 1
        if self.slow_effect is not None:
            enemy.apply_slow(*self.slow_effect)
        if self.knockback_duration:
            enemy.apply_knockback(enemy.speed * self.knockback_duration)
        if self.poison_effect is not None:
            enemy.apply_poison(*self.poison_effect)

    def draw(self, surface, assets):
        size = (12, 12)
        sprite = assets.get(self.sprite_name, size)
        rect = sprite.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        surface.blit(sprite, rect)
