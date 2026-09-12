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

_apply_hit_effects also resolves several more relic-driven, per-enemy
checks, each read straight off the enemy being hit (via getattr with a
neutral default, so a lightweight test double missing the attribute is
unaffected): Chilling Precision (relic_damage_vs_slowed_multiplier,
gated on enemy.slow_timer > 0 -- read *before* this same hit's own slow
application below, so a Frost tower's first-ever hit on a target never
retroactively counts itself as "vs. a slowed enemy"), Choke Point
(relic_damage_vs_early_route_multiplier, gated on enemy.distance_traveled
< CHOKE_POINT_DISTANCE_THRESHOLD), Giant Slayer
(relic_damage_vs_high_hp_multiplier, gated on enemy.max_hp >
GIANT_SLAYER_HP_THRESHOLD), Aftershock (relic_slow_chance/
relic_slow_effect, same chance-gated shape as the existing poison/chain
relic rolls, just calling enemy.apply_slow()), and Overkill
(relic_overkill_carry_fraction, checked after the hit resolves: any
damage beyond what was needed to kill carries to the nearest other enemy
within OVERKILL_CARRY_RANGE via _find_chain_target/_apply_direct_damage,
the same non-recursive single hop Arcing Rounds' own bounce already
uses). CHOKE_POINT_DISTANCE_THRESHOLD/GIANT_SLAYER_HP_THRESHOLD/
OVERKILL_CARRY_RANGE are plain module constants here, not Relic fields --
relics.py has no import dependency on tower.py/projectile.py, and every
existing per-mechanic constant already lives beside the mechanic that
consumes it.

mark_effect (a Beacon-style tower's own field, not relic-driven -- see
tower.BeaconTower) is a (damage_multiplier, duration) pair applied via
enemy.apply_mark(), the same shape as slow_effect/poison_effect above.

A later relic batch filled in the remaining gaps in this same "tower's
own field, separate relic-chance-rolled field" pattern: relic_knockback_
chance/relic_knockback_effect and relic_mark_chance/relic_mark_effect
follow slow/poison's exact chance-gated shape, just calling enemy.
apply_knockback()/apply_mark() instead. relic_damage_vs_flying_
multiplier/relic_damage_vs_shielded_multiplier/relic_damage_vs_healer_
multiplier join the ungated Chilling Precision/Choke Point/Giant Slayer
block, checked against the target's own current is_flying/shield/
heal_rate state (duck-typed via getattr, not a species check) rather than
max_hp or route progress -- each guarded on its own relic_* field being
non-neutral first, same as every check in that block, so a run holding
neither relic never even attempts the shield/heal_rate getattr (neither
is a base Enemy attribute, unlike is_flying, so an ungated attempt would
hit Python's slower missing-attribute path on every hit against every
other species).

A Containment Charges-style relic's own flat per-child damage is
deliberately NOT handled here, unlike every mechanism above -- it has no
per-tower or per-shot variation to justify threading it through Tower/
Projectile at all, so Game.update()'s own dead-enemy drain loop applies
it directly from self.relic_modifiers, the one place enemy.pending_spawns
is ever read to begin with.

