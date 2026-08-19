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


def _format_px(value):
    return f"{value:.0f}px"


def _format_seconds(value):
    return f"{value:.2f}s"


def _format_slow_percent(value):
    return f"{round((1 - value) * 100)}% slower"


def _format_count(value):
    return "Unlimited" if value == float("inf") else f"{int(value)}"


class Tower:
    cost = 0
    range = 0
    damage = 0
    fire_rate = 1.0  # shots per second
    projectile_speed = 300.0
    sprite_name = ""
    display_name = "Tower"

    MAX_LEVEL = 3
    # Default multiplier applied to a LEVEL_SCALED_STATS entry at a given
    # level -- level 1 is always 1.0x (no bonus, the placed/base stats).
    LEVEL_STAT_MULTIPLIERS = {1: 1.0, 2: 1.35, 3: 1.8}
    # Per-stat overrides of the above, e.g. {"damage": {1: 1.0, 2: 1.7,
    # 3: 2.6}} -- a stat not listed here just uses LEVEL_STAT_MULTIPLIERS
    # like normal. Lets one stat scale on its own curve (a tower that
    # should hit dramatically harder at max level without also reaching
    # dramatically further, say) without a whole separate mechanism.
    LEVEL_STAT_MULTIPLIER_OVERRIDES = {}
    # Which of a tower's own attributes get a level multiplier at all on
    # level-up. A subclass can extend this tuple (e.g. + ("slow_duration",))
    # to have more of its own stats scale too -- everything else about
    # levelling stays generic.
    LEVEL_SCALED_STATS = ("damage", "range")
    # Gold cost to reach level 2 / level 3, as a multiplier of this
    # tower's base `cost`.
    UPGRADE_COST_MULTIPLIERS = {2: 0.6, 3: 1.0}
    # Extra, tower-specific stats shown in the stats panel (ui.py), as
    # (label, attribute_name, format_function) tuples. Empty by default;
    # a subclass with a special mechanic (splash, slow, knockback, ...)
    # lists it here and the panel picks it up automatically.
    EXTRA_STATS = ()

    # Once a tower reaches MAX_LEVEL, it can choose one of two named
    # specializations instead of continuing to level up -- a one-time
    # branching choice, not another step of the generic LEVEL_SCALED_STATS
    # curve. Keyed by an arbitrary string id; "stat_multipliers" is
    # applied the same way a level-up's multiplier is (current value *=
    # multiplier). Every tower shares these two generic placeholders for
    # now -- effects/costs/names are meant to be tuned (or made
    # tower-specific, by overriding this in a subclass) once the choose-
    # and-apply mechanism itself is confirmed working.
    SPECIALIZATIONS = {
        "power": {
            "display_name": "Power",
            "description": "Bigger numbers.",
            "stat_multipliers": {"damage": 1.3},
        },
        "precision": {
            "display_name": "Precision",
            "description": "+Range and fire rate.",
            "stat_multipliers": {"range": 1.2, "fire_rate": 1.2},
        },
    }
    # Gold cost to specialize, as a multiplier of this tower's base `cost`
    # -- same idea as UPGRADE_COST_MULTIPLIERS.
    SPECIALIZATION_COST_MULTIPLIER = 1.5

    def __init__(self, anchor_col, anchor_row, pixel_pos):
        self.anchor_col = anchor_col
        self.anchor_row = anchor_row
        self.pos = pygame.Vector2(pixel_pos)
        self.cooldown = 0.0
        self.level = 1
        # Snapshot each scaled stat's level-1 value once, up front, so
        # every upgrade recomputes from the true base rather than
        # compounding on an already-scaled number.
        self._base_stats = {name: getattr(self, name) for name in self.LEVEL_SCALED_STATS}
        # Total gold spent placing and upgrading this tower -- what a sale
        # refunds a fraction of, so upgrading then selling isn't a loss on
        # top of the upgrade itself. See sell_value().
        self.total_invested = self.cost
        # SPECIALIZATIONS key once chosen (see specialize()), else None.
        self.specialization = None

    @property
    def is_max_level(self):
        return self.level >= self.MAX_LEVEL

    def upgrade_cost(self):
        """Gold cost to reach the next level, or None if already maxed."""
        if self.is_max_level:
            return None
        return round(self.cost * self.UPGRADE_COST_MULTIPLIERS[self.level + 1])

    def _multiplier_table_for(self, name):
        """The level->multiplier table that applies to stat `name` -- its
        own override table if LEVEL_STAT_MULTIPLIER_OVERRIDES has one,
        otherwise the shared default LEVEL_STAT_MULTIPLIERS."""
        return self.LEVEL_STAT_MULTIPLIER_OVERRIDES.get(name, self.LEVEL_STAT_MULTIPLIERS)

    def upgrade(self):
        """Level up by one, rescaling every LEVEL_SCALED_STATS entry from
        its level-1 base. No-op (returns False) once at MAX_LEVEL."""
        if self.is_max_level:
            return False
        self.total_invested += self.upgrade_cost()
        self.level += 1
        for name, base_value in self._base_stats.items():
            multiplier = self._multiplier_table_for(name)[self.level]
            setattr(self, name, base_value * multiplier)
        return True

    def sell_value(self):
        """Gold refunded if this tower is sold right now -- a fraction
        (settings.SELL_REFUND_FRACTION) of everything spent on it, base
        cost plus any upgrades, not just the base cost."""
        return round(self.total_invested * settings.SELL_REFUND_FRACTION)

    @property
    def can_specialize(self):
        return self.is_max_level and self.specialization is None

    def specialization_cost(self):
        """Gold cost to choose a specialization, or None if not eligible
        right now (not maxed yet, or already specialized)."""
        if not self.can_specialize:
            return None
        return round(self.cost * self.SPECIALIZATION_COST_MULTIPLIER)

    def specialize(self, key):
        """Choose specialization `key` -- the one-time branching upgrade
        available once a tower hits MAX_LEVEL, applying that option's
        stat_multipliers on top of the tower's current stats. No-op
        (returns False) if not currently eligible or `key` isn't one of
        this tower's SPECIALIZATIONS."""
        if not self.can_specialize or key not in self.SPECIALIZATIONS:
            return False
        self.total_invested += self.specialization_cost()
        for stat_name, multiplier in self.SPECIALIZATIONS[key]["stat_multipliers"].items():
            setattr(self, stat_name, getattr(self, stat_name) * multiplier)
        self.specialization = key
        return True

    def _stat_after_next_upgrade(self, name):
        """What LEVEL_SCALED_STATS entry `name` would become after one
        more upgrade, without actually upgrading. Equal to its current
        value if already at MAX_LEVEL, or if this tower doesn't scale
        that stat with level at all."""
        if self.is_max_level or name not in self._base_stats:
            return getattr(self, name)
        next_level = self.level + 1
        return self._base_stats[name] * self._multiplier_table_for(name)[next_level]

    def range_after_next_upgrade(self):
        """Preview of `range` one level up -- used while hovering a
        tower's '+' badge, both for the range-ring preview and the stats
        panel (ui.py)."""
        return self._stat_after_next_upgrade("range")

    def damage_after_next_upgrade(self):
        """Preview of `damage` one level up -- see range_after_next_upgrade
        for the same idea applied to damage."""
        return self._stat_after_next_upgrade("damage")

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
        """In-range, still-on-the-path enemy furthest along it -- more
        robust than raw proximity on a path with switchbacks, and works
        unchanged regardless of which enemy species are involved. Must
        exclude enemies that already reached the goal, not just dead
        ones: Game.update() runs every tower's update() before it filters
        reached-goal enemies out of the live list for this frame, so
        without this check a tower could fire a brand-new shot at an
        enemy that's already effectively gone -- and since "furthest
        along the path" is the whole ranking, a just-arrived enemy would
        usually *win* that ranking over every real threat still on the
        path."""
        candidates = [e for e in enemies if not e.is_dead and not e.reached_goal and self.in_range(e)]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.distance_traveled)

    def in_range(self, enemy):
        return self.pos.distance_to(enemy.pos) <= self.range

    def create_projectile(self, target):
        raise NotImplementedError

    def tile_rect(self):
        """pygame.Rect for this tower's footprint -- always one tile's
        worth of area (settings.TILE_SIZE square), positioned at its
        subtile anchor rather than a tile boundary."""
        return pygame.Rect(self.anchor_col * settings.SUBTILE_SIZE, self.anchor_row * settings.SUBTILE_SIZE,
                            settings.TILE_SIZE, settings.TILE_SIZE)

    def contains_point(self, pos):
        """True if pixel position `pos` is anywhere on this tower's tile --
        used to show its stats/range on hover. Broader than
        contains_upgrade_badge() below, which is just the small clickable
        '+' circle that actually triggers an upgrade."""
        return self.tile_rect().collidepoint(pos)

    # --- Upgrade badge: the clickable "+cost" shown at a placed tower's
    # top-right corner. Geometry lives here (not in game.py/ui.py) so hit-
    # testing and drawing always agree on where it is. ---

    BADGE_RADIUS = 9

    def upgrade_badge_center(self):
        tile_left = self.anchor_col * settings.SUBTILE_SIZE
        tile_top = self.anchor_row * settings.SUBTILE_SIZE
        inset = self.BADGE_RADIUS + 2
        return (tile_left + settings.TILE_SIZE - inset, tile_top + inset)

    def contains_upgrade_badge(self, pos):
        """True if pixel position `pos` is within this tower's upgrade
        badge -- there is no badge (and this is always False) once the
        tower is at MAX_LEVEL, since there's nothing left to upgrade to."""
        if self.is_max_level:
            return False
        cx, cy = self.upgrade_badge_center()
        dx, dy = pos[0] - cx, pos[1] - cy
        return dx * dx + dy * dy <= self.BADGE_RADIUS ** 2

    def draw(self, surface, assets, font=None):
        # Sized almost edge-to-edge with the footprint (settings.TILE_SIZE
        # square) rather than with a big margin, so the sprite's own edges
        # make it obvious which subtiles the tower's anchor actually
        # covers -- the margin is just the same subtile gap the map's own
        # mosaic uses, not an arbitrary inset.
        margin = 2 * settings.SUBTILE_GAP
        size = (settings.TILE_SIZE - margin, settings.TILE_SIZE - margin)
        sprite = assets.get(self.sprite_name, size)
        rect = sprite.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        surface.blit(sprite, rect)
        self._draw_level_pips(surface, rect)
        if font is not None:
            self._draw_upgrade_badge(surface, font)

    def _draw_upgrade_badge(self, surface, font):
        cost = self.upgrade_cost()
        if cost is None:
            return  # already at max level -- nothing to upgrade to

        center = self.upgrade_badge_center()
        pygame.draw.circle(surface, settings.COLOR_BUTTON_SELECTED, center, self.BADGE_RADIUS)
        pygame.draw.circle(surface, (0, 0, 0), center, self.BADGE_RADIUS, width=1)

        plus_text = font.render("+", True, settings.COLOR_TEXT)
        surface.blit(plus_text, plus_text.get_rect(center=center))

        cost_text = font.render(str(cost), True, settings.COLOR_GOLD)
        surface.blit(cost_text, cost_text.get_rect(midtop=(center[0], center[1] + self.BADGE_RADIUS + 2)))

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
    # Cheap and unremarkable at level 1, but scales on damage much more
    # steeply than the generic curve so it stays a satisfying investment
    # late-game instead of being outclassed by pricier towers -- fair
    # numbers don't always make for a fun upgrade path. Range still uses
    # the generic LEVEL_STAT_MULTIPLIERS.
    LEVEL_STAT_MULTIPLIER_OVERRIDES = {"damage": {1: 1.0, 2: 1.7, 3: 2.6}}

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
    EXTRA_STATS = (("Splash radius", "splash_radius", _format_px),)

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
    EXTRA_STATS = (
        ("Slow", "slow_factor", _format_slow_percent),
        ("Slow duration", "slow_duration", _format_seconds),
    )

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
    EXTRA_STATS = (
        ("Splash radius", "splash_radius", _format_px),
        ("Knockback", "knockback_duration", _format_seconds),
    )

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.damage, splash_radius=self.splash_radius,
            knockback_duration=self.knockback_duration,
            sprite_name="projectile_knockback",
        )


