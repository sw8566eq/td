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

An Arcing Rounds-style relic's chain bounce (relic_chain_chance/
relic_chain_effect) is a separate, independent mechanism from the
tower-driven chain_range/max_chain_targets above -- it fires on ANY hit
(splash included) via a chance roll in _apply_hit_effects, and is always
exactly one non-recursive bounce via _apply_direct_damage, never a
multi-link chain. See _find_chain_target for the nearest-unvisited-enemy
lookup both mechanisms share.
"""

import random

import pygame


class Projectile:
    def __init__(self, pos, target, speed, damage, splash_radius=0, slow_effect=None,
                 knockback_duration=0.0, chain_range=0.0, max_chain_targets=1,
                 poison_effect=None, sprite_name="", source=None,
                 relic_poison_chance=0.0, relic_poison_effect=None,
                 relic_crit_chance=0.0, relic_crit_damage_multiplier=1.0,
                 relic_chain_chance=0.0, relic_chain_effect=None):
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
        # Relic-driven, chance-based hit effects (see Tower.update(), the
        # one place that copies these from a firing tower's own relic_*
        # attributes onto its projectile) -- neutral defaults (0.0/None/
        # 1.0) here so a projectile built directly (every existing test,
        # a relic-less run) never rolls at all, and applying independently
        # of poison_effect/self.damage above: this is what actually lets
        # a poison OR crit relic reach every tower's own attacks, not just
        # the one tower type each mechanic was originally built for.
        self.relic_poison_chance = relic_poison_chance
        self.relic_poison_effect = relic_poison_effect
        self.relic_crit_chance = relic_crit_chance
        self.relic_crit_damage_multiplier = relic_crit_damage_multiplier
        # An Arcing Rounds-style relic's own bonus hit -- (damage_fraction,
        # chain_range) or None. Independent of self.chain_range/
        # max_chain_targets above (Lightning's own signature mechanic):
        # this fires on ANY hit, splash or single-target alike, and is a
        # single non-recursive bounce, not a multi-link chain -- see
        # _apply_hit_effects/_apply_direct_damage.
        self.relic_chain_chance = relic_chain_chance
        self.relic_chain_effect = relic_chain_effect
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
                    self._apply_hit_effects(enemy, enemies)
                    hit_anything = True
        else:
            self._apply_hit_effects(self.target, enemies)
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
            next_target = self._find_chain_target(current, hit, self.chain_range, enemies)
            if next_target is None:
                break
            self._apply_hit_effects(next_target, enemies)
            hit.add(next_target)
            current = next_target

    def _find_chain_target(self, current, excluded, chain_range, enemies):
        """Nearest live, not-yet-`excluded` enemy within `chain_range` of
        `current`, or None -- the nearest-unvisited-hop lookup shared by
        _resolve_chain()'s own multi-link chain above and an Arcing
        Rounds-style relic's single bonus hit (_apply_hit_effects
        below)."""
        next_target = None
        next_distance = None
        for enemy in enemies:
            if enemy.is_dead or enemy.reached_goal or enemy in excluded:
                continue
            distance = current.pos.distance_to(enemy.pos)
            if distance <= chain_range and (next_target is None or distance < next_distance):
                next_target = enemy
                next_distance = distance
        return next_target

    def _apply_direct_damage(self, enemy, amount):
        """Apply `amount` to `enemy` and attribute it back to self.source
        (damage_dealt/kills) -- no crit/poison/chain rolls of its own,
        just the damage-and-bookkeeping core every hit needs. Shared by
        _apply_hit_effects below (which layers crit/slow/knockback/
        poison/chain around this for the projectile's own primary hit)
        and an Arcing Rounds-style relic's bonus bounce (which uses only
        this, deliberately not a second full _apply_hit_effects() call --
        a single, simple, damage-only jump rather than a full second
        application of every hit effect. Keeping it non-recursive means
        the bounce needs no recursion guard and can never cascade)."""
        was_alive = not enemy.is_dead
        # take_damage() returns however much of `amount` actually reached
        # hp -- usually all of it, but a shielded or armored enemy
        # (ShieldedEnemy/BossEnemy) can absorb part of a hit first, and
        # damage_dealt should reflect what was really done, not the full
        # nominal amount regardless of what landed.
        applied = enemy.take_damage(amount)
        if self.source is not None:
            self.source.damage_dealt += applied
            if was_alive and enemy.is_dead:
                self.source.kills += 1
        return applied

    def _apply_hit_effects(self, enemy, enemies):
        # A Lucky Strikes-style relic's crit roll happens here, once per
        # enemy this projectile actually hits (see this method's own call
        # sites -- once for a direct hit, once per enemy in a splash
        # blast, once per chain link) -- damage stays a local, not
        # self.damage, so a splash/chain shot's later hits each get their
        # own independent roll rather than one roll deciding the whole
        # shot. Guarded on relic_crit_chance being truthy so a relic-less
        # run's projectiles never call random.random() at all.
        damage = self.damage
        if self.relic_crit_chance and random.random() < self.relic_crit_chance:
            damage *= self.relic_crit_damage_multiplier
        self._apply_direct_damage(enemy, damage)
        if self.slow_effect is not None:
            enemy.apply_slow(*self.slow_effect)
        if self.knockback_duration:
            enemy.apply_knockback(enemy.speed * self.knockback_duration)
        if self.poison_effect is not None:
            enemy.apply_poison(*self.poison_effect)
        # A Venomous Coating-style relic's poison roll -- same "once per
        # enemy actually hit, independent of the tower's own poison_effect
        # above" shape as the crit roll. Enemy.apply_poison()'s own
        # max()/max()/last-write semantics mean a successful roll here on
        # a hit that's ALSO already poisoning (e.g. from PoisonTower
        # itself) just refreshes/strengthens the stronger of the two,
        # never stacks a second concurrent DoT. The explicit `is not None`
        # guard (mirroring poison_effect's own check above) matters here:
        # relic_poison_chance/relic_poison_effect are always set together
        # by Game._construct_tower/Tower.update(), but nothing local
        # enforces that pairing, so a projectile built with a chance but
        # no effect (a test double, a future call site) fails the roll
        # instead of crashing on `*None`.
        if (
            self.relic_poison_chance and self.relic_poison_effect is not None
            and random.random() < self.relic_poison_chance
        ):
            enemy.apply_poison(*self.relic_poison_effect)
        # An Arcing Rounds-style relic's chain roll -- same "once per enemy
        # actually hit" shape as crit/poison above, but the resulting
        # bounce is a plain _apply_direct_damage() call, not a recursive
        # _apply_hit_effects() -- see that method's own docstring for why
        # (no re-rolling crit/poison/another bounce on the bounced-to
        # enemy, and no recursion guard needed). Uses the local `damage`
        # value above (post-crit-roll), so a crit'd hit's bounce is
        # proportionally stronger too -- a minor, deliberate synergy.
        if (
            self.relic_chain_chance and self.relic_chain_effect is not None
            and random.random() < self.relic_chain_chance
        ):
            damage_fraction, chain_range = self.relic_chain_effect
            bounce_target = self._find_chain_target(enemy, {enemy}, chain_range, enemies)
            if bounce_target is not None:
                self._apply_direct_damage(bounce_target, damage * damage_fraction)

    def draw(self, surface, assets):
        size = (12, 12)
        sprite = assets.get(self.sprite_name, size)
        rect = sprite.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        surface.blit(sprite, rect)