crit_chance/crit_damage_multiplier (BasicTower's own native crit) and
execute_hp_threshold/execute_damage_multiplier (SniperTower's own native
Execute, an ungated bonus once a target's remaining HP fraction drops at
or below the threshold) are two more tower-driven, not relic-driven,
per-enemy effects -- the exact same "tower's own field, separate from the
relic's own version of a similar idea" split slow_effect/poison_effect
already establish against relic_slow_effect/relic_poison_effect. Execute
joins the ungated Chilling Precision/Choke Point/Giant Slayer block since
it never rolls; the crit roll is resolved immediately before relic_crit_
chance's own roll, same "tower's own effect first" ordering.
"""

import random

import pygame

# Choke Point's own cutoff: an enemy with less than this much path
# distance behind it counts as "early in its route." Giant Slayer's own
# cutoff matches its relic text ("more than 100 max HP") exactly, so
# there's nothing to tune independently of the relic description itself.
# Overkill's own search radius for a carry-over bounce target, the same
# idea as arcing_rounds' own chain_range but a separate constant since the
# two mechanisms are otherwise unrelated.
CHOKE_POINT_DISTANCE_THRESHOLD = 200
GIANT_SLAYER_HP_THRESHOLD = 100
OVERKILL_CARRY_RANGE = 90


class Projectile:
    def __init__(self, pos, target, speed, damage, splash_radius=0, slow_effect=None,
                 knockback_duration=0.0, chain_range=0.0, max_chain_targets=1,
                 poison_effect=None, sprite_name="", source=None,
                 relic_poison_chance=0.0, relic_poison_effect=None,
                 relic_crit_chance=0.0, relic_crit_damage_multiplier=1.0,
                 relic_chain_chance=0.0, relic_chain_effect=None,
                 mark_effect=None, relic_damage_vs_slowed_multiplier=1.0,
                 relic_slow_chance=0.0, relic_slow_effect=None,
                 relic_poison_ignores_shield=False,
                 relic_damage_vs_early_route_multiplier=1.0,
                 relic_damage_vs_high_hp_multiplier=1.0,
                 relic_overkill_carry_fraction=0.0,
                 relic_knockback_chance=0.0, relic_knockback_effect=None,
                 relic_mark_chance=0.0, relic_mark_effect=None,
                 relic_damage_vs_flying_multiplier=1.0,
                 relic_damage_vs_shielded_multiplier=1.0,
                 relic_damage_vs_healer_multiplier=1.0,
                 crit_chance=0.0, crit_damage_multiplier=1.0,
                 execute_hp_threshold=0.0, execute_damage_multiplier=1.0):
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
        # A Beacon-style tower's own mark -- (damage_multiplier, duration)
        # or None, same shape as slow_effect/poison_effect above (this
        # tower's own always-on hit effect, not a relic-driven chance
        # roll). See enemy.apply_mark().
        self.mark_effect = mark_effect
        # The remaining relic-driven fields below all follow the exact
        # same "neutral default, copied from a firing tower's own relic_*
        # attribute by Tower.update()" shape as relic_poison_chance etc.
        # above -- see relics.py's own field-by-field docstring for what
        # each relic actually grants, and this module's own docstring for
        # where each is checked in _apply_hit_effects.
        self.relic_damage_vs_slowed_multiplier = relic_damage_vs_slowed_multiplier
        self.relic_slow_chance = relic_slow_chance
        self.relic_slow_effect = relic_slow_effect
        self.relic_poison_ignores_shield = relic_poison_ignores_shield
        self.relic_damage_vs_early_route_multiplier = relic_damage_vs_early_route_multiplier
        self.relic_damage_vs_high_hp_multiplier = relic_damage_vs_high_hp_multiplier
        self.relic_overkill_carry_fraction = relic_overkill_carry_fraction
        # Concussive Rounds/Disorienting Flash-style relics -- same
        # chance-gated shape as relic_poison_chance/relic_slow_chance
        # above, triggering enemy.apply_knockback()/apply_mark() instead.
        self.relic_knockback_chance = relic_knockback_chance
        self.relic_knockback_effect = relic_knockback_effect
        self.relic_mark_chance = relic_mark_chance
        self.relic_mark_effect = relic_mark_effect
        # Flak Rounds/Breach Charges/Suppression Directive-style relics --
        # ungated multiplies, same shape as relic_damage_vs_slowed_
        # multiplier above, checked against the target's own current
        # is_flying/shield/heal_rate state.
        self.relic_damage_vs_flying_multiplier = relic_damage_vs_flying_multiplier
        self.relic_damage_vs_shielded_multiplier = relic_damage_vs_shielded_multiplier
        self.relic_damage_vs_healer_multiplier = relic_damage_vs_healer_multiplier
        # BasicTower's own native crit mechanic -- tower-driven, not relic-
        # driven, so kept as its own pair rather than folded into relic_
        # crit_chance/relic_crit_damage_multiplier above (the exact same
        # "tower's own field, separate from the relic's own version of a
        # similar idea" split slow_effect/relic_slow_effect and poison_
        # effect/relic_poison_effect already establish). Neutral defaults
        # mean every other tower's projectiles never roll this at all.
        self.crit_chance = crit_chance
        self.crit_damage_multiplier = crit_damage_multiplier
        # SniperTower's own native "Execute" mechanic -- bonus damage
        # against a target already below execute_hp_threshold of its own
        # max_hp. Ungated (no chance roll), so it joins the other ungated
        # per-enemy multipliers in _apply_hit_effects rather than the
        # chance-rolled block below them.
        self.execute_hp_threshold = execute_hp_threshold
        self.execute_damage_multiplier = execute_damage_multiplier
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
        # Chilling Precision/Choke Point/Giant Slayer -- ungated, per-enemy
        # damage multipliers, each read straight off the enemy being hit
        # (getattr with a neutral default, so a lightweight test double
        # missing the attribute is unaffected -- see this module's own
        # docstring). Chilling Precision's slow_timer check MUST happen
        # before this same hit's own slow application further below, or a
        # Frost tower's first-ever hit on a target would retroactively
        # count itself as "vs. a slowed enemy."
        damage = self.damage
        if getattr(enemy, "slow_timer", 0.0) > 0:
            damage *= self.relic_damage_vs_slowed_multiplier
        if getattr(enemy, "distance_traveled", 0.0) < CHOKE_POINT_DISTANCE_THRESHOLD:
            damage *= self.relic_damage_vs_early_route_multiplier
        if getattr(enemy, "max_hp", 0.0) > GIANT_SLAYER_HP_THRESHOLD:
            damage *= self.relic_damage_vs_high_hp_multiplier
        # Flak Rounds/Breach Charges/Suppression Directive -- three more
        # ungated per-enemy multipliers, same shape as the three just
        # above, checked against the target's own *current* is_flying/
        # shield/heal_rate state (duck-typed via getattr, not a species
        # check) rather than max_hp/route-progress. Unlike is_flying (a
        # base Enemy attribute, always present), shield/heal_rate only
        # exist on ShieldedEnemy/HealerEnemy instances -- guarded on the
        # relic's own multiplier being non-neutral first, so a run that
        # doesn't hold Breach Charges/Suppression Directive never even
        # attempts the getattr against every other species (a plain
        # attribute lookup is cheap; one that has to fall through to a
        # missing-attribute default on every hit, for the common no-relic
        # case, isn't worth paying unconditionally).
        if getattr(enemy, "is_flying", False):
            damage *= self.relic_damage_vs_flying_multiplier
        if self.relic_damage_vs_shielded_multiplier != 1.0 and getattr(enemy, "shield", 0) > 0:
            damage *= self.relic_damage_vs_shielded_multiplier
        if self.relic_damage_vs_healer_multiplier != 1.0 and getattr(enemy, "heal_rate", 0) > 0:
            damage *= self.relic_damage_vs_healer_multiplier
        # hp_before, hoisted up from beside Overkill's own check further
        # below (see its comment there for the full rationale) since
        # Execute needs the same pre-hit hp reading -- both reads happen
        # before _apply_direct_damage changes anything, so sharing one
        # getattr() here is a pure reuse, not a behavior change.
        hp_before = getattr(enemy, "hp", 0.0)
        # SniperTower's own Execute mechanic -- bonus damage once the
        # target's own remaining HP fraction drops at/below
        # execute_hp_threshold. Distinct from Giant Slayer's max_hp check
        # just above (that one's about a species' raw toughness; this one's
        # about how close *this* enemy already is to dying) and from
        # Overkill's own post-hit carry-to-a-neighbor mechanic further
        # below (this fires before the hit, Overkill after). Guarded on
        # execute_damage_multiplier != 1.0 first -- same "cheap guard
        # before the real check" shape the crit roll just below uses
        # (guarded on crit_chance before ever calling random()) -- so a
        # non-Sniper tower's hit never even reads max_hp.
        if self.execute_damage_multiplier != 1.0:
            max_hp = getattr(enemy, "max_hp", 0.0)
            if max_hp and hp_before <= max_hp * self.execute_hp_threshold:
                damage *= self.execute_damage_multiplier
        # BasicTower's own native crit roll -- same "once per enemy this
        # projectile actually hits" shape as the relic crit roll just
        # below, and deliberately resolved first (tower's own effect, then
        # the relic's own version of a similar idea), mirroring poison_
        # effect/slow_effect's own ordering against their relic equivalents.
        if self.crit_chance and random.random() < self.crit_chance:
            damage *= self.crit_damage_multiplier
        # A Lucky Strikes-style relic's crit roll happens here, once per
        # enemy this projectile actually hits (see this method's own call
        # sites -- once for a direct hit, once per enemy in a splash
        # blast, once per chain link) -- damage stays a local, not
        # self.damage, so a splash/chain shot's later hits each get their
        # own independent roll rather than one roll deciding the whole
        # shot. Guarded on relic_crit_chance being truthy so a relic-less
        # run's projectiles never call random.random() at all.
        if self.relic_crit_chance and random.random() < self.relic_crit_chance:
            damage *= self.relic_crit_damage_multiplier
        # hp_before (captured above, alongside Execute's own read of it) and
        # applied are used for Overkill's own check, below -- applied is
        # the amount that actually reached hp (not necessarily the nominal
        # `damage` above, once a shield/armor phase absorbs part of it --
        # see Enemy.take_damage's own docstring), so `applied > hp_before`
        # is exactly "this hit killed with room to spare." A lightweight
        # test double that doesn't track hp at all reads hp_before as 0.0
        # (getattr's own default) -- meaningless there since relic_
        # overkill_carry_fraction defaults to 0.0, short-circuiting the
        # check below before hp_before is ever used.
        applied = self._apply_direct_damage(enemy, damage)
        if self.slow_effect is not None:
            enemy.apply_slow(*self.slow_effect)
        # An Aftershock-style relic's slow roll -- same "once per enemy
        # actually hit, independent of the tower's own slow_effect above"
        # shape as the poison/chain relic rolls below. apply_slow()'s own
        # min()/max() refresh semantics mean a successful roll here on an
        # already-slowed target just keeps the stronger of the two.
        if (
            self.relic_slow_chance and self.relic_slow_effect is not None
            and random.random() < self.relic_slow_chance
        ):
            enemy.apply_slow(*self.relic_slow_effect)
        # A Beacon-style tower's own mark -- see enemy.apply_mark().
        if self.mark_effect is not None:
            enemy.apply_mark(*self.mark_effect)
        # A Disorienting Flash-style relic's mark roll -- same "once per
        # enemy actually hit, independent of the tower's own mark_effect
        # above" shape as the slow/poison relic rolls elsewhere in this
        # method. Enemy.apply_mark()'s own max()/max() refresh semantics
        # mean a successful roll here on a hit that's ALSO already marked
        # (e.g. from BeaconTower itself) just keeps the stronger of the
        # two.
        if (
            self.relic_mark_chance and self.relic_mark_effect is not None
            and random.random() < self.relic_mark_chance
        ):
            enemy.apply_mark(*self.relic_mark_effect)
        if self.knockback_duration:
            enemy.apply_knockback(enemy.speed * self.knockback_duration)
        # A Concussive Rounds-style relic's knockback roll -- same "once
        # per enemy actually hit, independent of the tower's own
        # knockback_duration above" shape. Converted to a pixel distance
        # the same way the tower-driven knockback just above already is.
        if (
            self.relic_knockback_chance and self.relic_knockback_effect is not None
            and random.random() < self.relic_knockback_chance
        ):
            enemy.apply_knockback(enemy.speed * self.relic_knockback_effect)
        # relic_poison_ignores_shield (a Corrosive Poison-style relic)
        # threads through to Enemy.take_poison_damage() via apply_poison()
        # either way -- a tower's own poison_effect and a Venomous
        # Coating-style relic roll alike, since neither poison source
        # should behave differently against a shield once the relic is
        # held.
        if self.poison_effect is not None:
            enemy.apply_poison(*self.poison_effect, ignore_shield=self.relic_poison_ignores_shield)
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
            enemy.apply_poison(*self.relic_poison_effect, ignore_shield=self.relic_poison_ignores_shield)
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
        # An Overkill-style relic's carry-over -- any damage beyond what
        # was needed to kill `enemy` hops to the nearest other enemy
        # within OVERKILL_CARRY_RANGE, at relic_overkill_carry_fraction
        # strength. Same non-recursive single-hop shape as the chain
        # bounce immediately above, deliberately not a full
        # _apply_hit_effects() call for the same reasons that one isn't.
        if self.relic_overkill_carry_fraction and applied > hp_before:
            overkill_target = self._find_chain_target(enemy, {enemy}, OVERKILL_CARRY_RANGE, enemies)
            if overkill_target is not None:
                self._apply_direct_damage(
                    overkill_target, (applied - hp_before) * self.relic_overkill_carry_fraction
                )

    def draw(self, surface, assets):
        size = (12, 12)
        sprite = assets.get(self.sprite_name, size)
        rect = sprite.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        surface.blit(sprite, rect)