class LightningTower(Tower):
    cost = 110
    range = 100
    damage = 8
    fire_rate = 1.0
    projectile_speed = 400.0
    # Max distance from one hit enemy to the next it can arc to -- kept
    # short since, unlike max_chain_targets, nothing else bounds how many
    # enemies a bolt can reach through a tightly packed cluster.
    chain_range = 50
    max_chain_targets = float("inf")  # arcs to every unvisited enemy it can reach, no cap
    sprite_name = "tower_lightning"
    display_name = "Lightning"
    EXTRA_STATS = (
        ("Chain range", "chain_range", _format_px),
        ("Max targets", "max_chain_targets", _format_count),
    )
    # Overrides the generic Power/Precision placeholders with options that
    # play off Lightning's own mechanic instead: a longer reach between
    # chain links, or more damage on every link a bolt hits (not just the
    # first target) -- create_projectile() below reads both straight off
    # self, so a chosen specialization applies to every shot fired after.
    SPECIALIZATIONS = {
        "arc_reach": {
            "display_name": "Arc Reach",
            "description": "Chains reach further.",
            "stat_multipliers": {"chain_range": 1.6},
        },
        "overcharge": {
            "display_name": "Overcharge",
            "description": "Harder-hitting chains.",
            "stat_multipliers": {"damage": 1.5},
        },
    }

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.damage, chain_range=self.chain_range,
            max_chain_targets=self.max_chain_targets,
            sprite_name="projectile_lightning",
        )


TOWER_TYPES = {
    "basic": BasicTower,
    "cannon": CannonTower,
    "frost": FrostTower,
    "knockback": KnockbackTower,
    "lightning": LightningTower,
}
